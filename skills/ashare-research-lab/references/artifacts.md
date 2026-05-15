# Artifact Reference

The service artifact registry scans configured roots and recognizes these report directories:

- `scan`: `candidates.csv` and `candidate_list.md`
- `scoring`: `scoring_report.md`, `scored_candidates.csv`, and `score_metadata.json`
- `backtest`: `backtest_report.md`, `metrics.csv`, and `equity_curve.csv`
- `factor_validation`: `factor_validation_report.md`, `coverage.csv`, `rank_ic.csv`, and `ic_summary.csv`

Artifact records are file-based until a future phase connects them to `research_runs`.

Interpretation rules:

- `candidate_list.md` is a research screen, not a trading instruction.
- `scoring_report.md` is a composite research ranking, not a buy or sell recommendation.
- `backtest_report.md` describes historical simulation assumptions and is not a performance promise.
- `factor_validation_report.md` reports statistical validation labels and does not describe executable trading returns.

Do not commit generated artifact directories under `data/reports/generated/`.
