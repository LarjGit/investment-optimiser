# Repository Guidance

## Purpose
This repository builds a local decision-support tool for UK SIPP portfolio allocation.
It is recommendation-only, not trade automation.

The stable product and architecture source of truth is `docs/system-design.md`.

## Default Workflow
When a task starts from a GitHub issue, use the repo's `$implement` workflow by default instead of jumping straight to edits.

For issue-driven work:
- resolve the repository from `git remote get-url origin`
- read the issue with `gh issue view <number> --json number,title,body,comments`
- follow the `$implement` phases before editing, including loading any lessons in `docs/solutions/` when present, scanning the codebase, doing external research, producing a plan, and waiting for approval before implementation

## Design Guardrails
Keep changes aligned with `docs/system-design.md`.

Do not collapse the product into a gilt-only tool.

Preserve the distinction between current holdings as implementation state and the strategic baseline as decision truth.

Preserve explainability, auditability, and replayability as first-class requirements.

## Commands
Run the app:
`uv run streamlit run app.py`

Run tests:
`uv run pytest`
