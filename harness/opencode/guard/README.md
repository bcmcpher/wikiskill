# wikiskill evaluation guard

A fail-closed OpenCode plugin installed **only** into an explicit evaluation run's isolated config.
It refuses the command patterns the running task declares under `guard.deny`, so a suite can let a
model commit inside its throwaway workdir while making `git push` impossible.

It never goes into a user's own configuration: the logger plugin is the one that runs during real
use, and it blocks nothing.

## Configuration

Per-unit, through the environment, because each task in a run denies something different.

| Variable | Meaning |
|---|---|
| `WIKISKILL_GUARD_DENY` | JSON array of glob patterns matched against each shell command |
| `WIKISKILL_GUARD_TOOLS` | JSON array of tool-name globs refused outright |

Patterns are anchored globs: `*` spans anything, `?` one character, every other regex metacharacter
is literal. A command line is also split on `&&`, `||`, `;`, `|` and newlines, so `cd x && git push`
is caught by `git push*`.

## Tests

```bash
bun test test
```
