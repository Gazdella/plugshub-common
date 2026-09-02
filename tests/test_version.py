"""`__version__` must never drift from the packaging metadata again.

It was hardcoded in `plugshub_common/__init__.py` and stayed at "0.4.1" while
pyproject went 0.4.1 -> 0.4.2 -> 0.4.3 -> 0.5.0. Anyone reading
`plugshub_common.__version__` to find out what a service was running got 0.4.1
regardless of what was installed, which is how a fleet-wide version audit reached
the wrong conclusion on 2026-09-02, mid-incident.
"""

import re
import tomllib
from importlib.metadata import version as pkg_version
from pathlib import Path

import plugshub_common


def test_version_matches_the_installed_package_metadata():
    assert plugshub_common.__version__ == pkg_version("plugshub-common")


def test_version_is_not_hardcoded_in_the_source():
    """The mechanism, not just today's value: a literal here is what drifted."""
    src = (Path(plugshub_common.__file__)).read_text()
    literal = re.search(r'^__version__\s*=\s*["\']', src, re.MULTILINE)
    assert literal is None, (
        "__version__ is assigned a string literal again — derive it from the "
        "package metadata so a release cannot leave it behind"
    )


def test_version_agrees_with_pyproject():
    """The declared release number is the one source of truth."""
    root = Path(__file__).resolve().parents[1]
    pyproject = root / "pyproject.toml"
    if not pyproject.exists():  # installed-only environments
        return
    declared = tomllib.loads(pyproject.read_text())["project"]["version"]
    assert plugshub_common.__version__ == declared, (
        f"__version__ {plugshub_common.__version__} != pyproject {declared} — "
        "reinstall the package, or the metadata is stale"
    )
