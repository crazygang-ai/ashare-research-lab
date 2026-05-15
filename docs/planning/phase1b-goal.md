# Phase 1b Goal: 简单组合回测

请在已完成 Phase 1a 的 `/Users/crazy/own_project/ashare-research-lab` 仓库中继续实现 Phase 1b：简单组合回测。

本 phase 只做 Top N 等权组合回测：基于已落库的 `factor_values` 信号，在月末生成目标组合，T+1 开盘成交，加入交易成本和基础交易约束，并和市值加权 / 等权基准对比。

## 目标

1. 将现有 `ashare backtest` 从空壳改为真实回测命令。
2. 基于显式传入的 `source_run_id`、`sort_factor` 和 `index_code` 构造月末 Top N 等权组合。
3. 使用月末交易日 T 的信号，在 T+1 开盘执行调仓。
4. 加入手续费、印花税、滑点、最低佣金。
5. 分层处理信号选股硬过滤与撮合层交易约束：
   - 信号选股层使用 `factor_values` 中的 hard filter。
   - 撮合层使用 `daily_prices`、涨跌停字段和 `securities` PIT 退市状态。
6. 处理停牌、涨停不可买、跌停不可卖、退市强制退出。
7. 输出持仓、成交、调仓、净值曲线、指标和回测报告。
8. 对比同一 PIT universe 下的市值加权基准和等权基准。
9. 增加测试，覆盖调仓日、信号选择、交易约束、成本、退市、指标、CLI 和报告输出。

## 工作约束

- 严格遵守 `docs/planning/a-share-research-plan.md`。
- 所有 Python 命令必须在 Conda 环境 `ashare-research-lab` 中执行。
- 每个 phase 必须单独 commit。
- 本 phase 不计算新因子。
- 本 phase 不重新实现 Phase 1a-5 单因子验证。
- 本 phase 不重新实现 Phase 1a-6 候选报告。
- 本 phase 不重写 `factor_values`，依赖前置 `calculate-factors` 的 replace / fail-fast 行为。
- 本 phase 只读取 DuckDB，不写入 `factor_values`、`research_runs` 或任何新表。
- 本 phase 不修改 DuckDB schema。
- `backtest` 默认以 DuckDB `read_only=True` 打开数据库。
- 回测必须显式传入 `--from`、`--to`、`--source-run-id`、`--sort-factor`、`--index-code`，不能默认读取旧 run 或当前日期。
- `calculate-factors` 的区间必须覆盖 backtest 区间，且 `source_run_id` 必须一致；`signal_date` 当日缺少信号时按本 goal 的跳过 / fail-fast 规则处理。
- Phase 1b 完成后单独 commit。
- 提交信息为：`feat: phase 1b simple portfolio backtest`

## 文件变更

建议新增或修改：

```text
src/ashare/backtest/__init__.py
src/ashare/backtest/config.py
src/ashare/backtest/schedule.py
src/ashare/backtest/signals.py
src/ashare/backtest/costs.py
src/ashare/backtest/broker.py
src/ashare/backtest/benchmark.py
src/ashare/backtest/metrics.py
src/ashare/backtest/engine.py
src/ashare/reports/backtest_report.py
src/ashare/cli.py
configs/backtest.yaml
docs/backtest_assumptions.md
docs/planning/followups.md
tests/test_backtest_schedule.py
tests/test_backtest_signals.py
tests/test_backtest_broker.py
tests/test_backtest_benchmark.py
tests/test_backtest_metrics.py
tests/test_backtest_cli.py
```

可选修改：

```text
src/ashare/fixtures/builder.py
.gitignore
```

仅当现有 fixture 无法覆盖停牌、涨停不可买、跌停不可卖、退市强制退出等测试场景时，允许最小扩充 `src/ashare/fixtures/builder.py`，但不得改变既有 fixture 主样本范围、关键日期索引和前置 phase PIT 语义。

仅当当前仓库未忽略生成报告目录时，允许加入：

```gitignore
data/reports/generated/
```

本 phase 不应提交生成的回测报告、CSV、DuckDB 或缓存数据。

## 回测口径

### 输入

回测输入只来自：

```text
factor_values
daily_prices
trading_calendar
valuation_daily
universe_members
securities
configs/backtest.yaml
configs/data_dictionary.yaml
```

信号读取必须遵守 PIT 语义：

