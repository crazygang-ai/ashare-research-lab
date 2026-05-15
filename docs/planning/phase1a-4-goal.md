# Phase 1a-4 Goal: 基础因子计算

请在已完成 Phase 1a-3.5 的 `/Users/crazy/own_project/ashare-research-lab` 仓库中继续实现 Phase 1a-4：基础因子计算。

本 phase 只做最小基础因子计算与 `factor_values` 落库，不做因子验证、报告、scan、组合回测或 LLM。

## 目标

1. 基于 Phase 1a-3 / 1a-3.5 的 Point-in-Time as-of 查询层计算基础因子。
2. 实现并落库以下 11 个因子 / 硬过滤字段：
   - `return_20d`
   - `return_60d`
   - `above_ma60`
   - `low_liquidity`
   - `is_st`
   - `is_suspended`
   - `is_delisted`
   - `pe_ttm_percentile`
   - `pb_percentile`
   - `revenue_yoy`
   - `profit_yoy`
3. 写入 DuckDB `factor_values` 表。
4. 增加 `ashare calculate-factors` CLI 命令。
5. 更新因子配置和数据字典，让本 phase 实现的每个因子都有明确口径。
6. 增加测试，覆盖公式正确性、PIT 不泄漏、落库幂等性和 CLI 可运行性。

## 工作约束

- 严格遵守 `docs/planning/a-share-research-plan.md`。
- 所有 Python 命令必须在 Conda 环境 `ashare-research-lab` 中执行。
- 因子计算必须显式传入 `as_of_date`，不能默认使用当前日期。
- 单日模式下，`as_of_date` 必须是 `trading_calendar.is_open = true` 的交易日。
- 区间模式下，`--from` / `--to` 端点允许是非交易日；内部只计算区间内 `is_open = true` 的交易日。
- 默认 `trade_date == as_of_date`。
- 所有原始输入数据必须通过 Phase 1a-3.5 的 as-of 查询语义获取，不能绕过 PIT 规则读取未来可见数据。
- 本 phase 允许写入 `factor_values`，不写入 `research_runs`。
- 本 phase 不实现正式 run 管理、快照系统、报告生成或验证统计。
- 本 phase 不接真实 AkShare 数据，不调用 LLM。
- 本 phase 完成后单独 commit。
- 提交信息为：`feat: phase 1a-4 basic factor calculation`

## Universe 选择规则

`calculate_factors_for_date` 必须先确定本次计算的股票集合。该集合是所有因子和硬过滤字段的计算边界。

规则：

- 如果传入 `index_code`：
  - 基础 universe = `query_universe_members_as_of(index_code=...)` 返回的 `stock_code` 集合。
  - 再用 `query_securities_as_of(include_delisted=True)` 获取证券状态。
  - 默认 `include_delisted=False` 时，从 universe 中剔除 `is_delisted_as_of = true` 的股票。
  - `include_delisted=True` 时，不因为退市状态额外剔除股票，但不会复活已经不属于该指数当前 as-of 成分的股票。
- 如果 `index_code is None`：
  - 基础 universe = `query_securities_as_of(include_delisted=include_delisted)` 返回的 `stock_code` 集合。
  - `include_delisted=False` 时不包含已退市股票。
  - `include_delisted=True` 时包含已退市股票，并可写出 `is_delisted = 1.0`。
- 空 universe 是合法结果：
  - 计算函数返回 0 行。
  - CLI 退出码为 0。
  - CLI 输出中明确显示写入 0 行。

硬过滤字段写入范围：

- `is_st`、`is_suspended`、`is_delisted` 对最终 universe 中每只股票都强制写入一行 `0.0` 或 `1.0`，便于后续硬过滤直接 join。
- 不允许下游把缺失的硬过滤字段默认解释为 `0.0`。
- `is_suspended` 的 MVP 保守口径：
  - 当 `as_of_date` 当天有 `daily_prices` 行时，使用该行 `is_suspended`。
  - 当 universe 中股票缺少 `as_of_date` 当天 `daily_prices` 行时，写 `1.0`，视为不可交易 / 数据不足的保守硬过滤。

