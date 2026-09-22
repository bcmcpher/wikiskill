"""The OpenCode evaluation backend: isolate, run headless, export, normalise.

Isolation is the whole point. A run must not see the developer's global config, project config,
Claude Code skills, MCP servers or plugins, because any of those would change what the model is
offered and quietly invalidate the comparison. OpenCode has no switch for "ignore global config", so
each run gets its own XDG directories, an inline config passed through
`OPENCODE_CONFIG_CONTENT`, and a throwaway git-initialised working directory.

What the model then did is read back twice: the `run --format json` stream says how the run ended,
and `opencode export` gives the full session — including every child session a `task` delegation
spawned — which is what becomes raw events.
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from .. import RAW_SCHEMA_VERSION, build, paths, rawlog
from ..collection import Collection
from ..frontmatter import read as read_frontmatter
from .base import INJECTED, OFF, ROUTED, Backend, PreflightResult, RunnerError, Trajectory, Unit
from .preflight import MIN_CONTEXT_TOKENS, Endpoint, check

#: Commands no evaluation may run, whatever a suite says. A task's own `guard.deny` adds to these.
BASE_DENY = (
    "git push*",
    "*git push*",
    "datalad push*",
    "sudo *",
    "ssh *",
    "rm -rf /*",
    "npm publish*",
    "pip install*",
    "uv publish*",
    "curl *",
    "wget *",
)

#: Tool parts whose error text means the harness or the guard refused the call, not that it failed.
_BLOCKED_MARKERS = ("wikiskill evaluation guard", "permission denied by", "rejected", "not allowed")

#: The guard's own words when a unit runs out of steps. Checked before `_BLOCKED_MARKERS`, which it
#: also matches: running out of steps is something the model did, not a permission it lacked. The
#: wording is the contract with `StepBudgetExhausted` in `harness/opencode/guard/`.
_STEP_EXHAUSTED_MARKER = "step budget of"

#: Shapes a model emits when it describes a tool call instead of making one.
_TOOL_SHAPED = ('"tool_call"', '"function_call"', "<tool_call>", '"tool_name"', '"arguments":')

#: The probe a harness-mediated preflight runs. It asks for something no prose can fake: a file on
#: disk. Deliberately not a skill — preflight asks whether the model can drive tools at all,
#: which is a precondition for routing, not a measurement of it.
PROBE_PROMPT = (
    "Create a file named probe.txt whose only contents are the word OK. "
    "Use your tools; do not describe the steps."
)
PROBE_FILE = "probe.txt"
PROBE_TIMEOUT_S = 300
PROBE_LIST_TIMEOUT_S = 120

#: `opencode export` on a long session is a few hundred kilobytes of JSON off local storage.
EXPORT_TIMEOUT_S = 120

_SKILL_TOOLS = {"skill", "skills"}
_TASK_TOOLS = {"task", "agent"}


def _ts(ms: int | float | None) -> str:
    """An RFC 3339 timestamp from harness epoch milliseconds, matching what the plugin writes."""
    when = time.time() if not ms else float(ms) / 1000.0
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(when)) + f".{int((when % 1) * 1000):03d}Z"


def _string_field(source: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = source.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _bound(text: str, limit: int) -> tuple[str, bool]:
    encoded = text.encode("utf-8")
    if len(encoded) <= limit:
        return text, False
    return encoded[:limit].decode("utf-8", "ignore"), True


class OpenCodeBackend(Backend):
    """Runs a unit in a fresh, isolated headless OpenCode session."""

    harness = "opencode"

    def __init__(
        self,
        *,
        collection: Collection | None,
        endpoint: Endpoint | None,
        layout,
        suite_root: Path,
        executable: str = "opencode",
        min_context: int = MIN_CONTEXT_TOKENS,
        output_limit_bytes: int = 16 * 1024,
        guard_plugin: Path | None = None,
    ) -> None:
        self.collection = collection
        self.endpoint = endpoint
        self.layout = layout
        self.suite_root = suite_root
        self.executable = executable
        self.min_context = min_context
        self.output_limit_bytes = output_limit_bytes
        self.guard_plugin = guard_plugin or _default_guard_plugin()
        self._version: str | None = None

    # ------------------------------------------------------------------ identity

    def version(self) -> str:
        if self._version is None:
            try:
                done = subprocess.run(
                    [self.executable, "--version"],
                    capture_output=True,
                    text=True,
                    timeout=30,
                    check=False,
                )
                self._version = done.stdout.strip() or "unknown"
            except (OSError, subprocess.SubprocessError) as exc:
                raise RunnerError(
                    f"cannot run {self.executable!r}: {exc}. Install OpenCode, or pass "
                    "--opencode with a path to it."
                ) from exc
        return self._version

    def preflight(self, model: str) -> PreflightResult:
        """Check a model along the path its units will actually take.

        With an endpoint the runner can address itself, that is plain OpenAI-compatible HTTP.
        Without one the harness holds the credential, and a direct probe would be wrong twice over:
        it may be refused for reasons the run would never hit — OpenCode's own free tier answers a
        direct POST with `FreeTierError: can only be used from within OpenCode` — and it tests a
        path no unit uses. So the probe goes through `opencode run` instead.
        """
        if self.endpoint is not None:
            return check(self.endpoint, _model_id(model), min_context=self.min_context)
        return self.harness_preflight(model)

    def harness_preflight(self, model: str) -> PreflightResult:
        """Reachability, model listing, a tool-call probe and context, all through the harness."""
        details: dict[str, Any] = {"via": "harness", "model": model}
        root = Path(self.layout.root) / "preflight" / model.replace("/", "-").replace(":", "-")
        for name in ("config", "data", "state", "cache"):
            (root / name).mkdir(parents=True, exist_ok=True)
        env = self._env(root, self._config(model), list(BASE_DENY))

        try:
            details["harness_version"] = self.version()
        except RunnerError as exc:
            return PreflightResult(model=model, ok=False, problems=(str(exc),), details=details)

        listed = self._harness_models(env)
        details["models_listed"] = len(listed)
        if listed and model not in listed:
            provider_id = _split_model(model)[0]
            near = ", ".join(sorted(m for m in listed if m.startswith(f"{provider_id}/"))[:3])
            hint = f" This provider offers: {near}." if near else ""
            return PreflightResult(
                model=model,
                ok=False,
                problems=(
                    (
                        f"{self.executable} does not offer {model!r}. Check the name against "
                        f"`{self.executable} models`, or fix the manifest's alias table.{hint}"
                    ),
                ),
                details=details,
            )

        problems: list[str] = []
        stream, made_file = self._probe(model, root, env)
        details["probe_tools"] = _stream_tool_calls(stream)
        details["probe_wrote_file"] = made_file
        verdict = probe_verdict(stream, produced_file=made_file, model=model)
        if verdict:
            problems.append(verdict)

        if self.min_context > 0:
            context, source = catalog_context(_read_catalog(root / "cache"), model)
            details["context_tokens"] = context
            details["context_source"] = source
            if context is None:
                problems.append(
                    f"could not establish the context window {self.executable} serves {model} "
                    "with. Re-run with --min-context 0 to accept it unchecked, once you know it is "
                    f"at least {self.min_context} tokens."
                )
            elif context < self.min_context:
                problems.append(
                    f"{model} is served with a {context}-token context ({source}), below the "
                    f"{self.min_context} tokens OpenCode's system prompt and tool schemas need. "
                    "Choose a model with a larger context for this suite."
                )

        return PreflightResult(
            model=model, ok=not problems, problems=tuple(problems), details=details
        )

    def _harness_models(self, env: dict[str, str]) -> list[str]:
        """Every `provider/model` the harness offers, as it reports them itself."""
        try:
            done = subprocess.run(
                [self.executable, "models"],
                capture_output=True,
                text=True,
                timeout=PROBE_LIST_TIMEOUT_S,
                env=env,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return []
        return [line.strip() for line in done.stdout.splitlines() if "/" in line.strip()]

    def _probe(self, model: str, root: Path, env: dict[str, str]) -> tuple[list[dict], bool]:
        """Ask the model to do one thing no amount of prose can fake: write a file with a tool."""
        workdir = root / "work"
        if workdir.exists():
            shutil.rmtree(workdir)
        workdir.mkdir(parents=True)
        _git_init(workdir)
        try:
            done = subprocess.run(
                [
                    self.executable,
                    "run",
                    "--format",
                    "json",
                    "--dir",
                    str(workdir),
                    "-m",
                    model,
                    PROBE_PROMPT,
                ],
                capture_output=True,
                text=True,
                timeout=PROBE_TIMEOUT_S,
                env=env,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return _probe_failure(f"the probe did not finish within {PROBE_TIMEOUT_S}s"), False
        except OSError as exc:
            return _probe_failure(str(exc)), False
        (root / "probe.ndjson").write_text(done.stdout, encoding="utf-8")
        if done.stderr:
            (root / "probe.stderr").write_text(done.stderr, encoding="utf-8")
        return _parse_stream(done.stdout), (workdir / PROBE_FILE).is_file()

    # ------------------------------------------------------------------ isolation

    def prepare(self, unit: Unit) -> Path:
        """Build the unit's isolated root and return its working directory."""
        root = self.layout.unit_dir(unit)
        for name in ("config", "data", "state", "cache"):
            (root / name).mkdir(parents=True, exist_ok=True)
        workdir = root / "work"
        if workdir.exists():
            shutil.rmtree(workdir)
        fixtures = self.suite_root / unit.task.fixtures if unit.task.fixtures else None
        if fixtures and fixtures.is_dir():
            shutil.copytree(fixtures, workdir)
        else:
            if fixtures:
                raise RunnerError(
                    f"task {unit.task.id!r} names a fixture directory that is not there: {fixtures}"
                )
            workdir.mkdir(parents=True)
        _run_setup(unit, workdir, root)
        # After setup, so a command that makes its own repository (`datalad create`) finds an
        # ordinary directory; on an existing repository this is a harmless re-initialisation.
        _git_init(workdir)

        (root / "config.json").write_text(
            json.dumps(self.config_for(unit), indent=2) + "\n", encoding="utf-8"
        )
        if unit.condition in (ROUTED, INJECTED) and self.collection is not None:
            # INJECTED installs too: the point is to compare routing against content with the same
            # neighbourhood present, and a component that is absent cannot be denied either.
            self._install_collection(root)
            agent = _injected_agent(unit)
            if agent:
                _promote_to_primary(root, agent)
        return workdir

    def _install_collection(self, root: Path) -> None:
        """Put the components under test into this run's own config, and nothing else.

        ROUTED means "the collection is discoverable the way it normally would be", so every
        component the collection declares is installed — not only the watched ones. A near-miss
        neighbour that is missing would make a routing result meaningless: the model cannot choose
        wrongly between two skills when only one of them is there.

        The source repository is never touched: each source tree is built into the run's own staging
        directory and copied from there.
        """
        collection = self.collection
        if collection is None:
            return
        target = root / "config" / "opencode"
        target.mkdir(parents=True, exist_ok=True)

        staged = root / "built"
        try:
            # Pins stripped: every subagent runs on the model this unit evaluates.
            built = build.build_collection("opencode", collection, staged, strip_models=True)
        except build.BuildError as exc:
            raise RunnerError(f"collection {collection.name!r} cannot be installed: {exc}") from exc
        installed = _merge_tree(staged, target)
        if built.warnings:
            (root / "build-warnings.txt").write_text(
                "\n".join(built.warnings) + "\n", encoding="utf-8"
            )
        if not installed:
            raise RunnerError(
                f"collection {collection.name!r} produced no installable components, so ROUTED "
                "would be identical to OFF"
            )

    def config_for(self, unit: Unit, root: Path | None = None) -> dict[str, Any]:
        """The inline config a unit runs under. Only the target provider, and no MCP at all."""
        config = self._config(unit.model)
        if unit.condition == INJECTED:
            self._inject(config, unit, root)
        return config

    def _inject(self, config: dict[str, Any], unit: Unit, root: Path | None) -> None:
        """Force a skill's text into context while forbidding the model to load it itself.

        This is the measurement that separates routing from content. Under ROUTED the model has to
        find the skill; under INJECTED it is given the same words and cannot reach for the tool, so
        the difference between the two is what the routing cost, and the difference from OFF is what
        the words were worth.

        An agent needs none of this: `execute` runs it directly with `--agent`, which bypasses
        delegation the same way.
        """
        if root is None or _injected_agent(unit):
            return
        name = _bare(unit.task.expect.primary)
        if not name:
            return
        text = root / "config" / "opencode" / "skills" / name / "SKILL.md"
        if not text.is_file():
            raise RunnerError(
                f"INJECTED needs the text of {unit.task.expect.primary!r}, and the collection "
                f"built no skill at {text}"
            )
        config["instructions"] = [str(text)]
        # An `instructions` file the model could also load through the skill tool would measure
        # neither condition: it would be ROUTED with a head start.
        permission = config.setdefault("permission", {})
        permission["skill"] = {name: "deny"}

    def _config(self, model: str) -> dict[str, Any]:
        """The same config a preflight probe runs under, which is the point: they must match.

        A provider the harness resolves itself gets no block here. Declaring one would replace the
        credential and routing OpenCode supplies for its own models with a bare OpenAI-compatible
        endpoint, and the isolation the rest of this config buys is unaffected either way.
        """
        provider_id, model_id = _split_model(model)
        config: dict[str, Any] = {
            "$schema": "https://opencode.ai/config.json",
            "autoupdate": False,
            "share": "disabled",
            "mcp": {},
            "permission": {
                "edit": "allow",
                "webfetch": "deny",
                "external_directory": "deny",
                "bash": {"*": "allow"},
            },
        }
        if self.endpoint is not None:
            config["provider"] = {
                provider_id: {
                    "npm": "@ai-sdk/openai-compatible",
                    "name": provider_id,
                    "options": {"baseURL": self.endpoint.root},
                    "models": {model_id: {"name": model_id}},
                }
            }
        if self.guard_plugin is not None:
            config["plugin"] = [str(self.guard_plugin)]
        return config

    def env_for(self, unit: Unit, root: Path) -> dict[str, str]:
        """The environment one unit runs in: isolated XDG, inline config, discovery switched off."""
        return self._env(
            root,
            self.config_for(unit, root),
            list(BASE_DENY) + list(unit.task.guard_deny),
            max_steps=unit.task.max_steps,
            task_env=dict(unit.task.env),
        )

    def _env(
        self,
        root: Path,
        config: dict[str, Any],
        deny: list[str],
        max_steps: int | None = None,
        task_env: dict[str, str] | None = None,
    ) -> dict[str, str]:
        env = dict(os.environ)
        # The suite's own variables go in first, so nothing it sets can undo the isolation below.
        env.update(task_env or {})
        env.update(
            {
                "XDG_CONFIG_HOME": str(root / "config"),
                "XDG_DATA_HOME": str(root / "data"),
                "XDG_STATE_HOME": str(root / "state"),
                "XDG_CACHE_HOME": str(root / "cache"),
                "OPENCODE_CONFIG_CONTENT": json.dumps(config),
                "OPENCODE_DISABLE_PROJECT_CONFIG": "true",
                "OPENCODE_DISABLE_CLAUDE_CODE": "1",
                "WIKISKILL_GUARD_DENY": json.dumps(deny),
                # `opencode run` has no step limit of its own, so the guard counts tool calls and
                # refuses the one past the budget. Absent for a probe, which has no task behind it.
                "WIKISKILL_MAX_STEPS": str(max_steps) if max_steps else "",
                # The logger plugin is inert without a runtime config, and this run has none: eval
                # events come from `normalize`, so nothing writes the log twice.
                "WIKISKILL_ORIGIN": "eval",
            }
        )
        env.pop("OPENCODE_CONFIG", None)
        return env

    def debug(self, unit: Unit, *args: str) -> Any:
        """Run `opencode debug ...` inside a unit's own environment and parse its JSON.

        This is how a run proves its isolation rather than asserting it: the config and skill list
        recorded in the manifest are the ones the model was actually given.
        """
        root = self.layout.unit_dir(unit)
        try:
            done = subprocess.run(
                [self.executable, "debug", *args],
                capture_output=True,
                text=True,
                timeout=120,
                env=self.env_for(unit, root),
                check=False,
            )
            return json.loads(done.stdout) if done.stdout.strip() else {"error": done.stderr[-500:]}
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
            return {"error": str(exc)}

    def isolation_proof(self, unit: Unit) -> dict[str, Any]:
        """The loaded configuration and skill list for one unit, for the run manifest.

        Taken whether or not that unit ever ran: a run whose models all failed preflight should
        still say what the model *would* have been given, because that is what makes the next
        attempt debuggable.
        """
        try:
            self.prepare(unit)
        except (RunnerError, OSError) as exc:
            return {"condition": unit.condition, "error": str(exc)}
        config = self.debug(unit, "config")
        skills = self.debug(unit, "skill")
        names: list[str] = []
        if isinstance(skills, list):
            names = [
                str(entry.get("name") if isinstance(entry, dict) else entry) for entry in skills
            ]
        elif isinstance(skills, dict) and isinstance(skills.get("skills"), list):
            names = [str(entry.get("name", entry)) for entry in skills["skills"]]
        return {
            "condition": unit.condition,
            "config": config,
            "skills": names,
            "mcp": (config.get("mcp") if isinstance(config, dict) else None) or {},
        }

    # ------------------------------------------------------------------ execution

    def execute(self, unit: Unit) -> Trajectory:
        root = self.layout.unit_dir(unit)
        try:
            workdir = self.prepare(unit)
        except (RunnerError, OSError) as exc:
            return Trajectory(unit=unit, outcome="infra_error", error=str(exc), reason=str(exc))

        command = [
            self.executable,
            "run",
            "--format",
            "json",
            "--dir",
            str(workdir),
            "-m",
            unit.model,
        ]
        agent = _injected_agent(unit)
        if agent:
            # Running the agent directly is the agent's INJECTED: it gets the task without the
            # delegation step that ROUTED measures.
            command += ["--agent", agent]
        command.append(unit.task.prompt)
        started = time.time()
        try:
            done = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=unit.task.timeout_s,
                env=self.env_for(unit, root),
                check=False,
            )
            stdout, stderr, exit_code = done.stdout, done.stderr, done.returncode
        except subprocess.TimeoutExpired:
            reason = f"timed out after {unit.task.timeout_s}s"
            return Trajectory(
                unit=unit,
                outcome="infra_error",
                error=reason,
                reason=reason,
                duration_ms=int((time.time() - started) * 1000),
                workdir=workdir,
            )
        except OSError as exc:
            return Trajectory(unit=unit, outcome="infra_error", error=str(exc), reason=str(exc))

        duration_ms = int((time.time() - started) * 1000)
        (root / "run.ndjson").write_text(stdout, encoding="utf-8")
        if stderr:
            (root / "run.stderr").write_text(stderr, encoding="utf-8")

        stream = _parse_stream(stdout)
        session_id = _session_id(stream)
        if session_id is None:
            reason = (
                f"{self.executable} produced no session (exit {exit_code}). "
                + (stderr.strip().splitlines() or ["no stderr"])[-1]
            )
            return Trajectory(
                unit=unit,
                outcome="infra_error",
                error=reason,
                reason=reason,
                duration_ms=duration_ms,
                exit_code=exit_code,
                workdir=workdir,
            )

        try:
            sessions = self.export_sessions(session_id, root)
        except RunnerError as exc:
            return Trajectory(
                unit=unit,
                outcome="infra_error",
                session_id=session_id,
                error=str(exc),
                reason=str(exc),
                duration_ms=duration_ms,
                exit_code=exit_code,
                workdir=workdir,
            )
        (root / "sessions.json").write_text(json.dumps(sessions, indent=2), encoding="utf-8")

        trajectory = Trajectory(
            unit=unit,
            outcome="completed",
            sessions=sessions,
            session_id=session_id,
            duration_ms=duration_ms,
            exit_code=exit_code,
            workdir=workdir,
        )
        trajectory.activations = activations(sessions)
        trajectory.tokens = _token_totals(sessions)
        trajectory.final_text = _final_text(sessions)
        trajectory.transcript = _transcript(sessions)
        trajectory.outcome, trajectory.error = classify(stream, sessions)
        mismatch = agent_mismatch(unit, sessions)
        if mismatch:
            trajectory.outcome, trajectory.error, trajectory.reason = (
                "infra_error",
                mismatch,
                mismatch,
            )
        return trajectory

    def export_sessions(self, session_id: str, root: Path) -> list[dict[str, Any]]:
        """The root session and every child session a delegation spawned, breadth first.

        Each export goes to a file rather than a pipe. `opencode export` exits without draining a
        pipe, so anything past 64 KiB arrives truncated — and a truncated export is unparseable, so
        a long session would lose its whole trajectory and be scored as a run that activated
        nothing. Writing to a file gets all of it; keeping the file also leaves the evidence on disk
        next to the run.

        Failure raises. A trajectory that could not be read back says nothing about the model, and
        the caller turns that into `infra_error` rather than an empty session list that scores like
        a miss.
        """
        env = dict(os.environ)
        env.update(
            {
                "XDG_CONFIG_HOME": str(root / "config"),
                "XDG_DATA_HOME": str(root / "data"),
                "XDG_STATE_HOME": str(root / "state"),
                "XDG_CACHE_HOME": str(root / "cache"),
                "OPENCODE_DISABLE_PROJECT_CONFIG": "true",
                "OPENCODE_DISABLE_CLAUDE_CODE": "1",
            }
        )
        exports = root / "exports"
        exports.mkdir(parents=True, exist_ok=True)

        seen: set[str] = set()
        pending = [session_id]
        exported: list[dict[str, Any]] = []
        while pending:
            current = pending.pop(0)
            if current in seen:
                continue
            seen.add(current)
            session = self._export_one(current, exports / f"{current}.json", env)
            exported.append(session)
            pending.extend(child for child in _child_session_ids(session) if child not in seen)
        return exported

    def _export_one(
        self, session_id: str, destination: Path, env: dict[str, str]
    ) -> dict[str, Any]:
        try:
            with destination.open("w", encoding="utf-8") as handle:
                done = subprocess.run(
                    [self.executable, "export", session_id],
                    stdout=handle,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=EXPORT_TIMEOUT_S,
                    env=env,
                    check=False,
                )
        except (OSError, subprocess.SubprocessError) as exc:
            raise RunnerError(f"could not export session {session_id}: {exc}") from exc

        if done.returncode != 0:
            last = (done.stderr or "").strip().splitlines()
            raise RunnerError(
                f"{self.executable} export {session_id} exited {done.returncode}: "
                + (last[-1] if last else "no stderr")
            )
        try:
            session = json.loads(destination.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RunnerError(
                f"the export of session {session_id} is not readable JSON "
                f"({destination.stat().st_size if destination.exists() else 0} bytes): {exc}"
            ) from exc
        if not isinstance(session, dict):
            raise RunnerError(f"the export of session {session_id} is not a session object")
        return session

    # ------------------------------------------------------------------ normalisation

    def normalize(self, trajectory: Trajectory) -> list[dict[str, Any]]:
        """Raw events for one trajectory, in the order things happened.

        Every event carries `origin: eval` and the unit's provenance, so an evaluation reads back
        from the raw log per task, condition and repeat without a side file.
        """
        unit = trajectory.unit
        provider, model = _split_model(unit.model)
        root_session = trajectory.session_id or ""
        collection = self.collection.name if self.collection else unit.suite
        events: list[dict[str, Any]] = []

        for session in trajectory.sessions:
            info = session.get("info") or {}
            session_id = str(info.get("id") or root_session)
            parent_id = info.get("parentID") or None
            component: dict[str, Any] | None = None

            def make(
                event_type: str,
                payload: dict[str, Any],
                ts: str,
                *,
                session_id: str = session_id,
                parent_id: str | None = parent_id,
                component: dict[str, Any] | None = None,
                info: dict[str, Any] = info,
            ) -> dict[str, Any]:
                return {
                    "schema_version": RAW_SCHEMA_VERSION,
                    "event_id": rawlog.new_event_id(),
                    "ts": ts,
                    "origin": "eval",
                    "eval": unit.provenance(),
                    "harness": self.harness,
                    "harness_version": str(info.get("version") or self.version()),
                    "provider": provider,
                    "model": model,
                    "collection": collection,
                    "session_id": session_id,
                    "root_session_id": root_session or session_id,
                    "parent_session_id": parent_id,
                    "component": component,
                    "type": event_type,
                    "payload": payload,
                }

            created = _ts((info.get("time") or {}).get("created"))
            events.append(
                make(
                    "session_start",
                    {
                        "cwd": info.get("directory"),
                        "title": info.get("title"),
                        "agent": info.get("agent"),
                    },
                    created,
                )
            )

            for message in session.get("messages") or []:
                message_info = message.get("info") or {}
                role = message_info.get("role")
                message_ts = _ts((message_info.get("time") or {}).get("created"))
                for part in message.get("parts") or []:
                    for event, activated in self._part_events(
                        part, role, message_ts, make, component
                    ):
                        if activated is not None:
                            component = activated
                        events.append(event)
                error = message_info.get("error")
                if isinstance(error, dict):
                    message_text = _string_field(error.get("data") or {}, "message") or str(
                        error.get("name") or "error"
                    )
                    events.append(
                        make(
                            "error",
                            {"message": message_text, "where": "session", "fatal": True},
                            message_ts,
                            component=component,
                        )
                    )

            ended = _ts((info.get("time") or {}).get("updated"))
            events.append(
                make(
                    "session_end",
                    {"reason": "export", "duration_ms": trajectory.duration_ms or None},
                    ended,
                    component=component,
                )
            )
        return events

    def _part_events(self, part, role, message_ts, make, component):
        """Events for one part, each with the component it should be attributed to."""
        kind = part.get("type")
        produced: list[tuple[dict[str, Any], dict[str, Any] | None]] = []

        if kind == "text" and role == "assistant":
            text = part.get("text") or ""
            limited, truncated = _bound(text, self.output_limit_bytes)
            produced.append(
                (
                    make(
                        "assistant_turn",
                        {
                            "text": limited,
                            "text_length": len(text),
                            "finish_reason": "truncated_by_logger" if truncated else None,
                        },
                        _ts((part.get("time") or {}).get("end"))
                        if part.get("time")
                        else message_ts,
                        component=component,
                    ),
                    None,
                )
            )
        elif kind == "step-finish":
            tokens = part.get("tokens") or {}
            cache = tokens.get("cache") or {}
            produced.append(
                (
                    make(
                        "step_usage",
                        {
                            "tokens": {
                                "input": tokens.get("input"),
                                "output": tokens.get("output"),
                                "reasoning": tokens.get("reasoning"),
                                "cache_read": cache.get("read"),
                                "cache_write": cache.get("write"),
                            },
                            "cost": part.get("cost"),
                        },
                        message_ts,
                        component=component,
                    ),
                    None,
                )
            )
        elif kind == "tool":
            produced.extend(self._tool_events(part, message_ts, make, component))
        return produced

    def _tool_events(self, part, message_ts, make, component):
        """An activation, a delegation and the call itself, in the order they happened."""
        state = part.get("state") or {}
        status = state.get("status")
        if status not in ("completed", "error"):
            return []
        tool = str(part.get("tool") or "").lower()
        args = state.get("input") or {}
        metadata = state.get("metadata") or {}
        times = state.get("time") or {}
        ts = _ts(times.get("end") or times.get("start")) if times else message_ts
        produced: list[tuple[dict[str, Any], dict[str, Any] | None]] = []
        activated = None

        hint = self._activation(tool, args, metadata)
        if hint:
            activated = {"kind": hint[0], "name": hint[1], "source_hash": hint[2]}
            produced.append(
                (
                    make(
                        "component_activated",
                        {
                            "trigger": hint[3],
                            "source_path": hint[4],
                            "input_summary": (
                                _string_field(args, "description", "prompt", "query") or None
                            ),
                        },
                        ts,
                        component=activated,
                    ),
                    activated,
                )
            )
            component = activated

        if tool in _TASK_TOOLS:
            produced.append(
                (
                    make(
                        "delegation",
                        {
                            "subagent_type": _string_field(
                                args, "subagent_type", "subagentType", "agent", "name"
                            )
                            or "unknown",
                            "child_session_id": _string_field(
                                metadata, "sessionID", "sessionId", "session_id"
                            ),
                            "description": _string_field(args, "description", "prompt"),
                        },
                        ts,
                        component=component,
                    ),
                    None,
                )
            )

        output_value = state.get("output")
        raw_output = output_value if isinstance(output_value, str) else ""
        limited, truncated = _bound(raw_output, self.output_limit_bytes)
        start, end = times.get("start"), times.get("end")
        duration = int(end - start) if isinstance(start, int) and isinstance(end, int) else None
        produced.append(
            (
                make(
                    "tool_call",
                    {
                        "tool": str(part.get("tool") or "unknown"),
                        "call_id": part.get("callID"),
                        "ok": status == "completed",
                        "input": args or None,
                        "output": limited,
                        "output_length": len(raw_output),
                        "output_truncated": truncated,
                        "output_hash": None,
                        "error": state.get("error") if status == "error" else None,
                        "duration_ms": duration,
                    },
                    ts,
                    component=component,
                ),
                activated,
            )
        )
        return produced

    def _activation(self, tool, args, metadata):
        """``(kind, name, source_hash, trigger, source_path)`` when a call activated a component."""
        if tool in _SKILL_TOOLS:
            name = _string_field(args, "name", "skill", "skill_name")
            if name and self._watched("skill", name):
                directory = _string_field(metadata, "dir", "directory", "path")
                source = f"{directory}/SKILL.md" if directory else None
                return (
                    "skill",
                    name,
                    rawlog.file_hash(source) if source else None,
                    "skill_tool",
                    source,
                )
        elif tool in _TASK_TOOLS:
            name = _string_field(args, "subagent_type", "subagentType", "agent", "name")
            if name and self._watched("agent", name):
                source = _string_field(metadata, "path", "agentPath", "file")
                return (
                    "agent",
                    name,
                    rawlog.file_hash(source) if source else None,
                    "task_tool",
                    source,
                )
        return None

    def _watched(self, kind: str, name: str) -> bool:
        """During an evaluation every component of the collection counts, watch list or not.

        A suite names the route it expects; refusing to record an activation because the manifest's
        watch list is narrower would make the run unscorable.
        """
        if self.collection is None:
            return False
        if self.collection.matches(kind, name):
            return True
        bare = name.rsplit("/", maxsplit=1)[-1]
        return any(
            component.kind == kind and component.name.split("/")[-1] == bare
            for component in self.collection.discover()
        )


# --------------------------------------------------------------------------- stream reading


def _parse_stream(stdout: str) -> list[dict[str, Any]]:
    """`run --format json` is NDJSON: one event object per line, and nothing else."""
    events = []
    for raw_line in stdout.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            events.append(parsed)
    return events


def _session_id(stream: list[dict[str, Any]]) -> str | None:
    for event in stream:
        for key in ("sessionID", "sessionId", "session_id"):
            value = event.get(key)
            if isinstance(value, str) and value:
                return value
        info = event.get("info")
        if isinstance(info, dict) and isinstance(info.get("sessionID"), str):
            return info["sessionID"]
    return None


def _child_session_ids(session: dict[str, Any]) -> list[str]:
    """Child sessions a `task` delegation spawned, taken from the tool part's metadata."""
    found = []
    parent = str((session.get("info") or {}).get("id") or "")
    for message in session.get("messages") or []:
        for part in message.get("parts") or []:
            if part.get("type") != "tool":
                continue
            metadata = (part.get("state") or {}).get("metadata") or {}
            child = _string_field(metadata, "sessionID", "sessionId", "session_id")
            if child and child != parent:
                found.append(child)
    return found


def _iter_parts(sessions: list[dict[str, Any]]):
    for session in sessions:
        for message in session.get("messages") or []:
            yield message, (message.get("parts") or [])


def activations(sessions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Every component the model loaded or delegated to, in the order it did so.

    Taken from the calls themselves rather than from the collection's watch list: a route the suite
    expects may name a component the manifest does not watch, and a routing miss is only visible if
    the component that was chosen instead is recorded too.

    A call the harness refused is recorded with `blocked: true` rather than dropped. Under INJECTED
    the expected skill is denied on purpose, so the model reaching for it is worth keeping — but it
    did not reach it, and the scorer must not read the attempt as an activation.
    """
    found: list[dict[str, Any]] = []
    for _, parts in _iter_parts(sessions):
        for part in parts:
            if part.get("type") != "tool":
                continue
            state = part.get("state") or {}
            if state.get("status") not in ("completed", "error"):
                continue
            tool = str(part.get("tool") or "").lower()
            args = state.get("input") or {}
            entry: dict[str, Any] | None = None
            if tool in _SKILL_TOOLS:
                name = _string_field(args, "name", "skill", "skill_name")
                if name:
                    entry = {"kind": "skill", "name": name}
            elif tool in _TASK_TOOLS:
                name = _string_field(args, "subagent_type", "subagentType", "agent", "name")
                if name:
                    entry = {"kind": "agent", "name": name}
            if entry is None:
                continue
            if _refused(state):
                entry["blocked"] = True
            found.append(entry)
    return found


#: What OpenCode says when a `permission` rule refuses a tool call, alongside the guard's own words.
_REFUSAL_MARKERS = (
    "prevents you from using this specific tool call",
    *_BLOCKED_MARKERS,
)


def _refused(state: dict[str, Any]) -> bool:
    """Whether the harness refused this call rather than the call itself going wrong."""
    if state.get("status") != "error":
        return False
    message = str(state.get("error") or "").lower()
    return any(marker in message for marker in _REFUSAL_MARKERS)


def _token_totals(sessions: list[dict[str, Any]]) -> dict[str, int]:
    totals = {"input": 0, "output": 0, "reasoning": 0}
    for _, parts in _iter_parts(sessions):
        for part in parts:
            if part.get("type") != "step-finish":
                continue
            tokens = part.get("tokens") or {}
            for key in totals:
                value = tokens.get(key)
                if isinstance(value, int):
                    totals[key] += value
    return totals


def _final_text(sessions: list[dict[str, Any]]) -> str:
    text = ""
    for session in sessions[:1]:
        for message in session.get("messages") or []:
            if (message.get("info") or {}).get("role") != "assistant":
                continue
            for part in message.get("parts") or []:
                if part.get("type") == "text" and isinstance(part.get("text"), str):
                    text = part["text"]
    return text


def _transcript(sessions: list[dict[str, Any]]) -> str:
    """Every text part of every session, joined — including children, so a delegated answer counts.

    A `regex` verifier with `target: transcript` asks "was this said at any point", which is a
    different question from `final_text`'s "was this the answer".
    """
    chunks = []
    for session in sessions:
        for message in session.get("messages") or []:
            for part in message.get("parts") or []:
                if part.get("type") == "text" and isinstance(part.get("text"), str):
                    chunks.append(part["text"])
    return "\n".join(chunks)


def classify(
    stream: list[dict[str, Any]], sessions: list[dict[str, Any]]
) -> tuple[str, str | None]:
    """How a unit ended, and the harness's own words for it.

    Behaviour and infrastructure are told apart here, before anything is scored: a model that cannot
    be given tools is an `api_error`, not a skill that failed.
    """
    error_text = None
    for event in stream:
        if event.get("type") != "error":
            continue
        data = (event.get("error") or {}).get("data") or {}
        error_text = _string_field(data, "message") or str((event.get("error") or {}).get("name"))

    tool_parts = [
        part for _, parts in _iter_parts(sessions) for part in parts if part.get("type") == "tool"
    ]
    for part in tool_parts:
        state = part.get("state") or {}
        message = str(state.get("error") or "").lower()
        if _STEP_EXHAUSTED_MARKER in message:
            return "step_exhausted", state.get("error")
        if any(marker in message for marker in _BLOCKED_MARKERS):
            return "permission_blocked", state.get("error")

    if error_text:
        return "api_error", error_text

    if not tool_parts:
        final = _final_text(sessions)
        if any(marker in final for marker in _TOOL_SHAPED):
            return "tool_call_as_text", "the assistant described a tool call instead of making one"
    return "completed", None


# --------------------------------------------------------------------------- helpers


def _bare(name: str | None) -> str:
    """The component half of a `<plugin>/<component>` name. Built trees use the bare name."""
    return name.rsplit("/", 1)[-1] if name else ""


def _promote_to_primary(root: Path, agent: str) -> None:
    """Let `--agent` run a subagent, in this run's config only.

    The build marks every collection agent `mode: subagent`, which is right for delegation and for
    ROUTED. But `opencode run --agent` refuses a subagent and silently falls back to the default
    agent, so INJECTED would measure the wrong agent. `all` keeps it usable both ways.
    """
    path = root / "config" / "opencode" / "agents" / f"{agent}.md"
    if not path.is_file():
        raise RunnerError(
            f"INJECTED needs agent {agent!r}, and the collection built none at {path}"
        )
    document = read_frontmatter(path)
    meta = dict(document.meta)
    meta["mode"] = "all"
    path.write_text(document.render(meta), encoding="utf-8")


def agent_mismatch(unit: Unit, sessions: list[dict[str, Any]]) -> str | None:
    """Why a unit that was to run an agent directly did not, or None when it did.

    OpenCode falls back to its default agent with only a warning on stderr, and the unit would then
    measure that agent instead of the one under test.
    """
    requested = _injected_agent(unit)
    ran = _root_agent(sessions)
    if requested and ran != requested:
        return f"asked the harness to run agent {requested!r}, but the session ran {ran!r}"
    return None


def _root_agent(sessions: list[dict[str, Any]]) -> str | None:
    """The agent the root session actually ran as."""
    if not sessions:
        return None
    info = sessions[0].get("info") or {}
    agent = info.get("agent")
    return agent if isinstance(agent, str) else None


def _injected_agent(unit: Unit) -> str:
    """The agent a unit runs directly, or empty when it does not run one."""
    expect = unit.task.expect
    if unit.condition != INJECTED or expect.skill:
        return ""
    return _bare(expect.agent)


def _split_model(model: str) -> tuple[str, str]:
    provider, _, rest = model.partition("/")
    return (provider, rest) if rest else ("unknown", model)


def _model_id(model: str) -> str:
    return _split_model(model)[1]


def _probe_failure(message: str) -> list[dict[str, Any]]:
    """A stream standing in for one the harness never produced, so one reader handles both."""
    return [{"type": "error", "error": {"data": {"message": message}}}]


def _stream_tool_calls(stream: list[dict[str, Any]]) -> list[str]:
    """The tools a `run --format json` stream shows the model actually calling."""
    names = []
    for event in stream:
        part = event.get("part")
        if not isinstance(part, dict) or part.get("type") != "tool":
            continue
        if ((part.get("state") or {}).get("status")) in ("completed", "error"):
            names.append(str(part.get("tool") or "unknown"))
    return names


def _stream_text(stream: list[dict[str, Any]]) -> str:
    chunks = []
    for event in stream:
        part = event.get("part")
        if isinstance(part, dict) and part.get("type") == "text":
            text = part.get("text")
            if isinstance(text, str):
                chunks.append(text)
    return "\n".join(chunks)


def _stream_error(stream: list[dict[str, Any]]) -> str | None:
    for event in stream:
        if event.get("type") != "error":
            continue
        data = (event.get("error") or {}).get("data") or {}
        message = data.get("message") or (event.get("error") or {}).get("name")
        if message:
            return str(message)
    return None


def probe_verdict(stream: list[dict[str, Any]], *, produced_file: bool, model: str) -> str | None:
    """What the tool-call probe proved. `None` means it passed.

    Either a tool ran or the file exists — both are proof of a real call, and the second survives a
    stream shape this parser has not seen. Everything else is a reason the model would score zero
    for causes that have nothing to do with the skills under test.
    """
    if produced_file or _stream_tool_calls(stream):
        return None
    error = _stream_error(stream)
    if error:
        return (
            f"{model} failed the tool-call probe: {error}. A model that cannot be given tools "
            "cannot drive a skill; choose a tool-calling model for this suite."
        )
    if any(marker in _stream_text(stream) for marker in _TOOL_SHAPED):
        return (
            f"{model} printed a tool call instead of making one. Skills are driven by real tool "
            "calls, so this model would score zero regardless of the skills under test."
        )
    return (
        f"{model} answered the tool-call probe with text instead of calling a tool, and wrote no "
        f"{PROBE_FILE}. Skills are driven by tool calls, so this model would score zero for "
        "reasons that have nothing to do with the skills under test."
    )


def _read_catalog(cache_root: Path) -> dict[str, Any]:
    """The models.dev catalog the harness fetched into this probe's own cache.

    Read from the run's cache rather than the developer's, so preflight reports what the isolated
    run was told, not what some other configuration happens to hold.
    """
    path = cache_root / "opencode" / "models.json"
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def catalog_context(catalog: dict[str, Any], model: str) -> tuple[int | None, str]:
    """The context window the catalog advertises for a model, and where the number came from.

    Unlike Ollama, a hosted provider's context is a property of the model rather than of a server
    setting, so the catalog is the authority and there is no local override to consult.
    """
    provider_id, model_id = _split_model(model)
    entry = ((catalog.get(provider_id) or {}).get("models") or {}).get(model_id)
    if not isinstance(entry, dict):
        return None, "unknown"
    context = (entry.get("limit") or {}).get("context")
    if isinstance(context, int) and context > 0:
        return context, f"the models.dev catalog entry for {provider_id}/{model_id}"
    return None, "unknown"


def _merge_tree(staged: Path, target: Path) -> int:
    """Copy a built tree into the run's config, skipping build bookkeeping. Returns files copied."""
    copied = 0
    for path in sorted(staged.rglob("*")):
        if not path.is_file() or path.name == build.BUILD_MARKER:
            continue
        destination = target / path.relative_to(staged)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)
        copied += 1
    return copied


#: One setup command's budget. Setup builds a starting state; it is not where work happens.
SETUP_TIMEOUT_S = 300


def _run_setup(unit: Unit, workdir: Path, root: Path) -> None:
    """Run a task's setup commands in its workdir, logging each to `setup.log`.

    A command that fails raises `RunnerError`, which the caller records as `infra_error`: a unit
    that never reached its starting state says nothing about the model.
    """
    if not unit.task.setup:
        return
    env = {**os.environ, **dict(unit.task.env)}
    with (root / "setup.log").open("w", encoding="utf-8") as log:
        for command in unit.task.setup:
            log.write(f"$ {command}\n")
            try:
                done = subprocess.run(
                    command,
                    shell=True,
                    cwd=workdir,
                    capture_output=True,
                    text=True,
                    errors="replace",
                    timeout=SETUP_TIMEOUT_S,
                    env=env,
                    check=False,
                )
            except subprocess.TimeoutExpired as exc:
                raise RunnerError(
                    f"setup `{command}` for task {unit.task.id!r} did not finish within "
                    f"{SETUP_TIMEOUT_S}s"
                ) from exc
            except OSError as exc:
                raise RunnerError(f"setup `{command}` could not be started: {exc}") from exc
            log.write(done.stdout + done.stderr)
            if done.returncode != 0:
                tail = (done.stderr or done.stdout).strip().splitlines()[-3:]
                raise RunnerError(
                    f"setup `{command}` for task {unit.task.id!r} exited {done.returncode}"
                    + (f": {' / '.join(tail)}" if tail else "")
                )


def _git_init(workdir: Path) -> None:
    """A workdir is a git repo so the harness can snapshot it, and so verifiers can diff it."""
    # A run without git still works; only the harness's own snapshotting is lost.
    with contextlib.suppress(OSError, subprocess.SubprocessError):
        subprocess.run(
            ["git", "init", "--quiet", str(workdir)],
            capture_output=True,
            timeout=60,
            check=False,
        )


def _default_guard_plugin() -> Path | None:
    """The guard plugin, whether running from a checkout or an installed wheel."""
    found = paths.packaged_data("opencode-guard") / "wikiskill-guard.ts"
    return found if found.is_file() else None


__all__ = ["BASE_DENY", "OFF", "ROUTED", "OpenCodeBackend", "classify"]