```text
source_run_id = ?
trade_date = signal_date
as_of_date <= signal_date
```

同一 `(source_run_id, stock_code, trade_date, factor_name)` 可能存在多个 `as_of_date` 可见版本时：

1. 取 `as_of_date <= signal_date` 中最大的 `as_of_date`。
2. 如果同一最大 `as_of_date` 下仍出现重复行，必须 fail-fast，错误信息打印至多 5 个重复样例。
3. 不允许 `drop_duplicates`、取第一行或聚合均值静默处理重复键。

`sort_factor` 的方向来自 `configs/data_dictionary.yaml`：

- `higher_is_better`：因子值越大越靠前。
- `lower_is_better`：因子值越小越靠前。
- `boolean_filter` 不允许作为 `sort_factor`。

### 调仓日

调仓频率固定为月频。

规则：

- `signal_date` 为 `--from` 到 `--to` 区间内每个月最后一个开市交易日。
- `execution_date` 为 `signal_date` 严格之后的下一个开市交易日。
- `execution_date` 必须 `<= --to`；如果越过 `--to`，跳过该次调仓并记录 warning。
- 如果某个 `signal_date` 没有对应的 `factor_values` 信号行，跳过该月并记录 warning。
- 如果 `execution_date` 不存在，跳过该次调仓并记录 warning。
- 如果全部月份都没有可执行信号，CLI 非 0 退出并说明没有可回测信号。

### Top N 等权组合

每个 `signal_date`：

1. 读取该日 PIT universe：`query_universe_members_as_of(index_code=...)`。
2. 读取同日 `factor_values`，使用 `as_of_date <= signal_date` 且每个 `(stock_code, factor_name)` 取最新可见版本。
3. 应用信号选股层 hard filter：
   - `is_st == 0.0`
   - `is_suspended == 0.0`
   - `is_delisted == 0.0`
   - `low_liquidity == 0.0`
4. hard filter 字段缺失时，保守排除该股票。
5. 排序因子缺失时，排除该股票。
6. 按 `sort_factor` 方向排序，tie 使用 `stock_code` 升序。
7. 选择前 `top_n` 只股票。
8. 目标权重为入选股票等权：`1 / selected_count`。
9. 如果入选数量少于 `top_n`，按实际入选数量等权，不强行补齐。

本 phase 不做多因子加权、不做综合评分、不做行业中性化。

### 成交规则

成交日为 `execution_date`，成交价使用 T+1 开盘价。

规则：

- 目标 notional 基数使用 `execution_date` 前一交易日收盘后的组合 NAV；月末调仓时通常就是 `signal_date` 收盘 NAV。
- 同一 `execution_date` 先卖出、后买入。
- 卖出释放的现金可参与同日买入。
- 本 phase 使用金额簿记，允许小数股；不实现 A 股 100 股整数手约束。
- 买入成交价：`open * (1 + slippage_bps / 10000)`。
- 卖出成交价：`open * (1 - slippage_bps / 10000)`。
- `open` 缺失、非正数或当日无 `daily_prices` 行时，该股票不可交易。
- 撮合层不可交易判断使用 `execution_date` 当日 `daily_prices.is_suspended`，不读取 `factor_values.is_suspended`。
- 涨停不可买：若 `limit_up` 非空且 `open >= limit_up - 1e-6`，买入跳过。
- 跌停不可卖：若 `limit_down` 非空且 `open <= limit_down + 1e-6`，卖出跳过。
- 退市状态使用 `query_securities_as_of(execution_date, include_delisted=True)` 的 `is_delisted_as_of`，不读取 `factor_values.is_delisted`。
- 未成交订单必须写入 `trade_ledger.csv`，并记录 `reject_reason`。
- 被阻止卖出的股票继续持有。
- 被阻止买入的目标仓位保留为现金。

### 成本规则

成本来自 `configs/backtest.yaml`，默认使用 plan 第 17 节口径：

```yaml
costs:
  commission_bps: 2.5
  stamp_tax_bps: 10
  slippage_bps: 5
  min_commission_yuan: 5
```

规则：

- 配置优先级为 `CLI flag > configs/backtest.yaml > 内置默认`。
- 佣金买卖双边收取。
- 印花税仅卖出收取。
- 最低佣金按单笔订单计算。
- 滑点计入成交价，同时 `trade_ledger.csv` 中记录 `slippage_cost`。
- 报告中必须分别输出：
  - `commission`
  - `stamp_tax`
  - `slippage_cost`
  - `total_cost`
  - `gross_return`
  - `net_return`
  - `cost_drag`

