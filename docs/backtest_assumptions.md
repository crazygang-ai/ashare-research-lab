# Backtest Assumptions

Phase 1b implements a simple Top N equal-weight portfolio backtest for research
replay. The numeric defaults live in `configs/backtest.yaml`; this document
describes the assumptions in human-readable form.

## Strategy And Signals

- The strategy ranks the PIT universe by one explicit `sort_factor`.
- The input signal source is `factor_values` for an explicit `source_run_id`.
- Phase 8 backtests also read `factor_run_universe` for the explicit universe
  denominator and snapshot fingerprint when it is available; formal historical
  backtests require `universe_kind = historical_pit`.
- In formal mode, each executable signal date must have matching
  `factor_run_universe` rows for the requested `source_run_id` and `index_code`;
  missing snapshots, `current_snapshot`, and `unknown_legacy` fail fast.
- Price, valuation, security, and trading-calendar reads are source-isolated by
  the selected `data_source` / `source_tag`; a shared DuckDB with multiple
  sources must pass `--data-source` explicitly.
- The signal date is the final open trading day of each month in the requested
  interval.
- The portfolio selects the Top N stocks that pass the hard filters and have a
  non-missing sort factor.
- Selected stocks receive equal target weights. If fewer than N names pass, the
  actual selected count is equal-weighted.
- This phase does not calculate new factors and does not use candidate report
  files as input.

## PIT Input Rules

- Signal reads require `source_run_id`, `trade_date = signal_date`, and
  `as_of_date <= signal_date`; universe membership comes from the matching
  `factor_run_universe` snapshot when present.
- If multiple visible versions exist for the same stock and factor, the latest
  `as_of_date` is used.
- Duplicate rows at that latest `as_of_date` fail fast instead of being silently
  deduplicated. Phase 8 adds migration preflight checks and a DuckDB unique
  index over `(source_run_id, stock_code, trade_date, as_of_date, factor_name)`.
- `sort_factor` direction is read from `configs/data_dictionary.yaml`.
- Boolean hard-filter factors cannot be used as the `sort_factor`.
- Backtest runs are audited in `research_runs`, `research_run_inputs`,
  `research_artifacts`, and `run_manifest.json`; reports remain file artifacts,
  but their inputs and output files are indexed after Phase 5.

## Execution Timing

- Rebalancing is monthly.
- Orders generated from month-end signal date T execute at the next open trading
  day, T+1.
- Execution price is the T+1 open price from `daily_prices.open`.
- Sell orders are processed before buy orders.
- The notional base is the previous close NAV before the execution date.
- Buy orders are rounded down to the configured A-share board-lot size
  (`trading_rules.board_lot_size`, default 100 shares). Unfilled target notional
  remains cash. If the requested quantity can form at least one board lot but
  available cash cannot cover one board lot plus costs, the order is rejected
  with `reject_reason = insufficient_cash`.
- Sell orders are rounded down to board-lot multiples, but when
  `trading_rules.allow_odd_lot_sell = true` an existing residual odd-lot block
  may be sold once without splitting it. Full exits may sell the entire residual
  position. If no board lot or complete odd-lot residual can be sold, the order
  is rejected with `reject_reason = below_board_lot` and the residual holding
  remains.

## Trading Costs

- Commission is charged on both buys and sells.
- Stamp tax is charged only on sells.
- Minimum commission is applied per order.
- Slippage is applied in the execution price: buys pay above open and sells
  receive below open.
- Reports separately show `commission`, `stamp_tax`, `slippage_cost`,
  `total_cost`, `gross_return`, `net_return`, and `cost_drag`.

## Hard Filters And Trading Constraints

Signal selection uses hard filters from `factor_values`:

- `is_st == 0.0`
- `is_suspended == 0.0`
- `is_delisted == 0.0`
- `low_liquidity == 0.0`

Missing hard-filter values are treated conservatively and exclude the stock.

The matching layer uses execution-date trading data:

- `daily_prices.is_suspended` blocks both buys and sells.
- Missing `daily_prices` rows or invalid open prices block trading.
- Limit-up opens block buys.
- Limit-down opens block sells.
- Buy quantities must be board-lot multiples. Sell quantities are board-lot
  multiples plus, when present and requested, one complete odd-lot residual
  block; odd-lot residuals are not split.
- Delisting state comes from PIT `securities`, not from `factor_values`.

Rejected buy orders leave the target notional in cash. Rejected sell orders
continue to be held. Reports include `trade_ledger.csv` with `reject_reason`
values and a Markdown diagnostic summary for rejected orders and forced delist
exits.

## Delisting

- Delisted stocks cannot be bought.
- If a holding reaches a PIT-visible delisting state and has not been sold, it
  is force-exited.
- The default forced delist exit value is 0.0.
- Forced exits are written to `trade_ledger.csv` with
  `order_status = forced_delist_exit`, `executed_price = 0.0`, and
  `executed_notional = 0.0`.
- Delisted holdings are not silently removed from the historical ledger or
  metrics.

## NAV And Holdings

- Initial cash defaults to 1,000,000 yuan.
- NAV is calculated after each open trading date closes.
- Positions are valued using `daily_prices.close`.
- If a holding is missing the current close, the most recent visible close is
  used and a warning is recorded.
- This phase does not model dividends, bonus shares, rights issues, or other
  corporate-action cash flows.

## Benchmarks

The current schema has no real index行情 table, so Phase 1b uses two synthetic
benchmarks over the same PIT universe:

- Synthetic market-cap-weighted benchmark.
- Synthetic equal-weight benchmark.

Benchmark constituents are locked on the same monthly signal dates as the
portfolio and stay static until the next signal date. Market-cap weights prefer
`valuation_daily.float_mv` and fall back to `total_mv`. Benchmark returns use
`adjusted_close = close * adj_factor`; missing `adj_factor` falls back to close
and is disclosed in warnings.

Formal benchmark construction also requires historical PIT `universe_members`
for the selected `data_source`; current snapshots are not silently accepted as
formal benchmark constituents.

Suspended benchmark members or members missing a daily price row receive 0.0
return for that day and reduce reported coverage.

## Real Index 行情 Gap

Real index行情 is still not used in benchmark calculations. The intended future
interface is a source-isolated `index_daily_prices` table or provider output
separate from stock `daily_prices`, with at least:

- `index_code`
- `trade_date`
- `open`
- `high`
- `low`
- `close`
- `volume`
- `amount`
- `source`
- `source_tag`

Backtest benchmark code should only read real index行情 when an explicit config
such as `benchmark.real_index.enabled = true`, `benchmark.real_index.index_code`,
and `benchmark.real_index.source` is provided. It must not mix index行情 rows into
stock行情 tables. Until that implementation exists, enabling
`benchmark.real_index.enabled` fails fast instead of silently falling back to a
synthetic benchmark.

## Not Covered

- This report is for research replay only and is not a trading instruction.
- This report is a historical simulation and is not a performance promise.
- No new factors are computed.
- No multi-factor weighting, composite score, industry neutralization, style
  attribution, or industry attribution is implemented.
- No real index行情 is used.
- No corporate-action cash flow is modeled: cash dividends, bonus shares, rights
  issues, and related tax/accounting flows are not posted to portfolio cash or
  holdings.
- No partial fill, order-book depth, volume constraint, impact-cost model,
  shorting, leverage, parameter search, or walk-forward optimization is
  implemented.
- Backtest runs write audit metadata and artifact indexes, but detailed
  backtest result tables are still not persisted in DuckDB.
