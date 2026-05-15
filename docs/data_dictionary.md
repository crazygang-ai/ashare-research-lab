# Data Dictionary

This file is generated from `configs/data_dictionary.yaml` by `docs/build_data_dictionary.py`.
Do not maintain this Markdown file by hand.

## above_ma60

- type: factor
- source: daily_prices
- raw_fields: close, adj_factor
- formula: 1.0 if adjusted_close_t > mean(latest 60 adjusted close observations including t) else 0.0
- unit: flag
- frequency: daily
- effective_date: daily_prices.trade_date <= explicit as_of_date
- direction: higher_is_better
- missing: skip when fewer than 60 valid price observations are available
- hard_filter: False
- soft_penalty: False
- description: Boolean momentum flag based on the latest 60 PIT-visible price observations.

## is_delisted

- type: hard_filter
- source: securities
- raw_fields: delist_date, delist_effective_date
- formula: 1.0 when is_delisted_as_of is true under PIT securities semantics, else 0.0
- unit: flag
- frequency: daily
- effective_date: securities.delist_effective_date visibility
- direction: lower_is_better
- missing: always writes 0.0 or 1.0 for every stock in the final universe
- hard_filter: True
- soft_penalty: False
- description: Delisting hard-filter flag based on Phase 1a-3.5 securities as-of semantics.

## is_st

- type: hard_filter
- source: st_status
- raw_fields: in_date, out_date, in_effective_date, out_effective_date
- formula: 1.0 when a PIT-visible ST interval is active as of as_of_date, else 0.0
- unit: flag
- frequency: daily
- effective_date: st_status interval effective-date visibility
- direction: lower_is_better
- missing: always writes 0.0 or 1.0 for every stock in the final universe
- hard_filter: True
- soft_penalty: False
- description: ST hard-filter flag computed from Phase 1a-3.5 interval as-of semantics.

## is_suspended

- type: hard_filter
- source: daily_prices
- raw_fields: is_suspended
- formula: 1.0 if current daily_prices.is_suspended is true or the current daily_prices row is missing, else 0.0
- unit: flag
- frequency: daily
- effective_date: daily_prices.trade_date == explicit as_of_date
- direction: lower_is_better
- missing: always writes 0.0 or 1.0 for every stock in the final universe
- hard_filter: True
- soft_penalty: False
- description: MVP unavailable-to-trade flag. A value of 1.0 means either a true suspension row exists for as_of_date or the universe stock has no daily_prices row for as_of_date and is conservatively treated as untradeable/data-insufficient.

## low_liquidity

- type: hard_filter
- source: daily_prices
- raw_fields: amount
- formula: 1.0 if avg(latest 20 amount observations including t) < min_avg_amount else 0.0
- unit: flag
- frequency: daily
- effective_date: daily_prices.trade_date <= explicit as_of_date
- direction: lower_is_better
- missing: skip when fewer than 20 amount observations are available
- hard_filter: True
- soft_penalty: False
- description: Conservative low-liquidity flag parameterized by configs/factors.yaml hard_filters.low_liquidity.params.

## pb_percentile

- type: factor
- source: valuation_daily
- raw_fields: pb
- formula: average_rank_percentile(current pb within latest valid single-stock valuation window)
- unit: percentile
- frequency: daily
- effective_date: valuation_daily.trade_date <= explicit as_of_date
- direction: lower_is_better
- missing: skip when pb <= 0 or valid observations are below min_observations
- hard_filter: False
- soft_penalty: False
- description: Single-stock rolling PB percentile over PIT-visible positive PB observations.

## pe_ttm_percentile

- type: factor
- source: valuation_daily
- raw_fields: pe_ttm
- formula: average_rank_percentile(current pe_ttm within latest valid single-stock valuation window)
- unit: percentile
- frequency: daily
- effective_date: valuation_daily.trade_date <= explicit as_of_date
- direction: lower_is_better
- missing: skip when pe_ttm <= 0 or valid observations are below min_observations
- hard_filter: False
- soft_penalty: False
- description: Single-stock rolling PE percentile over PIT-visible positive PE observations.

## profit_yoy

- type: factor
- source: fundamental_reports
- raw_fields: report_period, publish_time, effective_date, net_profit
- formula: current_net_profit / previous_year_same_period_net_profit - 1
- unit: ratio
- frequency: reporting
- effective_date: fundamental_reports.effective_date <= explicit as_of_date
- direction: higher_is_better
- missing: skip when strict prior-year same-period report is missing or previous net_profit <= 0
- hard_filter: False
- soft_penalty: False
- description: Latest visible report-period net profit growth, using latest publish_time revision for duplicate stock/report_period rows.

## return_20d

- type: factor
- source: daily_prices
- raw_fields: close, adj_factor
- formula: adjusted_close_t / adjusted_close_t_shift_20 - 1
- unit: ratio
- frequency: daily
- effective_date: daily_prices.trade_date <= explicit as_of_date
- direction: higher_is_better
- missing: skip when current or 20-observation lagged adjusted close is unavailable
- hard_filter: False
- soft_penalty: False
- description: 20 observed-price-row adjusted return using close * adj_factor, with null adj_factor treated as 1.0.

## return_60d

- type: factor
- source: daily_prices
- raw_fields: close, adj_factor
- formula: adjusted_close_t / adjusted_close_t_shift_60 - 1
- unit: ratio
- frequency: daily
- effective_date: daily_prices.trade_date <= explicit as_of_date
- direction: higher_is_better
- missing: skip when current or 60-observation lagged adjusted close is unavailable
- hard_filter: False
- soft_penalty: False
- description: 60 observed-price-row adjusted return using close * adj_factor.

## revenue_yoy

- type: factor
- source: fundamental_reports
- raw_fields: report_period, publish_time, effective_date, revenue
- formula: current_revenue / previous_year_same_period_revenue - 1
- unit: ratio
- frequency: reporting
- effective_date: fundamental_reports.effective_date <= explicit as_of_date
- direction: higher_is_better
- missing: skip when strict prior-year same-period report is missing or previous revenue <= 0
- hard_filter: False
- soft_penalty: False
- description: Latest visible report-period revenue growth, using latest publish_time revision for duplicate stock/report_period rows.