### 停牌、涨跌停、退市

信号选股层：

- 使用 `factor_values` 中的 `is_st`、`is_suspended`、`is_delisted`、`low_liquidity` hard filter。
- hard filter 缺失或等于 `1.0` 时排除。

撮合层：

- 使用 `daily_prices.is_suspended` 判断 `execution_date` 当日是否停牌。
- 使用 `daily_prices.limit_up` / `limit_down` 判断涨跌停。
- 使用 `securities` PIT 查询判断 `execution_date` 当日是否已退市。
- 当日缺少 `daily_prices` 行时，按不可交易处理。

退市：

- 不允许买入 `is_delisted_as_of = true` 的股票。
- 如果持仓股票到达 PIT 可见的 `delist_date` 且仍未卖出，按保守规则强制退出。
- 默认退市强制退出价值为 `0.0`。
- 强制退市退出必须写入 `trade_ledger.csv`：
  - `order_status = forced_delist_exit`
  - `executed_price = 0.0`
  - `executed_notional = 0.0`
  - `reject_reason = NULL`
- 退市股票不得从历史样本中静默删除。
- `docs/backtest_assumptions.md` 必须写清退市退出假设。

### 净值与持仓

- 初始资金默认 `1_000_000` 元，可由配置或 CLI 覆盖。
- `--top`、`--initial-cash` 优先级均为 `CLI flag > configs/backtest.yaml > 内置默认`。
- 净值按每日收盘后计算。
- 持仓使用 `daily_prices.close` 估值。
- 若持仓股票当日缺少价格，使用最近一个可见收盘价估值，并记录 warning。
- 本 phase 不实现现金分红、送转、配股等公司行为现金流。

### 基准

由于当前 schema 没有真实指数行情表，本 phase 实现两个合成基准：

1. 市值加权基准。
2. 等权基准。

基准 universe：

- 使用同一个 `index_code` 的 PIT `universe_members`。
- 在每个组合调仓 `signal_date` 确定一次基准成分。
- 两次 `signal_date` 之间使用上一次 `signal_date` 锁定的 PIT universe，按月静态持有。
- 下一个 `signal_date` 才更换基准成分，基准调仓节奏与组合调仓节奏对齐，避免日级刷新成分拉高隐含换手。
- 市值加权优先使用 `valuation_daily.float_mv`，缺失时 fallback 到 `total_mv`。
- 等权基准使用同一 universe 的等权组合。
- 基准默认不扣交易成本。
- 基准收益使用 `adjusted_close = close * adj_factor`。
- `adj_factor` 缺失时按 `close` 计算，并将该股票计入 coverage 的可用分子；报告需说明存在 fallback。
- 基准成分当日 `is_suspended = true` 或缺少 `daily_prices` 行时，当日收益按 `0.0` 处理，并计入 coverage 分母但不计入有效价格收益分子。
- `benchmark_returns.csv` 必须输出 coverage 字段。

### 指标

`metrics.csv` 固定为 wide-format 单行，列名稳定。

至少输出：

```text
total_return
annualized_return
volatility
max_drawdown
sharpe
calmar
win_rate
gross_return
net_return
cost_drag
total_cost
commission
stamp_tax
slippage_cost
average_turnover
max_turnover
benchmark_cap_weight_return
benchmark_equal_weight_return
excess_return_vs_cap_weight
excess_return_vs_equal_weight
tracking_difference_vs_cap_weight
tracking_difference_vs_equal_weight
rebalance_count
trade_count
rejected_order_count
forced_delist_exit_count
```

换手率口径：

```text
gross_turnover = (buy_notional + sell_notional) / nav_before_trade
one_way_turnover = gross_turnover / 2
average_turnover = mean(one_way_turnover)
max_turnover = max(one_way_turnover)
```

## 输出文件

给定 `--output-dir`，至少生成：

```text
backtest_report.md
equity_curve.csv
benchmark_returns.csv
rebalance_summary.csv
target_weights.csv
holdings.csv
trade_ledger.csv
metrics.csv
assumptions.csv
```

### CSV schema

`equity_curve.csv` 固定列：