## 配置结构

更新 `configs/factors.yaml` 时必须使用以下结构，避免参数散落或测试无法稳定读取：

```yaml
factors:
  return_20d:
    direction: higher_is_better
    group: momentum
    hard_filter: false
    soft_penalty: false
    params:
      window_days: 20

  return_60d:
    direction: higher_is_better
    group: momentum
    hard_filter: false
    soft_penalty: false
    params:
      window_days: 60

  above_ma60:
    direction: higher_is_better
    group: momentum
    hard_filter: false
    soft_penalty: false
    params:
      window_days: 60

  pe_ttm_percentile:
    direction: lower_is_better
    group: valuation
    hard_filter: false
    soft_penalty: false
    params:
      window_days: 252
      min_observations: 20

  pb_percentile:
    direction: lower_is_better
    group: valuation
    hard_filter: false
    soft_penalty: false
    params:
      window_days: 252
      min_observations: 20

  revenue_yoy:
    direction: higher_is_better
    group: financial
    hard_filter: false
    soft_penalty: false
    params: {}

  profit_yoy:
    direction: higher_is_better
    group: financial
    hard_filter: false
    soft_penalty: false
    params: {}

hard_filters:
  is_st:
    enabled: true
    params: {}

  is_suspended:
    enabled: true
    params: {}

  is_delisted:
    enabled: true
    params: {}

  low_liquidity:
    enabled: true
    params:
      window_days: 20
      min_avg_amount: 50000000
```

配置加载建议：

- CLI 增加 `--factor-config`，默认 `configs/factors.yaml`。
- 计算函数允许直接传入已解析的配置对象，便于测试注入自定义阈值。
- 测试必须覆盖自定义 `low_liquidity.params.min_avg_amount` 和估值 `min_observations`。

## 因子口径

所有写入 `factor_values.factor_value` 的值使用 `DOUBLE`。布尔 / 硬过滤字段统一写为：

```text
true  -> 1.0
false -> 0.0
```

缺失或无法可靠计算的连续因子不写入 `factor_values`。测试中的中间计算 DataFrame 可以保留 `NaN`，但落库层跳过 `NaN`。

### 观测窗口语义

`20d` / `60d` 的窗口按单股票 `daily_prices` 中已经 PIT 可见的价格观测行计算，不直接按 `trading_calendar` 取日期。

规则：

- 对每只股票，将 `daily_prices` 按 `trade_date` 升序排序。
- `return_20d` 使用当前观测行向前 `20` 行的价格，即 `shift(20)`。
- `return_60d` 使用当前观测行向前 `60` 行的价格，即 `shift(60)`。
- 停牌日如果存在 `daily_prices` 行，仍算一个观测。
- 缺少 `daily_prices` 行的日期不算价格观测。
- `above_ma60` 使用当前观测行及之前共 `60` 个有效价格观测的均值。

### `return_20d`

- 类型：动量因子。
- 来源：`daily_prices` as-of 可见行情。
- 价格口径：后复权近似价 `adjusted_close = close * adj_factor`；如果 `adj_factor` 为空，使用 `close`。
- 公式：

```text
adjusted_close_t / adjusted_close_t_shift_20 - 1
```

- 要求至少存在当前观测和向前 20 行的同股票价格。
- 不使用 `as_of_date` 之后的价格或复权因子。

### `return_60d`

- 类型：动量因子。
- 来源和价格口径同 `return_20d`。
- 公式：

```text
adjusted_close_t / adjusted_close_t_shift_60 - 1
```

- 要求至少存在当前观测和向前 60 行的同股票价格。

### `above_ma60`

- 类型：动量因子。
- 来源：`daily_prices` as-of 可见行情。
- 公式：

```text
1.0 if adjusted_close_t > mean(adjusted_close over latest 60 observations including t)
0.0 otherwise
```

- 少于 60 个有效价格观测时不写入。

### `low_liquidity`

- 类型：硬过滤字段。
- 来源：`daily_prices.amount`。
- 参数从 `hard_filters.low_liquidity.params` 读取：

```text
window_days = 20
min_avg_amount = 50_000_000
```

