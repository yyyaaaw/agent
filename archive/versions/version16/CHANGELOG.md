# Changelog

## Current

- Archived the pre-skill root implementation to `archive/versions/version15`.
- Added Agent v16 Skill Registry with built-in skills for daily reports, evaluation, memory search, source diagnosis, feedback learning, and MCP control.
- Added CLI commands for listing, recommending, planning, and optionally executing supported skills.
- Exposed skill discovery and planning through MCP tools.
- Added read-only MCP tools for source health and source plan inspection.
- Promoted the latest agent implementation to the repository root.
- Archived historical version folders under `archive/versions/`.
- Standardized the default SQLite database path as `data/agent.sqlite3`.
- Added a root `requirements.txt` for installable project dependencies.
- Added project documentation under `docs/`.
- Expanded offline evaluation with KPI summaries, source health, LLM token usage, and cost estimation.
- Added DeepSeek balance-delta cost tracking, with token-price estimation kept as a fallback.
- Added fixed regression evals under `evals/` and a `--eval-regression` CLI command.
- Added `run_id` to report and raw-news filenames to prevent same-day overwrite.
- Switched report generation batching to event-first prompts so one event is not split across LLM batches.