```text
trade_date
cash
position_value
nav
gross_return
net_return
daily_cost
cumulative_cost
drawdown
```

排序：

```text
ORDER BY trade_date
```

`benchmark_returns.csv` 固定列：

```text
trade_date
cap_weight_return
equal_weight_return
cap_weight_nav
equal_weight_nav
cap_weight_coverage
equal_weight_coverage
cap_weight_member_count
equal_weight_member_count
```

排序：

```text
ORDER BY trade_date
```

`rebalance_summary.csv` 固定列：

```text
signal_date
execution_date
selected_count
target_count
nav_before_trade
buy_notional
sell_notional
gross_turnover
one_way_turnover
commission
stamp_tax
slippage_cost
total_cost
executed_order_count
rejected_order_count
forced_delist_exit_count
warning_count
```

排序：

```text
ORDER BY signal_date, execution_date
```

`target_weights.csv` 固定列：

```text
signal_date
execution_date
stock_code
rank
sort_factor
sort_factor_value
target_weight
target_notional
```

排序：

```text
ORDER BY signal_date, rank, stock_code
```

`holdings.csv` 固定列：

```text
trade_date
stock_code
shares
close
market_value
weight
price_source
```

排序：

```text
ORDER BY trade_date, stock_code
```

`trade_ledger.csv` 固定列：

```text
execution_date
signal_date
stock_code
side
order_status
reject_reason
intended_notional
executed_notional
executed_price
shares_delta
commission
stamp_tax
slippage_cost
total_cost
cash_after
```

排序：

```text
ORDER BY execution_date, stock_code, side, order_status
```

`metrics.csv` 固定为 wide-format 单行，列至少包含本 goal 指标清单。

`assumptions.csv` 固定列：

```text
key
value
```

排序：

```text
ORDER BY key
```

### Markdown 报告

`backtest_report.md` 至少包含：

1. 策略规则。
2. 回测区间。
3. 调仓频率。
4. T+1 开盘成交。
5. 交易成本。
6. 停牌 / 涨跌停 / 退市规则。
7. 两个基准口径。
8. 关键指标摘要。
9. 成本影响。
10. 拒单和强制退市退出摘要。
11. 明确说明：本报告不是交易建议。
12. 明确说明：本报告不包含风格归因和行业归因。
13. 明确说明：本 phase 不做复杂风格归因。

## 接口建议

### 配置

在 `src/ashare/backtest/config.py` 中提供：

```python
def load_backtest_config(config_path: str | Path = "configs/backtest.yaml") -> dict[str, object]:
    ...
```

### 调仓日

在 `src/ashare/backtest/schedule.py` 中提供：

```python
def get_month_end_signal_dates(
    connection: duckdb.DuckDBPyConnection,
    start_date: DateLike,
    end_date: DateLike,
) -> list[date]:
    ...

def get_execution_date(
    connection: duckdb.DuckDBPyConnection,
    signal_date: DateLike,
    end_date: DateLike,
) -> date | None:
    ...
```

### 信号

在 `src/ashare/backtest/signals.py` 中提供：

```python
def build_topn_targets(
    connection: duckdb.DuckDBPyConnection,
    signal_date: DateLike,
    source_run_id: str,
    sort_factor: str,
    index_code: str,
    top_n: int,
    data_dictionary: Mapping[str, object],
) -> pd.DataFrame:
    ...
```

返回字段至少包含：

```text
signal_date
stock_code
target_weight
sort_factor
sort_factor_value
rank
```

### 成本与撮合

在 `src/ashare/backtest/costs.py` 中提供：

```python
def calculate_trade_costs(
    side: str,
    notional: float,
    commission_bps: float,
    stamp_tax_bps: float,
    min_commission_yuan: float,
) -> dict[str, float]:
    ...
```

在 `src/ashare/backtest/broker.py` 中提供：

```python
def execute_rebalance(
    connection: duckdb.DuckDBPyConnection,
    signal_date: DateLike,
    execution_date: DateLike,
    current_positions: pd.DataFrame,
    target_weights: pd.DataFrame,
    cash: float,
    nav_before_trade: float,
    cost_config: Mapping[str, object],
    trading_rules: Mapping[str, object],
) -> tuple[pd.DataFrame, pd.DataFrame, float]:
    ...
```

### 引擎

在 `src/ashare/backtest/engine.py` 中提供：

