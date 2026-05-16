# Data Dictionary

This file is generated from configs/data_dictionary.yaml by docs/build_data_dictionary.py.
Do not edit by hand.

## daily_prices.adj_factor

- section: schema_fields
- description: 后复权近似因子；动量因子使用 close * adj_factor，adj_factor 为空时 fallback 到 close。
- pit_visibility: daily_prices.trade_date <= as_of_date
- source: daily_prices
- type: column
- unit: ratio

## daily_prices.amount

- section: schema_fields
- description: 单日成交额，low_liquidity 使用最近窗口内 amount 均值。
- pit_visibility: daily_prices.trade_date <= as_of_date
- source: daily_prices
- type: column
- unit: yuan

## daily_prices.is_suspended

- section: schema_fields
- description: 行情行上的真实停牌标志；缺失行情行不在本字段内表达。
- pit_visibility: daily_prices.trade_date == as_of_date for current-day tradability checks
- source: daily_prices
- type: column
- unit: boolean

## factor_run_universe.stock_code

- section: schema_fields
- description: 因子计算 run 在该 trade_date / as_of_date 使用的显式 universe 成员，用作验证、评分、回测和日报 gate 的覆盖率分母。
- pit_visibility: written together with the factor source_run_id
- source: factor_run_universe
- type: column
- unit: identifier

## factor_run_universe.universe_kind

- section: schema_fields
- description: 显式 universe 的来源类别；formal 历史验证和回测要求 historical_pit，current_snapshot 只能用于试点或探索。
- pit_visibility: metadata written together with factor_run_universe rows
- source: factor_run_universe
- type: column
- unit: category

## factor_values.as_of_date

- section: schema_fields
- description: 因子计算使用的显式 PIT 截止日期。
- pit_visibility: written by factor calculation for the requested as_of_date
- source: factor_values
- type: column
- unit: date

## factor_values.factor_value

- section: schema_fields
- description: 因子或硬过滤标志的数值输出。
- pit_visibility: derived only from inputs visible at factor_values.as_of_date
- source: factor_values
- type: column
- unit: numeric

## factor_values.source_run_id

- section: schema_fields
- description: 产生该因子值的 research_runs.run_id；Phase 8 通过 migration 级重复检查、DuckDB unique index 与写入层 fail-fast 治理 `(source_run_id, stock_code, trade_date, as_of_date, factor_name)` 唯一性。
- pit_visibility: metadata written after a calculation run
- source: factor_values
- type: column
- unit: identifier

## fundamental_reports.effective_date

- section: schema_fields
- description: 财报快照进入 PIT 查询可见集的日期。
- pit_visibility: effective_date <= as_of_date
- source: fundamental_reports
- type: column
- unit: date

## fundamental_reports.net_profit

- section: schema_fields
- description: 归母或口径一致的净利润字段；profit_yoy 使用同一 report_period 的最新可见修订。
- pit_visibility: fundamental_reports.effective_date <= as_of_date
- source: fundamental_reports
- type: column
- unit: yuan

## fundamental_reports.publish_time

- section: schema_fields
- description: 财报快照披露时间；同一 stock_code/report_period 多条可见记录取 publish_time 最新一条。
- pit_visibility: publish_time must be no later than the effective snapshot used by PIT
- source: fundamental_reports
- type: column
- unit: timestamp

## fundamental_reports.revenue

- section: schema_fields
- description: 营业收入字段；revenue_yoy 使用同一 report_period 的最新可见修订。
- pit_visibility: fundamental_reports.effective_date <= as_of_date
- source: fundamental_reports
- type: column
- unit: yuan

## industry_classifications.in_effective_date

- section: schema_fields
- description: 行业分类区间开始对 PIT 查询生效的日期。
- pit_visibility: in_effective_date <= as_of_date
- source: industry_classifications
- type: column
- unit: date

## industry_classifications.out_effective_date

- section: schema_fields
- description: 行业分类区间结束对 PIT 查询生效的日期；为空表示持续有效。
- pit_visibility: out_effective_date is null or out_effective_date > as_of_date
- source: industry_classifications
- type: column
- unit: date

## securities.delist_date

- section: schema_fields
- description: 证券实际退市日期。
- pit_visibility: visible only through securities delist PIT fields as of as_of_date
- source: securities
- type: column
- unit: date

## securities.delist_effective_date

- section: schema_fields
- description: 退市状态进入 PIT 查询可见集的日期。
- pit_visibility: delist_effective_date <= as_of_date
- source: securities
- type: column
- unit: date

## securities.delist_publish_time

- section: schema_fields
- description: 退市信息披露时间。
- pit_visibility: publish_time-backed metadata for delist_effective_date
- source: securities
- type: column
- unit: timestamp

## st_status.in_effective_date

- section: schema_fields
- description: ST 区间开始对 PIT 查询生效的日期。
- pit_visibility: in_effective_date <= as_of_date
- source: st_status
- type: column
- unit: date

## st_status.out_effective_date

- section: schema_fields
- description: ST 区间结束对 PIT 查询生效的日期；为空表示仍处于 ST 区间。
- pit_visibility: out_effective_date is null or out_effective_date > as_of_date
- source: st_status
- type: column
- unit: date

## universe_members.in_effective_date

- section: schema_fields
- description: 指数成分进入样本池对 PIT 查询生效的日期。
- pit_visibility: in_effective_date <= as_of_date
- source: universe_members
- type: column
- unit: date

## universe_members.out_effective_date

- section: schema_fields
- description: 指数成分退出样本池对 PIT 查询生效的日期；为空表示仍在样本池内。
- pit_visibility: out_effective_date is null or out_effective_date > as_of_date
- source: universe_members
- type: column
- unit: date

## valuation_daily.pb

- section: schema_fields
- description: 市净率，pb_percentile 使用单股票历史正值窗口计算。
- pit_visibility: valuation_daily.trade_date <= as_of_date
- source: valuation_daily
- type: column
- unit: multiple

## valuation_daily.pe_ttm

- section: schema_fields
- description: 滚动市盈率，pe_ttm_percentile 使用单股票历史正值窗口计算。
- pit_visibility: valuation_daily.trade_date <= as_of_date
- source: valuation_daily
- type: column
- unit: multiple

## above_ma60

- section: factors
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

## is_delisted

- section: factors
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

## is_st

- section: factors
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

## is_suspended

- section: factors
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

## low_liquidity

- section: factors
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

## pb_percentile

- section: factors
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

## pe_ttm_percentile

- section: factors
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

## profit_yoy

- section: factors
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

## return_20d

- section: factors
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

## return_60d

- section: factors
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

## revenue_yoy

- section: factors
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