- 公式：

```text
avg(amount over latest 20 observations including t) < min_avg_amount
```

- 观测不足 20 个交易日时不写入。

### `is_st`

- 类型：硬过滤字段。
- 来源：`st_status` as-of 查询结果。
- `as_of_date` 当天存在 PIT 可见且有效的 ST 区间时写 `1.0`，否则写 `0.0`。
- 必须遵守 Phase 1a-3.5 的 `in_effective_date` / `out_effective_date` 可见性规则。

### `is_suspended`

- 类型：硬过滤字段。
- 来源：`daily_prices.is_suspended`。
- 对最终 universe 中每只股票强制写入：
  - 当日 `daily_prices.is_suspended = true` 写 `1.0`
  - 当日 `daily_prices.is_suspended = false` 写 `0.0`
  - 当日缺少 `daily_prices` 行写 `1.0`，作为 MVP 保守不可交易过滤
- `is_suspended = 1.0` 在 MVP 下含义为不可交易，覆盖两种场景：(a) 当日 `daily_prices.is_suspended = true` 真实停牌；(b) `as_of_date` 当天 universe 内股票缺失 `daily_prices` 行，按保守策略视为不可交易。这一二义性必须在 `configs/data_dictionary.yaml` 中 `is_suspended` 的 description 字段显式说明。后续 phase 如需区分，应引入独立的 `data_missing` 字段，不在本 phase 实现。

### `is_delisted`

- 类型：硬过滤字段。
- 来源：`securities` as-of 查询结果。
- 使用 `query_securities_as_of(include_delisted=True)` 获取状态。
- `is_delisted_as_of = true` 写 `1.0`，否则写 `0.0`。
- 必须遵守 Phase 1a-3.5 的 `delist_effective_date` 可见性规则。

### `pe_ttm_percentile`

- 类型：估值因子。
- 来源：`valuation_daily.pe_ttm`。
- 口径：单股票历史滚动分位数，不做横截面标准化。
- 参数从 `factors.pe_ttm_percentile.params` 读取：

```text
window_days = 252
min_observations = 20
```

- `pe_ttm <= 0` 或有效观测不足 `min_observations` 时不写入。
- 当前值在滚动窗口内的分位计算规则：
  - 窗口内有效观测按数值升序排名。
  - 同值使用 average rank。
  - `percentile = (average_rank_1_based - 1) / (n - 1)`。
  - `n == 1` 时不写入。
- 输出范围：`0.0` 到 `1.0`。
- 数值越低表示估值越低。

### `pb_percentile`

- 类型：估值因子。
- 来源：`valuation_daily.pb`。
- 口径同 `pe_ttm_percentile`。
- 参数从 `factors.pb_percentile.params` 读取。
- `pb <= 0` 或有效观测不足 `min_observations` 时不写入。
- 数值越低表示估值越低。

### `revenue_yoy`

- 类型：财务因子。
- 来源：`fundamental_reports` as-of 可见财报。
- 本 phase 假定 `fundamental_reports.revenue` 在同一 `report_period` 类型内可直接同比，由 ingest 层保证累计口径一致。
- 对每只股票，先在 as-of 可见财报中按 `(stock_code, report_period)` 去重：
  - 同一 `(stock_code, report_period)` 多条可见记录时，选择 `publish_time` 最新的一条。
  - 该规则只作用于因子计算阶段，不下放到 PIT 查询层，不改变 Phase 1a-3.5 “PIT 查询层不实现 latest-revision-wins” 的约定。
- 当前期取截至 `as_of_date` 可见的最新 `report_period`。
- 同期基准取 `report_period` 往前一年、月日相同的报告，要求 `(year - 1, month, day)` 严格相等，不做向最近季度末或最近披露日的回退。如果不存在严格匹配的同期 `report_period`，视为同期基准缺失，不写入。
- 公式：

```text
current_revenue / previous_year_same_period_revenue - 1
```

- `previous_year_same_period_revenue <= 0` 或缺失时不写入。

### `profit_yoy`