```python
@dataclass(frozen=True)
class BacktestResult:
    equity_curve: pd.DataFrame
    benchmark_returns: pd.DataFrame
    rebalance_summary: pd.DataFrame
    target_weights: pd.DataFrame
    holdings: pd.DataFrame
    trade_ledger: pd.DataFrame
    metrics: pd.DataFrame
    assumptions: pd.DataFrame
    warnings: tuple[str, ...] = ()

def run_topn_equal_weight_backtest(
    connection: duckdb.DuckDBPyConnection,
    start_date: DateLike,
    end_date: DateLike,
    source_run_id: str,
    sort_factor: str,
    index_code: str,
    top_n: int = 20,
    initial_cash: float = 1_000_000,
    backtest_config: Mapping[str, object] | None = None,
    data_dictionary: Mapping[str, object] | None = None,
) -> BacktestResult:
    ...
```

### 报告

在 `src/ashare/reports/backtest_report.py` 中提供：

```python
def render_backtest_markdown(
    result: BacktestResult,
    metadata: Mapping[str, object],
) -> str:
    ...

def write_backtest_report(
    result: BacktestResult,
    output_dir: str | Path,
    metadata: Mapping[str, object],
    overwrite: bool = False,
) -> dict[str, Path]:
    ...
```

## CLI 要求

修改现有命令：

```text
ashare backtest
```

本 phase 只支持：

```text
--strategy topn-equal
```

建议参数：

```text
--strategy             必填，本 phase 只支持 topn-equal
--db-path              默认 data/processed/ashare.duckdb
--from                 必填，回测起始日期
--to                   必填，回测结束日期
--source-run-id        必填，无默认值
--sort-factor          必填
--index-code           必填，例如 LOCAL_FIXTURE 或 000300.SH
--top                  可选，默认读取 configs/backtest.yaml，fallback 20
--initial-cash         可选，默认读取 configs/backtest.yaml，fallback 1000000
--backtest-config      默认 configs/backtest.yaml
--data-dictionary      默认 configs/data_dictionary.yaml
--output-dir           默认 data/reports/generated/phase1b/backtest
--overwrite            默认 false
```

行为：

- 只读打开 DuckDB。
- 调用 `run_topn_equal_weight_backtest`。
- 写出 Markdown / CSV 报告。
- 成功后打印输出文件路径、核心指标和 warnings。
- 同时打印：
  - `backtest report is for research only and is not a trading instruction.`
  - `回测报告仅供研究复盘，不是交易指令。`
- 不写 DB。
- 不调用 `calculate-factors`、`validate-factors`、`scan` 或 LLM。

## 配置要求

更新 `configs/backtest.yaml`，保持既有结构并补齐 Phase 1b 所需字段：

```yaml
scan:
  frequency: daily

rebalance:
  frequency: monthly
  trigger: month_end
  execution: next_open

portfolio:
  top_n: 20
  weighting: equal_weight
  initial_cash: 1000000

benchmark:
  primary: synthetic_cap_weight
  secondary: synthetic_equal_weight
  rebalance_frequency: monthly
  market_cap_field_priority:
    - float_mv
    - total_mv

trading_rules:
  skip_buy_if_limit_up: true
  block_sell_if_limit_down: true
  hold_if_suspended: true
  delist_exit_value_ratio: 0.0
  price_compare_tolerance: 0.000001

costs:
  commission_bps: 2.5
  stamp_tax_bps: 10
  slippage_bps: 5
  min_commission_yuan: 5
```

更新 `docs/backtest_assumptions.md`：

- 完整重写现有 TODO / 骨架内容。
- 写清本 phase 的回测假设、成本、成交、停牌、涨跌停、退市、基准、净值和不覆盖内容。
- 该文档是人读说明；所有数值口径仍以 `configs/backtest.yaml` 为单一事实源。

## followups 更新

修改 `docs/planning/followups.md`，追加本 phase 新留下的工程债。

现有 `followups.md` 已存在 D26，因此本 phase 不得复用 D26。至少新增：

```text
D27 回测暂不处理公司行为现金流
D28 回测暂不处理 A 股 100 股整数手和零股卖出细节
D29 当前 schema 缺少真实指数行情表，基准为合成基准
D30 回测未实现部分成交、盘口深度和成交量约束
D31 回测暂不做风格归因和行业归因
D32 backtest 不写 research_runs，回测产物仅以文件形式保存
```

