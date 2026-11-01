# delta-router

- Default branch: `main`.
- Scope, architecture and decisions: `docs/DESIGN.md`. Read it before planning; changing a decision needs a decision-log line.
- Build: `uv sync`.
- Fast test: `uv run pytest -x -q`.
- Full test: `uv run pytest` (unit tests only; integration tests are deselected by default).
- Integration tests: `uv run pytest -m integration`. They call Azure or Databricks and can cost money: run only with the author's explicit go.
- Lint: `uv run ruff check . && uv run ruff format --check .`
- Python 3.12 is managed by uv; the system `python3` is 3.10, so always go through `uv run`.
- Legacy v1 code is at tag `v1`: read with `git show v1:<path>`, never restore whole files or directories.