- 类型：财务因子。
- 来源：`fundamental_reports.net_profit`。
- 本 phase 假定 `fundamental_reports.net_profit` 在同一 `report_period` 类型内可直接同比，由 ingest 层保证累计口径一致。
- 当前期和同期基准选择规则同 `revenue_yoy`。
- MVP 公式：

```text
current_net_profit / previous_year_same_period_net_profit - 1
```

- `previous_year_same_period_net_profit <= 0` 或缺失时不写入，避免负基数导致误导性增长率。

## 文件变更

建议新增或修改：

```text
src/ashare/factors/__init__.py
src/ashare/factors/config.py
src/ashare/factors/calculator.py
src/ashare/factors/momentum.py
src/ashare/factors/valuation.py
src/ashare/factors/financial.py
src/ashare/factors/risk.py
src/ashare/factors/store.py
src/ashare/cli.py
configs/factors.yaml
configs/data_dictionary.yaml
docs/data_dictionary.md
src/ashare/fixtures/builder.py
tests/test_factors.py
tests/test_factor_cli.py
tests/test_fixtures.py
```

说明：

- `config.py` 负责读取和校验 `configs/factors.yaml` 中本 phase 需要的参数。
- `calculator.py` 负责调度单日 / 区间因子计算。
- `store.py` 只负责 `factor_values` 幂等写入。
- `momentum.py`、`valuation.py`、`financial.py`、`risk.py` 分别实现对应因子纯计算逻辑。
- `cli.py` 只新增 `calculate-factors`，不实现 `scan`、`validate-factors` 真实逻辑。
- `configs/factors.yaml` 增加本 phase 11 个因子的方向、分组、缺失值、窗口和阈值。
- `configs/data_dictionary.yaml` 增加本 phase 11 个因子的机器可读定义。
- `docs/data_dictionary.md` 如已有生成脚本支持，应从 YAML 生成，不手写维护。
- `src/ashare/fixtures/builder.py` 只允许补充因子测试所需的最小 fixture 数据，不得改变前置 phase 的 PIT 语义。
- 不需要修改 `schema.sql`，除非发现 `factor_values` 缺少 plan 已定义的必要列。

## 接口建议

在 `src/ashare/factors/config.py` 中提供：

```python
def load_factor_config(config_path: str | Path = "configs/factors.yaml") -> dict[str, object]:
    ...
```

在 `src/ashare/factors/calculator.py` 中提供：

```python
SUPPORTED_FACTORS: tuple[str, ...]

def calculate_factors_for_date(
    connection: duckdb.DuckDBPyConnection,
    as_of_date: DateLike,
    index_code: str | None = None,
    factor_names: Sequence[str] | None = None,
    include_delisted: bool = False,
    factor_config: Mapping[str, object] | None = None,
) -> pd.DataFrame:
    ...
```

返回 DataFrame 至少包含：

```text
stock_code
trade_date
factor_name
factor_value
as_of_date
```

规则：

- `factor_names is None` 时计算本 phase 全部支持因子。
- `factor_names` 非空时只计算指定因子；未知因子必须报错。
- 单日 `as_of_date` 不是交易日时抛出 `ValueError`。

在 `src/ashare/factors/store.py` 中提供：

```python
def write_factor_values(
    connection: duckdb.DuckDBPyConnection,
    factors: pd.DataFrame,
    source_run_id: str,
    replace: bool = True,
) -> int:
    ...
```

落库规则：

- `replace=True` 时，只删除待写入 DataFrame 中涉及的这些键：

```text
source_run_id
as_of_date
trade_date
factor_name
```

- `replace=True` 不删除同一 `source_run_id` 下其他未本次计算的 `factor_name`。
- 例如先用同一 `source_run_id` 全量跑，再用 `--factor return_20d` 局部 replace，其他 10 个因子的旧记录应保留。
- 重复运行同一命令不得产生重复行。
- 不新增唯一索引或复杂 upsert。
- `source_run_id` 由 CLI 参数传入，默认 `phase1a4`。

## CLI 要求

新增命令：

```text
ashare calculate-factors
```

建议参数：