每条仍按现有 followups 格式记录：

```markdown
### Dxx. <债标题>

- 现状: ...
- 触发: ...
- 决策: ...
- 关联: ...
```

不得借本 phase 实现 D27-D32。D32 应链接到前置关于正式 run / `research_runs` 的工程债或 plan 中 run 元数据要求。

## 测试要求

新增或更新测试，至少覆盖：

1. 月末调仓日来自 `trading_calendar.is_open = true`。
2. `execution_date` 是 `signal_date` 严格之后的下一个开市交易日。
3. `execution_date > --to` 时跳过该次调仓并记录 warning。
4. 缺少月末信号时跳过该月并记录 warning。
5. 全部月份无信号时 CLI 非 0 退出。
6. 信号读取使用 `as_of_date <= signal_date`，并取最新可见版本。
7. 同一最大 `as_of_date` 下重复 factor key 时 fail-fast。
8. `sort_factor` 为 `higher_is_better` 时降序选 Top N。
9. `sort_factor` 为 `lower_is_better` 时升序选 Top N，必须覆盖 `pe_ttm_percentile`。
10. tied factor value 使用 `stock_code` 稳定排序。
11. hard filter 缺失时保守排除。
12. `is_st`、`is_suspended`、`is_delisted`、`low_liquidity` 为 `1.0` 时在信号选股层排除。
13. T+1 开盘成交使用 `daily_prices.open`。
14. 撮合层停牌判断使用 `daily_prices.is_suspended`，不读取 `factor_values.is_suspended`。
15. 停牌股票不可买入、不可卖出。
16. 涨停不可买，比较时使用容差。
17. 跌停不可卖，比较时使用容差。
18. 卖出先执行，买入后执行。
19. 买入被拒绝时目标仓位保留为现金。
20. 卖出被拒绝时继续持有。
21. 佣金按 bps 计算且受最低佣金约束。
22. 印花税仅卖出收取。
23. 滑点对买入 / 卖出方向正确。
24. `trade_ledger` 同时记录成交和未成交订单。
25. 退市持仓触发 `forced_delist_exit`，并写入 `trade_ledger`。
26. 退市股票不从历史持仓和指标中静默消失。
27. 日度净值曲线按交易日输出且排序确定。
28. 持仓缺少当日价格时使用最近可见收盘价并记录 warning。
29. 市值加权基准优先使用 `float_mv`，缺失时 fallback 到 `total_mv`。
30. 等权基准使用同一 PIT universe。
31. 基准两次调仓之间使用上一次 `signal_date` 锁定的成分。
32. 基准成分停牌或缺价时当日收益按 `0.0` 处理，并影响 coverage。
33. 基准 `adj_factor` 缺失时 fallback 到 close，并在报告说明。
34. `benchmark_returns.csv` 包含本 goal 固定列。
35. 指标包含收益、超额收益、回撤、波动率、换手率和成本。
36. `gross_return` 与 `net_return` 能体现成本拖累。
37. `metrics.csv` 是 wide-format 单行，且包含本 goal 指标清单。
38. 所有输出 CSV 的列集合和排序键符合本 goal。
39. `write_backtest_report` 写出 1 个 Markdown 和 8 个 CSV。
40. `overwrite=False` 时目标文件已存在会 fail-fast。
41. Markdown 报告包含交易假设、成本、基准、退市规则、研究用途说明和“本报告不包含风格归因和行业归因”。
42. `ashare backtest --strategy topn-equal ...` 可以成功运行。
43. `ashare backtest --strategy other ...` 非 0 退出。
44. `ashare backtest` 不写入 DuckDB。
45. 如有必要，最小扩充 fixture 覆盖涨停一字板、跌停、退市、停牌四类边缘样本，但不修改既有 fixture 主样本范围 / 索引。
46. `docs/planning/followups.md` 包含 D27-D32。
47. `ashare --help` 仍能看到前置命令：

```text
ingest
validate-factors
event-study
scan
backtest
report
stock-report
db-init
ingest-local
as-of
calculate-factors
```

测试数据必须通过 fixture builder、`ingest_local` 和 `calculate-factors` 在 `tmp_path` 下构造，不依赖仓库内已有 DuckDB 文件。

## 验收命令

以下命令必须全部成功：

```bash
conda run -n ashare-research-lab python -m pip install -e .
```

