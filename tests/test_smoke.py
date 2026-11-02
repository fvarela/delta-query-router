from pathlib import Path


def test_dqr_is_imported_from_repo_src():
    import dqr

    src = Path(__file__).resolve().parents[1] / "src" / "dqr"
    assert Path(dqr.__file__).resolve().is_relative_to(src)