```text
--db-path              默认 data/processed/ashare.duckdb
--as-of               单日计算，ISO 日期
--from                区间起始日期，ISO 日期
--to                  区间结束日期，ISO 日期
--index-code          可选，例如 LOCAL_FIXTURE
--factor              可重复传入；不传则计算本 phase 全部支持因子
--factor-config       默认 configs/factors.yaml
--source-run-id       默认 phase1a4
--include-delisted    默认 false
--replace / --append  默认 replace
```

规则：

- `--as-of` 和 `--from/--to` 二选一，且必须显式选择其中一种：
  - 同时传入 `--as-of` 与 `--from` 或 `--to`，CLI 报错并以非 0 退出，错误信息说明二者互斥。
  - 两者都不传，CLI 报错并以非 0 退出，错误信息说明必须选择单日或区间模式。
  - 只传 `--from` 或只传 `--to`，CLI 报错并以非 0 退出，错误信息说明区间模式必须成对传入。
- 单日模式下，`--as-of` 不是交易日时 CLI 报错并以非 0 退出，错误信息必须说明该日期不是交易日。
- 区间模式下，`--from` / `--to` 可以是非交易日，内部按 `trading_calendar.is_open = true` 过滤。
- 区间模式下，如果区间内没有交易日，CLI 退出码为 0，写入 0 行。
- 成功后打印：
  - 数据库路径
  - 日期范围或单日
  - `source_run_id`
  - universe 股票数量（最终参与因子计算的股票数，即应用 `index_code` / `include_delisted` 规则之后的集合大小；区间模式下按每个交易日分别打印，或打印区间内出现过的并集大小，由实现选择一种并在 `--help` 或 README 中说明口径）
  - 写入总行数
  - 本 phase 每个支持 `factor_name` 的写入行数，包含 0 行的因子
- 不生成 Markdown / CSV 报告。
- 不写入 `research_runs`。
- 不调用 `validate-factors`、`scan` 或回测逻辑。

## Fixture 更新要求

如果现有 fixture 不足以测试本 phase 因子，必须最小更新。

要求：

1. 保持交易日起点为 `2026-01-05`，避免破坏前置 phase 关于 fixture 起点的测试语义。
2. 将主样本交易日从 60 个扩展到至少 125 个，并继续保留至少 3 个尾部 buffer 交易日。
3. `2026-06-26` 附近必须有足够价格和估值历史，使 `return_60d`、`above_ma60`、`pe_ttm_percentile`、`pb_percentile` 可以写出非空结果。
4. 保留 Phase 1a-3.5 的 ST、退市、行业切换、停牌、涨跌停边界；现有基于 `main_days[12]`、`main_days[30]`、`main_days[44]` 等索引的 PIT 边界不要改义。
5. 为至少 3 只股票补充同一报告期和上一年同期的 `fundamental_reports`，用于测试 `revenue_yoy` 和 `profit_yoy`。
6. 至少包含一个 `previous_year_same_period_revenue <= 0` 或缺失场景，验证不写入无效同比。
7. 至少包含一个 `previous_year_same_period_net_profit <= 0` 或缺失场景，验证不写入无效利润同比。
8. 至少给 1 只股票设置非恒定 `adj_factor`，例如某个 day_index 后变为 `1.05`，确保测试能识别 `return_20d` 使用了 `close * adj_factor` 而不是 raw `close`。
9. 同期基准财报（上一年 `report_period`）允许使用早于 `main_days[0]` 的 `publish_time`，例如 `datetime(2025, 4, 30, 18, 0)`，由 `ingest_local` 通过 `calculate_effective_date(publish_time, trading_days)` 推算 `effective_date`。同期基准报告不要求出现在 `trading_calendar` 中，也不要求 `daily_prices` 覆盖该日期。fixture builder 在写入这类记录时，必须保证 `publish_time` 早于 `as_of_date` 才能被 `query_fundamental_reports_as_of` 视为可见。
10. 扩展 fixture 长度时，必须同步更新 Phase 1a-2 / 1a-3 / 1a-3.5 中依赖 fixture 行数或末日日期的测试断言。受影响的断言要么使用 fixture 暴露的常量（例如 `MAIN_SAMPLE_DAYS`、`main_days[-1]`），要么使用相对偏移而非硬编码日期。Phase 1a-3.5 已建立的 `main_days[12]` / `[30]` / `[31]` / `[32]` / `[40]` / `[41]` / `[44]` PIT 边界不得改义。
11. 不新增真实数据源，不改变 schema 语义。

