# Factor Definitions

This file is generated from configs/data_dictionary.yaml by docs/build_data_dictionary.py.
Do not edit by hand.

## financial

### operating_cashflow_to_profit

- description: operating_cashflow_to_profit 使用最新 PIT 可见财报的 operating_cashflow / net_profit 衡量利润现金含量；字段来自 fundamental_reports，不使用未来修订。
- direction: higher_is_better
- effective_date: fundamental_reports.effective_date <= as_of_date
- factor_name: operating_cashflow_to_profit
- formula: latest_visible_operating_cashflow / latest_visible_net_profit
- frequency: report_period
- hard_filter: false
- missing: do not write when the latest PIT-visible report is missing, operating_cashflow is missing, net_profit is missing, or net_profit <= 0
- normalize: none
- outlier: none
- params: {}
- phase: 1a-4
- raw_fields: report_period, publish_time, effective_date, operating_cashflow, net_profit
- score_group: financial
- soft_penalty: false
- source: fundamental_reports
- type: factor
- unit: ratio

### profit_yoy

- description: 最新可见 report_period 的净利润同比；同一 stock_code/report_period 多条可见记录选择 publish_time 最新一条，同期基准严格匹配上一年同月同日，不向最近季度末或披露日回退。
- direction: higher_is_better
- effective_date: fundamental_reports.effective_date <= as_of_date
- factor_name: profit_yoy
- formula: current_net_profit / previous_year_same_period_net_profit - 1
- frequency: report_period
- hard_filter: false
- missing: do not write when strict prior-year same-period report is missing or previous net_profit <= 0
- normalize: none
- outlier: none
- params: {}
- phase: 1a-4
- raw_fields: report_period, publish_time, effective_date, net_profit
- score_group: financial
- soft_penalty: false
- source: fundamental_reports
- type: factor
- unit: ratio

### revenue_yoy

- description: 最新可见 report_period 的收入同比；同一 stock_code/report_period 多条可见记录选择 publish_time 最新一条，同期基准严格匹配上一年同月同日，不向最近季度末或披露日回退。
- direction: higher_is_better
- effective_date: fundamental_reports.effective_date <= as_of_date
- factor_name: revenue_yoy
- formula: current_revenue / previous_year_same_period_revenue - 1
- frequency: report_period
- hard_filter: false
- missing: do not write when strict prior-year same-period report is missing or previous revenue <= 0
- normalize: none
- outlier: none
- params: {}
- phase: 1a-4
- raw_fields: report_period, publish_time, effective_date, revenue
- score_group: financial
- soft_penalty: false
- source: fundamental_reports
- type: factor
- unit: ratio

## momentum

### above_ma60

- description: 使用 daily_prices 单股票 PIT 可见观测行中最近 60 个有效价格观测的均值，不使用 trading_calendar 日历偏移；少于 60 个观测时不写入。价格使用 adjusted_close = close * adj_factor，adj_factor 为空时 fallback 到 close。
- direction: higher_is_better
- effective_date: daily_prices.trade_date <= as_of_date; current row must be as_of_date
- factor_name: above_ma60
- formula: 1.0 if adjusted_close_t > mean(latest 60 adjusted_close observations including t) else 0.0
- frequency: daily
- hard_filter: false
- missing: do not write when fewer than 60 valid price observations are available
- normalize: none
- outlier: none
- params: {window_days: 60}
- phase: 1a-4
- raw_fields: close, adj_factor
- score_group: momentum
- soft_penalty: false
- source: daily_prices
- type: factor
- unit: boolean

### return_20d

- description: 20 个 daily_prices 单股票 PIT 可见观测行偏移收益率，使用 shift(20)，不是 trading_calendar 日历偏移；停牌日如果存在 daily_prices 行仍计为一个观测；使用 adjusted_close = close * adj_factor，adj_factor 为空时 fallback 到 close。
- direction: higher_is_better
- effective_date: daily_prices.trade_date <= as_of_date; current row must be as_of_date
- factor_name: return_20d
- formula: adjusted_close_t / adjusted_close_shift_20 - 1
- frequency: daily
- hard_filter: false
- missing: do not write when current or 20-observation lagged adjusted close is missing or zero
- normalize: none
- outlier: none
- params: {window_days: 20}
- phase: 1a-4
- raw_fields: close, adj_factor
- score_group: momentum
- soft_penalty: false
- source: daily_prices
- type: factor
- unit: ratio

### return_60d

