# Command Reference

All Python and CLI commands should run through:

```bash
conda run -n ashare-research-lab ...
```

Install the repo in editable mode:

```bash
conda run -n ashare-research-lab python -m pip install -e .
```

Run the Phase 4 service locally:

```bash
conda run -n ashare-research-lab ashare serve --service-config configs/service.yaml
```

Dry-run the configured fixture workflow:

```bash
conda run -n ashare-research-lab ashare service-workflow --service-config configs/service.yaml --name phase4-fixture-research --dry-run
```

Dry-run the scheduler once:

```bash
conda run -n ashare-research-lab ashare service-scheduler --service-config configs/service.yaml --once --name phase4-fixture-research --dry-run
```

Generate a Phase 7 daily report from explicit audited artifacts:

```bash
conda run -n ashare-research-lab ashare daily-report --as-of 2026-06-26 --db-path data/processed/ashare_phase4.duckdb --source-run-id phase4-service --scan-run-id SCAN_RUN_ID --score-run-id SCORE_RUN_ID --backtest-run-id BACKTEST_RUN_ID --event-study-run-id EVENT_STUDY_RUN_ID --output-dir data/reports/generated/phase7/daily/daily-20260626 --run-id daily-20260626 --run-mode exploratory
```

Generate a Phase 7 single-stock report:

```bash
conda run -n ashare-research-lab ashare stock-report --code 000001.SZ --as-of 2026-06-26 --db-path data/processed/ashare_phase4.duckdb --source-run-id phase4-service --score-run-id SCORE_RUN_ID --output-dir data/reports/generated/phase7/stock/000001.SZ-20260626 --run-id stock-000001SZ-20260626 --run-mode exploratory
```

Run the full test suite:

```bash
conda run -n ashare-research-lab pytest -q
```
