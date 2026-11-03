# delta-router

- Default branch: `main`.
- Scope, architecture and decisions: `docs/DESIGN.md`. Read it before planning; changing a decision needs a decision-log line.
- Build: `uv sync`.
- Fast test: `uv run pytest -x -q`.
- Full test: `uv run pytest` (unit tests only; integration tests are deselected by default).
- Integration tests: `uv run pytest -m integration`. They call Azure or Databricks and can cost money: run only with the author's explicit go.
- Every test that calls Azure or Databricks gets `@pytest.mark.integration`. `--strict-markers` is on, so a misspelled marker fails the run.
- New top-level directories and `dqr` subpackages are created by the first task that puts a real file in them; no placeholders (DESIGN decision log, 2026-11-01).
- Lint: `uv run ruff check . && uv run ruff format --check .`
- Python 3.12 is managed by uv; the system `python3` is 3.10, so always go through `uv run`.
- Legacy v1 code is at tag `v1`: read with `git show v1:<path>`, never restore whole files or directories.
- Public repo, deployed to the author's company Azure tenant: never commit anything that identifies the company or its pre-existing resources (tenant, subscription, principal or object ids; names of existing resources such as managed identities, service principals, networks, resource groups, workspaces; names of groups or people) in code, tests, docs, specs or commit messages. Those values live only in the git-ignored `.env`; `.env.example` lists the names. Names of resources this repo's Bicep creates are fine. Check with `git log -p` before any push.