- description: 60 个 daily_prices 单股票 PIT 可见观测行偏移收益率，使用 shift(60)，不是 trading_calendar 日历偏移；停牌日如果存在 daily_prices 行仍计为一个观测；使用 adjusted_close = close * adj_factor，adj_factor 为空时 fallback 到 close。
- direction: higher_is_better
- effective_date: daily_prices.trade_date <= as_of_date; current row must be as_of_date
- factor_name: return_60d
- formula: adjusted_close_t / adjusted_close_shift_60 - 1
- frequency: daily
- hard_filter: false
- missing: do not write when current or 60-observation lagged adjusted close is missing or zero
- normalize: none
- outlier: none
- params: {window_days: 60}
- phase: 1a-4
- raw_fields: close, adj_factor
- score_group: momentum
- soft_penalty: false
- source: daily_prices
- type: factor
- unit: ratio

## risk

### amount_cv_20d

- description: amount_cv_20d 使用 daily_prices 中 PIT 可见的最近 20 个成交额观测计算变异系数，衡量成交额稳定性；它不是换手率，避免在缺少自由流通股本 PIT 字段时伪造 turnover。
- direction: lower_is_better
- effective_date: daily_prices.trade_date <= as_of_date; current row must be as_of_date
- factor_name: amount_cv_20d
- formula: std(latest 20 amount observations including t, ddof=0) / mean(latest 20 amount observations including t)
- frequency: daily
- hard_filter: false
- missing: do not write when fewer than 20 amount observations are available or the window mean amount <= 0
- normalize: none
- outlier: none
- params: {window_days: 20}
- phase: 1a-4
- raw_fields: amount
- score_group: risk
- soft_penalty: true
- source: daily_prices
- type: factor
- unit: ratio

### is_delisted

- description: 退市硬过滤标志，基于 securities 的 PIT 退市语义；1.0 表示 as_of_date 已进入退市状态。
- direction: boolean_filter
- effective_date: securities.delist_effective_date <= as_of_date
- factor_name: is_delisted
- formula: 1.0 when is_delisted_as_of is true under PIT securities semantics, else 0.0
- frequency: daily
- hard_filter: true
- missing: always write 0.0 or 1.0 for every stock in the final universe
- normalize: none
- outlier: none
- params: {}
- phase: 1a-4
- raw_fields: delist_date, delist_effective_date
- score_group: risk
- soft_penalty: false
- source: securities
- type: hard_filter
- unit: boolean

### is_st

- description: ST 硬过滤标志，使用 st_status 区间 effective_date 语义判断 as_of_date 是否处于 ST 状态。
- direction: boolean_filter
- effective_date: st_status.in_effective_date <= as_of_date and out_effective_date is null or > as_of_date
- factor_name: is_st
- formula: 1.0 when a PIT-visible ST interval is active as of as_of_date, else 0.0
- frequency: daily
- hard_filter: true
- missing: always write 0.0 or 1.0 for every stock in the final universe
- normalize: none
- outlier: none
- params: {}
- phase: 1a-4
- raw_fields: in_effective_date, out_effective_date
- score_group: risk
- soft_penalty: false
- source: st_status
- type: hard_filter
- unit: boolean

### is_suspended

- description: is_suspended = 1.0 在 MVP 下含义为不可交易，覆盖真实停牌与当日 daily_prices 行缺失两种场景；后续 phase 如需区分，应引入独立 data_missing 字段。
- direction: boolean_filter
- effective_date: daily_prices.trade_date == as_of_date for the current row; missing row is treated as unavailable
- factor_name: is_suspended
- formula: 1.0 if current daily_prices.is_suspended is true or the current daily_prices row is missing, else 0.0
- frequency: daily
- hard_filter: true
- missing: always write 0.0 or 1.0 for every stock in the final universe; missing current daily_prices row maps to 1.0
- normalize: none
- outlier: none
- params: {}
- phase: 1a-4
- raw_fields: is_suspended
- score_group: risk
- soft_penalty: false
- source: daily_prices
- type: hard_filter
- unit: boolean

### low_liquidity

- description: 低流动性硬过滤标志；默认最近 20 个 daily_prices 成交额观测均值低于 50,000,000 元时输出 1.0，窗口与阈值来自 configs/factors.yaml。
- direction: boolean_filter
- effective_date: daily_prices.trade_date <= as_of_date; current row must be as_of_date
- factor_name: low_liquidity
- formula: 1.0 if avg(latest 20 amount observations including t) < min_avg_amount else 0.0
- frequency: daily
- hard_filter: true
- missing: do not write when fewer than window_days amount observations are available
- normalize: none
- outlier: none
- params: {min_avg_amount: 50000000, window_days: 20}
- phase: 1a-4
- raw_fields: amount
- score_group: risk
- soft_penalty: false
- source: daily_prices
- type: hard_filter
- unit: boolean

### max_drawdown_60d

