# Personal skills catalog

Read README.md first. Canonical skill sources live in `skills/<name>/`; `tools/skills.py`
installs symlinks into local harnesses. Edit canonical sources, not independent copies.
Preserve other skills and existing installations; use the tool's conflict/backup paths.
Do not import system/plugin catalogs or publish to GitHub without a user request.

Skill changes: run `./tools/skills.py check <name>`. Tool changes: also run
`uv run --with pyyaml python -m unittest discover -s tests -v`.
Use a temporary `--home` and `--repo` for filesystem experiments; never test destructive
cases against the real harness directories. This repository manages skill definitions,
not live sprint statuses or project artifacts.