## 测试要求

新增或更新测试，至少覆盖：

1. `calculate_factors_for_date` 可以基于 fixture DuckDB 返回本 phase 支持的 11 个因子。
2. `index_code` 给定时使用 PIT universe 成分作为股票集合。
3. `index_code is None` 时使用 PIT securities 作为股票集合。
4. `include_delisted=False` 默认剔除已退市股票。
5. `index_code is None and include_delisted=True` 时可以计算出 `is_delisted = 1.0`。
6. 空 universe 返回 0 行且 CLI 成功退出。
7. `return_20d` 使用 `close * adj_factor` 和向前 20 行价格观测计算，结果与测试手算一致。
8. `return_60d` 在观测不足时不写入，在样本后段观测充足时写入。
9. `above_ma60` 使用最近 60 个有效价格观测，结果与测试手算一致。
10. 停牌日如果存在 `daily_prices` 行，动量窗口把它计为一个观测。
11. `low_liquidity` 使用配置阈值和最近 20 行成交额均值。
12. 测试可注入自定义 `low_liquidity.params.min_avg_amount` 覆盖默认配置。
13. `is_st` 覆盖 ST 生效前、生效日、摘帽日前、摘帽日后的结果。
14. `is_suspended` 覆盖 fixture 中停牌日，并覆盖缺少当日价格行时的保守 `1.0` 行为。
15. `is_delisted` 覆盖退市公告前、公告后但退市日前、退市日当天。
16. `is_st`、`is_suspended`、`is_delisted` 对 universe 中每只股票都写出 `0.0` 或 `1.0`。
17. `pe_ttm_percentile` 不使用 `as_of_date` 之后的估值数据。
18. `pb_percentile` 不使用 `as_of_date` 之后的估值数据。
19. `pe_ttm_percentile` / `pb_percentile` 的 average-rank percentile 计算与测试手算一致。
20. 测试可注入自定义估值 `min_observations`。
21. `revenue_yoy` 只使用 `effective_date <= as_of_date` 的财报。
22. `profit_yoy` 只使用 `effective_date <= as_of_date` 的财报。
23. 财务因子同一 `(stock_code, report_period)` 多条可见记录时选择 `publish_time` 最新记录。
24. 财务修订选择逻辑只在因子层实现，不修改 PIT 查询层行为。
25. 负值或零值历史基数按本 goal 规则不写入。
26. 单日模式传入非交易日时 CLI 非 0 退出。
27. 区间模式端点为非交易日时，内部只计算区间内开市日。
28. `write_factor_values(..., replace=True)` 重复运行不产生重复行。
29. 局部 replace 只替换本次涉及的 `factor_name`，不删除同一 `source_run_id` 下其他因子。
30. `--factor return_20d --factor is_st` 只计算并写入指定因子。
31. CLI 输出每个本 phase 支持因子的写入行数，包含 0 行因子。
32. `ashare calculate-factors --as-of ...` 可以成功运行。
33. `ashare calculate-factors --from ... --to ...` 可以成功运行。
34. `ashare --help` 可以看到 `calculate-factors`，同时前置命令仍存在：

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
```

测试数据必须通过 fixture builder 和 `ingest_local` 在 `tmp_path` 下构造，不依赖仓库内已有 DuckDB 文件。

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
  --as-of 2026-06-26 \
  --db-path data/processed/ashare.duckdb \
  --index-code LOCAL_FIXTURE \
  --source-run-id phase1a4-smoke
```

```bash
conda run -n ashare-research-lab ashare calculate-factors \
  --as-of 2026-03-06 \
  --db-path data/processed/ashare.duckdb \
  --include-delisted \
  --source-run-id phase1a4-delisted
```