```bash
conda run -n ashare-research-lab ashare ingest-local \
  --input-dir tests/fixtures/generated \
  --db-path data/processed/ashare.duckdb
```

```bash
conda run -n ashare-research-lab ashare calculate-factors \
  --from 2026-03-30 \
  --to 2026-06-26 \
  --db-path data/processed/ashare.duckdb \
  --index-code LOCAL_FIXTURE \
  --source-run-id phase1b-backtest
```

```bash
conda run -n ashare-research-lab ashare backtest \
  --strategy topn-equal \
  --from 2026-03-30 \
  --to 2026-06-26 \
  --db-path data/processed/ashare.duckdb \
  --index-code LOCAL_FIXTURE \
  --source-run-id phase1b-backtest \
  --sort-factor return_20d \
  --top 3 \
  --output-dir data/reports/generated/phase1b/backtest \
  --overwrite
```

```bash
conda run -n ashare-research-lab python - <<'PY'
from pathlib import Path
import pandas as pd

out = Path("data/reports/generated/phase1b/backtest")
expected = {
    "backtest_report.md",
    "equity_curve.csv",
    "benchmark_returns.csv",
    "rebalance_summary.csv",
    "target_weights.csv",
    "holdings.csv",
    "trade_ledger.csv",
    "metrics.csv",
    "assumptions.csv",
}
missing = [name for name in expected if not (out / name).exists()]
assert not missing, f"missing backtest files: {missing}"

equity = pd.read_csv(out / "equity_curve.csv")
benchmark = pd.read_csv(out / "benchmark_returns.csv")
rebalance = pd.read_csv(out / "rebalance_summary.csv")
targets = pd.read_csv(out / "target_weights.csv")
holdings = pd.read_csv(out / "holdings.csv")
trades = pd.read_csv(out / "trade_ledger.csv")
metrics = pd.read_csv(out / "metrics.csv")
assumptions = pd.read_csv(out / "assumptions.csv")

assert not equity.empty, "equity_curve should not be empty"
assert not metrics.empty, "metrics should not be empty"
assert len(metrics) == 1, "metrics.csv must be wide-format single row"

expected_equity_cols = {
    "trade_date", "cash", "position_value", "nav", "gross_return",
    "net_return", "daily_cost", "cumulative_cost", "drawdown",
}
assert expected_equity_cols.issubset(equity.columns)

expected_benchmark_cols = {
    "trade_date", "cap_weight_return", "equal_weight_return",
    "cap_weight_nav", "equal_weight_nav", "cap_weight_coverage",
    "equal_weight_coverage", "cap_weight_member_count", "equal_weight_member_count",
}
assert expected_benchmark_cols.issubset(benchmark.columns)

expected_rebalance_cols = {
    "signal_date", "execution_date", "selected_count", "target_count",
    "nav_before_trade", "buy_notional", "sell_notional", "gross_turnover",
    "one_way_turnover", "commission", "stamp_tax", "slippage_cost",
    "total_cost", "executed_order_count", "rejected_order_count",
    "forced_delist_exit_count", "warning_count",
}
assert expected_rebalance_cols.issubset(rebalance.columns)

expected_target_cols = {
    "signal_date", "execution_date", "stock_code", "rank", "sort_factor",
    "sort_factor_value", "target_weight", "target_notional",
}
assert expected_target_cols.issubset(targets.columns)

expected_holding_cols = {
    "trade_date", "stock_code", "shares", "close", "market_value",
    "weight", "price_source",
}
assert expected_holding_cols.issubset(holdings.columns)

expected_trade_cols = {
    "execution_date", "signal_date", "stock_code", "side", "order_status",
    "reject_reason", "intended_notional", "executed_notional", "executed_price",
    "shares_delta", "commission", "stamp_tax", "slippage_cost", "total_cost",
    "cash_after",
}
assert expected_trade_cols.issubset(trades.columns)

expected_metric_cols = {
    "total_return",
    "annualized_return",
    "volatility",
    "max_drawdown",
    "sharpe",
    "calmar",
    "win_rate",
    "gross_return",
    "net_return",
    "cost_drag",
    "total_cost",
    "commission",
    "stamp_tax",
    "slippage_cost",
    "average_turnover",
    "max_turnover",
    "benchmark_cap_weight_return",
    "benchmark_equal_weight_return",
    "excess_return_vs_cap_weight",
    "excess_return_vs_equal_weight",
    "tracking_difference_vs_cap_weight",
    "tracking_difference_vs_equal_weight",
    "rebalance_count",
    "trade_count",
    "rejected_order_count",
    "forced_delist_exit_count",
}
missing_metrics = expected_metric_cols - set(metrics.columns)
assert not missing_metrics, f"missing metric columns: {sorted(missing_metrics)}"

assert {"key", "value"}.issubset(assumptions.columns)

text = (out / "backtest_report.md").read_text(encoding="utf-8")
assert "T+1" in text
assert "开盘" in text
assert "不是交易建议" in text or "not a trading instruction" in text
assert "不包含风格归因" in text
print("OK phase1b backtest artifacts")
PY
```

