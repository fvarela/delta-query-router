import tomllib
from pathlib import Path

import pytest

PYPROJECT = Path(__file__).parent.parent / "pyproject.toml"


def _write_repo_pytest_ini(pytester: pytest.Pytester) -> None:
    """Copy the repo's real [tool.pytest.ini_options] into a pytest.ini."""
    with PYPROJECT.open("rb") as f:
        options = tomllib.load(f)["tool"]["pytest"]["ini_options"]
    # testpaths points at the repo's tests/ directory, which the temporary
    # project does not have; every other option is copied as is.
    options.pop("testpaths", None)
    lines = ["[pytest]"]
    for key, value in options.items():
        if isinstance(value, list):
            value = "\n    " + "\n    ".join(value)
        lines.append(f"{key} = {value}")
    pytester.makeini("\n".join(lines) + "\n")


def test_integration_tests_are_deselected_by_default(pytester: pytest.Pytester):
    _write_repo_pytest_ini(pytester)
    pytester.makepyfile(
        """
        import pytest

        def test_plain():
            pass

        @pytest.mark.integration
        def test_costly():
            pass
        """
    )

    default = pytester.runpytest()
    default.assert_outcomes(passed=1, deselected=1)

    on_demand = pytester.runpytest("-m", "integration")
    on_demand.assert_outcomes(passed=1, deselected=1)


def test_unknown_marker_is_an_error(pytester: pytest.Pytester):
    _write_repo_pytest_ini(pytester)
    pytester.makepyfile(
        """
        import pytest

        @pytest.mark.integraton
        def test_typo():
            pass
        """
    )

    result = pytester.runpytest()
    result.assert_outcomes(passed=0, errors=1)
    result.stdout.fnmatch_lines(["*'integraton' not found in `markers`*"])