```bash
conda run -n ashare-research-lab ashare calculate-factors \
  --from 2026-06-01 \
  --to 2026-06-26 \
  --db-path data/processed/ashare.duckdb \
  --index-code LOCAL_FIXTURE \
  --source-run-id phase1a4-range
```

```bash
conda run -n ashare-research-lab python - <<'PY'
import duckdb

expected = {
    "return_20d",
    "return_60d",
    "above_ma60",
    "low_liquidity",
    "is_st",
    "is_suspended",
    "is_delisted",
    "pe_ttm_percentile",
    "pb_percentile",
    "revenue_yoy",
    "profit_yoy",
}

con = duckdb.connect("data/processed/ashare.duckdb", read_only=True)
names = {
    row[0]
    for row in con.execute(
        """
        SELECT DISTINCT factor_name
        FROM factor_values
        WHERE source_run_id IN (
            'phase1a4-smoke',
            'phase1a4-delisted',
            'phase1a4-range'
        )
        """
    ).fetchall()
}
missing = expected - names
assert not missing, f"missing factors: {sorted(missing)}"

delisted_rows = con.execute(
    """
    SELECT COUNT(*)
    FROM factor_values
    WHERE source_run_id = 'phase1a4-delisted'
      AND factor_name = 'is_delisted'
      AND factor_value = 1.0
    """
).fetchone()[0]
assert delisted_rows > 0, "expected at least one is_delisted = 1.0 row"

print(con.execute(
    """
    SELECT factor_name, COUNT(*)
    FROM factor_values
    WHERE source_run_id IN (
        'phase1a4-smoke',
        'phase1a4-delisted',
        'phase1a4-range'
    )
    GROUP BY factor_name
    ORDER BY factor_name
    """
).fetchall())
con.close()
PY
```

```bash
conda run -n ashare-research-lab pytest -q
```

```bash
conda run -n ashare-research-lab ashare --help
```

## 完成后

1. 运行 `git status`，确认只包含 Phase 1a-4 相关改动。
2. 执行 `git add .`。
3. 执行：

```bash
git commit -m "feat: phase 1a-4 basic factor calculation"
```

4. 最终回复说明：
   - 修改了哪些文件。
   - 实现了哪些因子。
   - 每类因子如何保证 PIT 不泄漏。
   - `factor_values` 写入和幂等规则。
   - 验收命令是否全部通过。
   - commit hash。
   - 是否发现 plan 或前置 phase 的缺口。

## 不要实现

- 不做 IC、Rank IC、分组收益、ICIR 或衰减曲线。
- 不实现 `validate-factors` 真实逻辑。
- 不生成因子验证报告。
- 不生成 Markdown / CSV 研究报告。
- 不实现 `scan` 真实逻辑。
- 不实现候选股票排序。
- 不实现综合打分。
- 不实现因子标准化到 0-100。
- 不做行业中性化。
- 不做组合回测。
- 不实现事件研究。
- 不写入 `research_runs`。
- 不实现正式 run / snapshot 管理。
- 不接真实 AkShare 数据。
- 不调用 LLM。
- 不实现服务化 API。
- 不新增复杂 schema migration framework。
- 不实现风险软扣分因子，例如 `pledge_ratio`、`inquiry_letter_count`、`recent_big_shareholder_reduce`。

## 发现的缺口

- Plan 中没有明确 `low_liquidity` 的最小成交额阈值和窗口。本 phase 固定为配置项，默认 `20` 日均成交额低于 `50_000_000`。
- Plan 中没有明确 `pe_ttm_percentile` / `pb_percentile` 是横截面分位还是个股历史分位。本 phase 使用单股票历史滚动分位，后续标准化阶段再做横截面排名。
- Plan 中没有明确 `return_20d` / `return_60d` 的 “20 / 60 个交易日前” 是交易日历偏移还是个股价格观测偏移。本 phase 使用单股票 `daily_prices` 观测行偏移。
- `factor_values` schema 未定义唯一键。本 phase 用 delete-before-insert 保证重复运行不膨胀，不在本 phase 增加约束。
- 前置 phase 可能只有数据字典骨架。本 phase 需要补齐本次实现的 11 个因子定义，但不扩大到未实现因子。