```bash
conda run -n ashare-research-lab python - <<'PY'
from pathlib import Path

text = Path("docs/planning/followups.md").read_text(encoding="utf-8")
required = [
    "D27",
    "D28",
    "D29",
    "D30",
    "D31",
    "D32",
    "公司行为",
    "100 股",
    "指数行情",
    "部分成交",
    "风格归因",
    "research_runs",
]
missing = [item for item in required if item not in text]
assert not missing, f"followups.md missing: {missing}"
print("OK followups D27-D32")
PY
```

```bash
conda run -n ashare-research-lab pytest -q
```

```bash
conda run -n ashare-research-lab ashare --help
```

## 完成后

1. 运行 `git status`，确认只包含 Phase 1b 相关代码、测试、配置和必要文档改动。
2. 确认未提交：
   - `data/reports/generated/`
   - `data/processed/*.duckdb`
   - `tests/fixtures/generated/`
3. 执行 `git add .`。
4. 执行：

```bash
git commit -m "feat: phase 1b simple portfolio backtest"
```

5. 最终回复说明：
   - 修改了哪些文件。
   - Top N 等权组合如何生成。
   - 月末调仓和 T+1 开盘成交如何实现。
   - 信号选股 hard filter 与撮合层交易约束如何分离。
   - 交易成本、停牌、涨跌停、退市如何处理。
   - 两个基准如何构造。
   - 回测报告输出了哪些 Markdown / CSV。
   - followups 是否追加 D27-D32。
   - 验收命令是否全部通过。
   - commit hash。
   - 是否发现 plan 或前置 phase 的缺口。

## 不要实现

- 不实现新因子。
- 不重新计算 Phase 1a 因子。
- 不重新实现单因子验证。
- 不实现事件研究。
- 不实现综合评分。
- 不实现多因子加权。
- 不实现 0-100 标准化。
- 不实现行业中性组合。
- 不实现复杂风格归因。
- 不实现行业归因。
- 不实现真实指数行情接入。
- 不实现公司行为现金流。
- 不实现 A 股 100 股整数手约束。
- 不实现部分成交、盘口深度、成交量约束或冲击成本模型。
- 不实现融资融券、做空、多空组合或杠杆。
- 不实现参数寻优、网格搜索或 walk-forward 优化。
- 不写入 `research_runs`。
- 不新增 DuckDB 表。
- 不修改 schema。
- 不调用 AkShare。
- 不调用 LLM。
- 不实现服务化 API。
- 不把回测报告描述为买入、卖出或交易指令。

## 发现的缺口

- 当前 schema 没有真实指数行情表，因此本 phase 只能实现同一 PIT universe 下的合成市值加权 / 等权基准，不能输出真实沪深 300 指数收益。
- 当前 plan 要求交易撮合使用未复权价格，但尚未定义公司行为现金流处理。本 phase 保守地不实现分红、送转、配股现金流，并在 followups 登记。
- 当前前置 phase 的候选清单是单日报告产物，不适合作为历史月度回测的主输入。本 phase 直接基于 `factor_values` 的历史信号构造 Top N，候选报告逻辑只作为口径参考。
- `factor_values` 没有唯一键；本 phase 不改 schema，回测读取时对同一最大 `as_of_date` 下的重复 key fail-fast，并链接前置 D2 工程债。
- Phase 1a-7 已有 D26 编号，本 phase 新增 followups 从 D27 开始，避免 D 编号语义冲突。
- 本 phase 不写 `research_runs`，与 plan 中正式运行审计要求仍有差距；本 phase 只输出文件产物，并在 D32 登记后续补齐方向。
