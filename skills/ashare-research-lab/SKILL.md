---
name: ashare-research-lab
description: Use this skill when working on the ashare-research-lab A-share research system, including running fixture workflows, factor validation, candidate scans, scoring, backtests, service queries, scheduled jobs, and explaining generated reports. Use it whenever the user asks to operate, inspect, debug, or extend this repository's research workflows.
---

# Ashare Research Lab

Use this Skill as an operation guide for the repo-local A-share research workflow. It is not core business logic and does not replace the Python package, CLI, tests, or planning docs.

## First Checks

1. Confirm the current directory is `ashare-research-lab`:

```bash
pwd
test -f pyproject.toml && test -d src/ashare
```

2. Check the worktree before changing files:

```bash
git status --short
```

If the worktree is dirty, preserve unrelated user edits. Do not revert files you did not change unless the user explicitly asks.

3. Run all Python commands through the Conda environment:

```bash
conda run -n ashare-research-lab python -m pip install -e .
```

## Common Workflow

Build deterministic fixtures:

```bash
conda run -n ashare-research-lab python scripts/build_fixtures.py --output-dir tests/fixtures/generated
```

Ingest fixture CSVs:

```bash
conda run -n ashare-research-lab ashare ingest-local --input-dir tests/fixtures/generated --db-path data/processed/ashare_phase4.duckdb
```

Calculate factors:

```bash
conda run -n ashare-research-lab ashare calculate-factors --from 2026-03-30 --to 2026-06-26 --db-path data/processed/ashare_phase4.duckdb --index-code LOCAL_FIXTURE --source-run-id phase4-service
```

Create a factor validation report:

```bash
conda run -n ashare-research-lab ashare report --kind factor-validation --from 2026-03-30 --to 2026-06-26 --db-path data/processed/ashare_phase4.duckdb --source-run-id phase4-service --factor return_20d --factor return_60d --factor above_ma60 --factor pe_ttm_percentile --factor pb_percentile --factor revenue_yoy --factor profit_yoy --horizon 5,20 --output-dir data/reports/generated/phase4/factor-validation --overwrite
```

Run a candidate scan:

```bash
conda run -n ashare-research-lab ashare scan --as-of 2026-06-26 --db-path data/processed/ashare_phase4.duckdb --source-run-id phase4-service --sort-factor return_20d --factor return_20d --factor pe_ttm_percentile --factor revenue_yoy --top 3 --output-dir data/reports/generated/phase4/scan --overwrite
```

Run composite scoring:

```bash
conda run -n ashare-research-lab ashare score --as-of 2026-06-26 --db-path data/processed/ashare_phase4.duckdb --source-run-id phase4-service --index-code LOCAL_FIXTURE --validation-dir data/reports/generated/phase4/factor-validation --diagnostics-from 2026-03-30 --diagnostics-to 2026-06-26 --horizon 5,20 --top 3 --output-dir data/reports/generated/phase4/scoring --overwrite
```

Run a topn backtest:

```bash
conda run -n ashare-research-lab ashare backtest --strategy topn-equal --from 2026-03-30 --to 2026-06-26 --db-path data/processed/ashare_phase4.duckdb --index-code LOCAL_FIXTURE --source-run-id phase4-service --sort-factor return_20d --top 3 --output-dir data/reports/generated/phase4/backtest --overwrite
```

Create a Phase 7 daily report from explicit audited artifacts:

```bash
conda run -n ashare-research-lab ashare daily-report --as-of 2026-06-26 --db-path data/processed/ashare_phase4.duckdb --source-run-id phase4-service --scan-run-id SCAN_RUN_ID --score-run-id SCORE_RUN_ID --backtest-run-id BACKTEST_RUN_ID --event-study-run-id EVENT_STUDY_RUN_ID --output-dir data/reports/generated/phase7/daily/daily-20260626 --run-id daily-20260626 --run-mode exploratory
```

Create a Phase 7 single-stock review report:

```bash
conda run -n ashare-research-lab ashare stock-report --code 000001.SZ --as-of 2026-06-26 --db-path data/processed/ashare_phase4.duckdb --source-run-id phase4-service --score-run-id SCORE_RUN_ID --output-dir data/reports/generated/phase7/stock/000001.SZ-20260626 --run-id stock-000001SZ-20260626 --run-mode exploratory
```

Run service smoke checks:

```bash
conda run -n ashare-research-lab ashare serve --help
conda run -n ashare-research-lab ashare service-workflow --name phase4-fixture-research --service-config configs/service.yaml --dry-run
conda run -n ashare-research-lab ashare service-scheduler --service-config configs/service.yaml --once --name phase4-fixture-research --dry-run
```

## Reading Artifacts

Generated reports live under `data/reports/generated/`. The common Phase 4 outputs are:

- factor validation: `factor_validation_report.md`, `coverage.csv`, `rank_ic.csv`, `ic_summary.csv`
- candidate scan: `candidate_list.md`, `candidates.csv`
- scoring: `scoring_report.md`, `scored_candidates.csv`, `score_metadata.json`
- backtest: `backtest_report.md`, `metrics.csv`, `equity_curve.csv`
- daily report: `daily_report.md`, `daily_candidates.csv`, `daily_score_summary.csv`, `daily_metadata.json`
- stock report: `stock_report.md`, `stock_factor_values.csv`, `stock_score_breakdown.csv`, `stock_metadata.json`
- data quality gate: `data_quality_gate.csv`, `data_quality_gate.json`

When explaining reports, keep the wording research-focused:

- Candidate lists are screening outputs, not a buy list.
- Composite scoring is a research ranking, not a trading instruction.
- Backtests are historical simulations with assumptions and costs, not executable performance promises.
- Daily reports and stock reports are review packets assembled from explicit audited artifacts, not trading instructions.
- Factor validation forward returns are statistical labels, not realized tradable returns.

Use the phrase `not a trading instruction` when summarizing candidate, scoring, or backtest output.

## Guardrails

- Do not commit generated artifacts, DuckDB files, workflow logs, fixture outputs, cache files, real announcement bodies, or raw LLM responses.
- Do not call real LLM APIs or real network data sources unless the user explicitly asks and the required configuration is already prepared.
- Do not put API keys, tokens, passwords, or other secrets in repo files.
- Do not describe any service response as a buy, sell, target price, position size, or automated trading signal.
- Do not implement research calculations inside the Skill. The Skill is only an operating manual.

See `references/commands.md` for command recipes and `references/artifacts.md` for artifact interpretation notes.
