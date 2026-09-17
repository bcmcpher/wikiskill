"""The wheel has to carry the data the installed CLI reads.

These are the tests for the failure that only appears after `uv tool install`: the code looks for a
resource under the package, packaging never shipped it, and the development checkout hides the gap
because the fallback path is right there. Each of `paths.PACKAGED_DATA` is checked against
`pyproject.toml` and then against a layout assembled the way the wheel assembles it.
"""

from __future__ import annotations

import shutil
import tomllib
from pathlib import Path

import pytest

from wikiskill import paths
from wikiskill.install import _logger_files, _plugin_source

REPO = Path(__file__).resolve().parent.parent


def force_include() -> dict[str, str]:
    with (REPO / "pyproject.toml").open("rb") as handle:
        config = tomllib.load(handle)
    return config["tool"]["hatch"]["build"]["targets"]["wheel"]["force-include"]


@pytest.mark.parametrize("kind", sorted(paths.PACKAGED_DATA))
def test_every_packaged_resource_is_shipped_by_the_wheel(kind):
    packaged, in_checkout = paths.PACKAGED_DATA[kind]
    assert (REPO / in_checkout).exists(), f"{in_checkout} is missing from the checkout"

    prefix = f"wikiskill/{packaged}"
    # A mapping covers the resource whether it names it exactly, ships a directory containing it,
    # or ships the files inside it one by one.
    covered = [
        (source, target)
        for source, target in force_include().items()
        if target == prefix
        or target.startswith(f"{prefix}/")
        or prefix.startswith(f"{target}/")
    ]
    assert covered, (
        f"nothing in pyproject.toml's force-include ships {prefix}, so an installed wikiskill "
        f"cannot read the {kind!r} resource"
    )
    for source, _ in covered:
        assert (REPO / source).exists(), f"force-include names {source}, which does not exist"


@pytest.fixture
def wheel_layout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The package directory as the wheel lays it out, with nothing else beside it."""
    package = tmp_path / "site-packages" / "wikiskill"
    package.mkdir(parents=True)
    for source, target in force_include().items():
        if not target.startswith("wikiskill/"):
            continue
        destination = package / target[len("wikiskill/") :]
        destination.parent.mkdir(parents=True, exist_ok=True)
        origin = REPO / source
        if origin.is_dir():
            shutil.copytree(origin, destination)
        else:
            shutil.copy(origin, destination)
    monkeypatch.setattr(paths, "package_dir", lambda: package)
    return package


def test_the_schema_resolves_inside_an_installed_package(wheel_layout):
    found = paths.schema_path()
    assert found.is_relative_to(wheel_layout)
    assert found.is_file()


def test_the_source_tree_resolves_inside_an_installed_package(wheel_layout):
    found = paths.source_tree()
    assert found.is_relative_to(wheel_layout)
    assert (found / "skills").is_dir()


def test_the_opencode_logger_resolves_inside_an_installed_package(wheel_layout):
    found = _plugin_source("opencode")
    assert found.is_relative_to(wheel_layout)
    assert (found / "wikiskill-logger.ts").is_file()


def test_the_installed_logger_is_the_same_file_set_as_the_checkout(wheel_layout):
    from_wheel = set(_logger_files("opencode"))
    assert from_wheel
    assert all(name.startswith("plugin/") for name in from_wheel)
    # Compared against the checkout, so a new module in the plugin cannot be left out of the wheel.
    checkout = REPO / "harness" / "opencode" / "plugin"
    expected = {
        f"plugin/{path.relative_to(checkout)}"
        for path in checkout.rglob("*.ts")
        if path.is_file()
        and not {"test", "node_modules"} & set(path.relative_to(checkout).parts)
    }
    assert from_wheel == expected