- description: max_drawdown_60d 使用 daily_prices 中 PIT 可见的最近 60 个 adjusted_close 观测计算窗口内最大回撤幅度，值越高表示近期路径风险越高。
- direction: lower_is_better
- effective_date: daily_prices.trade_date <= as_of_date; current row must be as_of_date
- factor_name: max_drawdown_60d
- formula: max(1.0 - adjusted_close_i / max(adjusted_close up to i)) over latest 60 adjusted_close observations including t
- frequency: daily
- hard_filter: false
- missing: do not write when fewer than 60 valid positive adjusted_close observations are available
- normalize: none
- outlier: none
- params: {window_days: 60}
- phase: 1a-4
- raw_fields: close, adj_factor
- score_group: risk
- soft_penalty: true
- source: daily_prices
- type: factor
- unit: ratio

### volatility_20d

- description: volatility_20d 使用 daily_prices 中 PIT 可见的最近 21 个 adjusted_close 观测得到 20 个日收益率，并计算 ddof=0 标准差；值越高表示近期波动风险越高。
- direction: lower_is_better
- effective_date: daily_prices.trade_date <= as_of_date; current row must be as_of_date
- factor_name: volatility_20d
- formula: std(latest 20 adjusted_close pct_change returns ending at t, ddof=0)
- frequency: daily
- hard_filter: false
- missing: do not write when fewer than 21 valid adjusted_close observations are available
- normalize: none
- outlier: none
- params: {window_days: 20}
- phase: 1a-4
- raw_fields: close, adj_factor
- score_group: risk
- soft_penalty: true
- source: daily_prices
- type: factor
- unit: ratio

## valuation

### industry_pe_ttm_percentile

- description: industry_pe_ttm_percentile 使用 valuation_daily 当前 PIT 可见 pe_ttm 与 industry_classifications 当前 PIT 可见一级行业，在行业内横截面排名；输出 0.0 到 1.0，越低表示相对同行估值越低。
- direction: lower_is_better
- effective_date: valuation_daily.trade_date == as_of_date and active industry_classifications interval is PIT-visible at as_of_date
- factor_name: industry_pe_ttm_percentile
- formula: average-rank percentile of current positive pe_ttm within the PIT-visible industry_l1 cross-section
- frequency: daily
- hard_filter: false
- missing: do not write when current pe_ttm <= 0, pe_ttm is missing, industry_l1 is missing, or the valid industry cross-section has fewer than min_industry_observations stocks
- normalize: none
- outlier: exclude non-positive pe_ttm values before industry percentile calculation
- params: {min_industry_observations: 2}
- phase: 1a-4
- raw_fields: pe_ttm, industry_l1, in_effective_date, out_effective_date
- score_group: valuation
- soft_penalty: false
- source: valuation_daily + industry_classifications
- type: factor
- unit: percentile_0_1

### pb_percentile

- description: pb_percentile 是单股票历史滚动分位，不是横截面分位；使用 valuation_daily 中 PIT 可见的正 pb 观测，trailing 252 个交易日且至少 20 个有效观测，输出 0.0 到 1.0。
- direction: lower_is_better
- effective_date: valuation_daily.trade_date <= as_of_date; current row must be as_of_date
- factor_name: pb_percentile
- formula: average-rank percentile of current positive pb within the latest valid single-stock valuation window
- frequency: daily
- hard_filter: false
- missing: do not write when current pb <= 0, pb is missing, or valid observations are below min_observations
- normalize: none
- outlier: exclude non-positive pb values before percentile calculation
- params: {min_observations: 20, window_days: 252}
- phase: 1a-4
- raw_fields: pb
- score_group: valuation
- soft_penalty: false
- source: valuation_daily
- type: factor
- unit: percentile_0_1

### pe_ttm_percentile

- description: pe_ttm_percentile 是单股票历史滚动分位，不是横截面分位；使用 valuation_daily 中 PIT 可见的正 pe_ttm 观测，trailing 252 个交易日且至少 20 个有效观测，输出 0.0 到 1.0。
- direction: lower_is_better
- effective_date: valuation_daily.trade_date <= as_of_date; current row must be as_of_date
- factor_name: pe_ttm_percentile
- formula: average-rank percentile of current positive pe_ttm within the latest valid single-stock valuation window
- frequency: daily
- hard_filter: false
- missing: do not write when current pe_ttm <= 0, pe_ttm is missing, or valid observations are below min_observations
- normalize: none
- outlier: exclude non-positive pe_ttm values before percentile calculation
- params: {min_observations: 20, window_days: 252}
- phase: 1a-4
- raw_fields: pe_ttm
- score_group: valuation
- soft_penalty: false
- source: valuation_daily
- type: factor
- unit: percentile_0_1
