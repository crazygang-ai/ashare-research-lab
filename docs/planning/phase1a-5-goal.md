# Phase 1a-5 Goal: 单因子验证

请在已完成 Phase 1a-4.5 的 `/Users/crazy/own_project/ashare-research-lab` 仓库中继续实现 Phase 1a-5：单因子验证。

本 phase 只基于已落库的 `factor_values` 和未来收益标签做验证统计，不计算新因子，不生成报告，不做 `scan`，不做组合回测。

## 目标

1. 基于 `factor_values` 构造单因子验证输入。
2. 基于 `daily_prices` 和 `trading_calendar` 构造未来收益标签。
3. 实现以下单因子验证指标：
   - 覆盖率
   - 缺失率
   - Rank IC
   - ICIR
   - Top / Bottom 分组收益
   - 衰减曲线
4. 将现有 `ashare validate-factors` CLI 从空壳改为真实验证命令。
5. 增加测试，覆盖标签构造、覆盖率、Rank IC、ICIR、分组收益、衰减曲线和 CLI。
6. 不写入新的结果表，不生成 Markdown / CSV 报告。

## 工作约束

- 严格遵守 `docs/planning/a-share-research-plan.md`。
- 所有 Python 命令必须在 Conda 环境 `ashare-research-lab` 中执行。
- 本 phase 不计算因子，只读取 Phase 1a-4 已写入的 `factor_values`。
- 本 phase 不写入 `factor_values`。
- 本 phase 不写入 `research_runs`。
- 本 phase 不新增 DuckDB 表，不修改 schema。
- 本 phase 不修改 PIT 查询层、不修改 ingest、不修改 factor calculator。
- `validate-factors` 默认以只读方式打开 DuckDB。
- 验证日期区间必须显式传入，不能默认使用当前日期。
- `source_run_id` 必须显式传入，CLI 不设置默认值，避免误读旧 run。
- 多空收益只作为单因子分析口径，用于衡量因子区分度，不代表可执行策略。
- 不实现报告渲染、不实现 `scan`、不实现组合回测、不实现事件研究。
- 不调用 AkShare，不调用 LLM。
- Phase 1a-5 完成后单独 commit。
- 提交信息为：`feat: phase 1a-5 single factor validation`

## 验证口径

### 输入数据

验证输入来自：

```text
factor_values
daily_prices
trading_calendar
configs/validation.yaml
configs/data_dictionary.yaml
```

`factor_values` 使用字段：

```text
stock_code
trade_date
factor_name
factor_value
as_of_date
source_run_id
```

规则：

- `trade_date` 是信号日期。
- 默认只使用 `as_of_date == trade_date` 的记录。
- 先过滤 `source_run_id`、日期区间、`factor_names` 和 `as_of_date == trade_date`。
- 在过滤后的子集内，如果同一 `(source_run_id, stock_code, trade_date, factor_name)` 出现 2 行或更多，必须 fail-fast。
- 重复键错误信息必须打印至多 5 个重复样例，方便定位问题。
- 不从原始行情、财务、估值表重新计算任何因子。

### signal_dates 来源

验证信号日期以 `factor_values` 实际存在的 `trade_date` 为准：

```text
signal_dates = DISTINCT factor_values.trade_date
WHERE source_run_id = ?
  AND trade_date BETWEEN from AND to
  AND factor_name IN selected_factor_names_or_default_set
  AND as_of_date = trade_date
```

规则：

- 不使用 `trading_calendar` 生成一批空信号日。
- `trading_calendar` 只服务于未来收益标签中 `t+h` 的“第 h 个后续开市交易日”语义。
- 如果日期区间内没有任何匹配的 `factor_values` 行，CLI 以非 0 退出并说明没有可验证的因子输入。

### 覆盖率和缺失率

由于连续因子缺失时不会写入 `factor_values`，覆盖率分母按以下规则确定。

优先使用同一 `source_run_id`、同一 `trade_date` 下 hard filter 因子行推断 universe：

```text
universe_factor_names:
  - is_st
  - is_suspended
  - is_delisted
  - low_liquidity
```

明确口径：

```text
universe(d) =
  UNION {
    stock_code |
    source_run_id = ?
    AND trade_date = d
    AND as_of_date = trade_date
    AND factor_name IN universe_factor_names
  }
```

规则：

- 使用并集，不使用交集。
- `low_liquidity` 可能因观测不足不写入，不能要求 4 个 hard filter 集合完全一致。
- 如果某日 hard filter 行全部不存在，fallback 到该日期 `factor_values` 中全部 `stock_code` 的去重并集。
- fallback 场景下 CLI 必须打印提示，说明覆盖率是基于可见 `factor_values` 行推断，可能高估覆盖率。

每个 `(factor_name, trade_date)` 输出：

```text
universe_count
valid_factor_count
missing_count
coverage
missing_rate
universe_source
```

公式：

```text
coverage = valid_factor_count / universe_count
missing_rate = 1 - coverage
```

其中 `universe_source` 至少取：

```text
hard_filters
factor_values_fallback
```

### 未来收益标签

未来收益标签只用于事后验证，不代表交易执行价格。

默认口径：

```text
forward_return_h = adjusted_close_{t+h} / adjusted_close_t - 1
adjusted_close = close * adj_factor
adj_factor 为空时 fallback 到 close
```

规则：

- `t` 是 `factor_values.trade_date`。
- `t+h` 使用 `trading_calendar.is_open = true` 的第 `h` 个后续交易日。
- horizon 必须严格向后，`h=1` 表示下一开市交易日。
- 如果 `t` 或 `t+h` 缺少对应股票价格，则该股票该 horizon 标签缺失。
- 标签构造可以读取未来价格，因为它是验证标签；但不能把未来价格写回因子或 PIT 查询层。
- 默认 horizons 来自 `configs/validation.yaml`，建议为 `[5, 20, 60]`。
- CLI 支持 `--horizon 5,20,60` 覆盖默认值。
- 本 phase 不在 label 阶段剔除停牌、退市或不可交易状态；只要 `daily_prices` 有可用 `close` 和 `adj_factor`，就按上述公式构造标签。
- 停牌、退市、涨跌停等交易约束属于后续组合回测口径；本 phase 的 forward return 是统计标签，不是可执行收益。

CLI 摘要必须为每个 horizon 打印：

```text
horizon
valid_label_count
latest_usable_signal_date
```

`latest_usable_signal_date` 定义为该 horizon 下至少有 1 条非空 `forward_return` 的最大信号日期；如果没有任何有效标签，则为 `NULL` 或等价空值。

### Rank IC 和 ICIR

每个 `(factor_name, trade_date, horizon)` 计算 Rank IC：

```text
Rank IC = SpearmanCorr(factor_value, forward_return_h)
```

规则：

- Spearman 通过 average rank 后做 Pearson correlation 实现。
- 有效样本数少于 `min_ic_observations` 时，该日 IC 记为缺失。
- 横截面 `factor_value` rank 标准差为 0 时，该日 IC 记为缺失。
- 横截面 `forward_return` rank 标准差为 0 时，该日 IC 记为缺失。
- 缺失 IC 不进入 ICIR 的均值、标准差或样本数。
- `rank_ic` 保留原始方向。
- 同时输出 `oriented_rank_ic`：
  - `higher_is_better`：等于 `rank_ic`
  - `lower_is_better`：等于 `-rank_ic`
  - `boolean_filter`：为 `NaN`
- 默认不验证 hard filter。
- 即使 `include_hard_filters=True`，`boolean_filter` 的 `oriented_rank_ic` 也保持 `NaN`，不参与 oriented ICIR 聚合；CLI 应打印 warning。

ICIR 按每个 `(factor_name, horizon)` 聚合：

```text
icir = mean(rank_ic) / std(rank_ic)
oriented_icir = mean(oriented_rank_ic) / std(oriented_rank_ic)
```

规则：

- 标准差使用样本标准差 `ddof=1`。
- 有效 IC 少于 2 个或标准差为 0 时，ICIR 为空。
- `ic_summary` 只包含 IC 相关聚合指标。
- `decay_curve` 是 IC 聚合与 group return 聚合的 horizon 级汇总。

### Top / Bottom 分组收益

分组收益按单日横截面计算。

规则：

- 默认 `n_groups = 5`。
- 因子方向来自 `configs/data_dictionary.yaml`。
- `higher_is_better`：因子值越大越靠近 Top。
- `lower_is_better`：因子值越小越靠近 Top。
- `boolean_filter` 默认不参与分组收益；如果 `include_hard_filters=True` 后纳入，允许返回空分组结果并打印 warning。
- Top 是方向调整后的最高组。
- Bottom 是方向调整后的最低组。
- 每个 `(factor_name, trade_date, horizon)` 输出：
  - `top_return`
  - `bottom_return`
  - `top_minus_bottom_return`
  - `long_short_return`
  - `valid_group_size`
- `long_short_return` 与 `top_minus_bottom_return` 数值相同，仅作为分析口径，不代表可执行多空策略。
- 分组遇到 tied factor value 时必须使用确定性排序，例如按 `stock_code` 作为稳定 tie-breaker。
- 当 `valid_n < n_groups * min_group_size` 时，跳过该日 group return。
- 被跳过的 group return 不进入 decay curve 的 group return 聚合。

### 衰减曲线

衰减曲线按 `(factor_name, horizon)` 聚合。

至少输出：

```text
factor_name
horizon
valid_ic_dates
valid_group_dates
mean_rank_ic
icir
mean_oriented_rank_ic
oriented_icir
mean_top_return
mean_bottom_return
mean_top_minus_bottom_return
mean_long_short_return
```

规则：

- `valid_ic_dates` 只统计有非空 Rank IC 的日期。
- `valid_group_dates` 只统计有非空 group return 的日期。
- 小样本导致 group return 被跳过时，不影响同日 IC 的有效性。
- 衰减曲线只返回 DataFrame 并由 CLI 打印摘要，不渲染报告文件。

## 配置优先级

配置优先级必须明确：

```text
CLI flag > configs/validation.yaml > 内置默认
```

规则：

- `--horizon` 覆盖 YAML 中 `single_factor.horizons`。
- `--n-groups` 覆盖 YAML 中 `single_factor.n_groups`。
- 未传 CLI flag 时读取 YAML。
- YAML 缺失时使用内置默认。
- `runner.validate_factors` 收到的 `validation_config` 应视为已合并后的配置对象。
- 测试必须覆盖 CLI flag 覆盖 YAML 的行为。

## 文件变更

建议新增或修改：

```text
src/ashare/validation/__init__.py
src/ashare/validation/config.py
src/ashare/validation/labels.py
src/ashare/validation/ic.py
src/ashare/validation/quantile_returns.py
src/ashare/validation/decay.py
src/ashare/validation/runner.py
src/ashare/cli.py
configs/validation.yaml
tests/test_validation_labels.py
tests/test_validation_metrics.py
tests/test_validate_factors_cli.py
```

说明：

- `config.py` 负责读取 `configs/validation.yaml` 并合并 CLI 覆盖项。
- `labels.py` 只负责未来收益标签。
- `ic.py` 只负责 Rank IC / ICIR。
- `quantile_returns.py` 只负责 Top / Bottom 分组收益。
- `decay.py` 只负责 horizon 聚合。
- `runner.py` 负责读取 `factor_values`、合并标签、调度验证指标。
- `cli.py` 只把现有 `validate-factors` 命令接入真实逻辑，不实现其他命令。
- 不修改 `src/ashare/factors/`。
- 不修改 `src/ashare/pit/`。
- 不修改 `src/ashare/storage/schema.sql`。

## 接口建议

在 `src/ashare/validation/config.py` 中提供：

```python
def load_validation_config(config_path: str | Path = "configs/validation.yaml") -> dict[str, object]:
    ...

def merge_validation_config(
    config: Mapping[str, object] | None,
    horizons: Sequence[int] | None = None,
    n_groups: int | None = None,
) -> dict[str, object]:
    ...
```

在 `src/ashare/validation/labels.py` 中提供：

```python
def build_forward_return_labels(
    connection: duckdb.DuckDBPyConnection,
    signal_dates: Sequence[date],
    horizons: Sequence[int],
) -> pd.DataFrame:
    ...
```

返回字段至少包含：

```text
stock_code
trade_date
horizon
target_trade_date
forward_return
```

在 `src/ashare/validation/runner.py` 中提供：

```python
@dataclass(frozen=True)
class FactorValidationResult:
    coverage: pd.DataFrame
    label_summary: pd.DataFrame
    rank_ic: pd.DataFrame
    ic_summary: pd.DataFrame
    group_returns: pd.DataFrame
    decay_curve: pd.DataFrame
    warnings: tuple[str, ...] = ()

def validate_factors(
    connection: duckdb.DuckDBPyConnection,
    start_date: DateLike,
    end_date: DateLike,
    source_run_id: str,
    factor_names: Sequence[str] | None = None,
    horizons: Sequence[int] | None = None,
    n_groups: int | None = None,
    include_hard_filters: bool = False,
    validation_config: Mapping[str, object] | None = None,
    data_dictionary: Mapping[str, object] | None = None,
) -> FactorValidationResult:
    ...
```

规则：

- `factor_names is None` 时，默认验证数据字典中 `type: factor` 的因子，不包含 `type: hard_filter`。
- `include_hard_filters=True` 时才把 hard filter 纳入验证指标。
- 未知 factor name 必须报错。
- 缺少因子方向时必须报错，不静默假设方向。
- `source_run_id` 为空或缺失时必须报错。
- 空结果返回空 DataFrame，但 CLI 对完全没有输入因子行的场景应以非 0 退出并说明原因。

## `configs/validation.yaml`

将 Phase 0 骨架补为可运行配置，建议结构：

```yaml
single_factor:
  horizons: [5, 20, 60]
  n_groups: 5
  min_ic_observations: 3
  min_group_size: 1
  require_same_as_of_trade_date: true
  universe_factor_names:
    - is_st
    - is_suspended
    - is_delisted
    - low_liquidity
  label:
    price: adjusted_close
    return_type: close_to_close
```

不得在本 phase 加入报告输出配置、组合回测配置或 scan 配置。

## CLI 要求

修改现有命令：

```text
ashare validate-factors
```

建议参数：

```text
--db-path              默认 data/processed/ashare.duckdb
--from                 必填，验证起始日期
--to                   必填，验证结束日期
--source-run-id        必填，无默认值
--factor               可重复传入；不传则验证默认 factor 集合
--horizon              逗号分隔，例如 5,20,60
--n-groups             默认读取 configs/validation.yaml
--validation-config    默认 configs/validation.yaml
--data-dictionary      默认 configs/data_dictionary.yaml
--include-hard-filters 默认 false
--verbose              默认 false
```

行为：

- 只读打开 DuckDB。
- 打印验证区间、`source_run_id`、factor 列表、horizon 列表。
- 打印每个 horizon 的 `valid_label_count` 和 `latest_usable_signal_date`。
- 打印 coverage / missing rate 摘要。
- 打印 Rank IC / ICIR 摘要。
- 打印 Top / Bottom 分组收益摘要。
- 打印 decay curve 摘要。
- 默认只打印摘要和 `head(N)`，避免 factor x date x horizon 矩阵刷屏。
- `--verbose` 可以打印更完整的明细摘要，但仍不写文件。
- 明确打印：`long_short_return is for factor analysis only and is not an executable strategy.`
- 如果 coverage 使用 fallback universe，必须打印 warning。
- 如果 `include_hard_filters=True`，必须提示 boolean filter 的 oriented IC / group return 不纳入常规解释。
- 不写文件。
- 不生成 Markdown / CSV。
- 不调用 `scan`、`backtest`、`report`。

## 测试要求

新增或更新测试，至少覆盖：

1. future return label 使用 `trading_calendar` 的第 `h` 个后续开市日。
2. `h=1` 标签使用下一开市日，不使用同日。
3. label 使用 `close * adj_factor`，`adj_factor` 为空时 fallback 到 `close`。
4. 缺少起点价格或目标价格时，不生成该股票该 horizon 标签。
5. label 阶段不因 `is_suspended`、`is_delisted` 或 hard filter 状态主动剔除股票。
6. `signal_dates` 来自 `factor_values.trade_date`，不由 `trading_calendar` 扩展空日期。
7. `factor_values` 按 `source_run_id`、日期区间、factor name 正确过滤。
8. 默认排除 `as_of_date != trade_date` 的 factor rows。
9. 重复 factor key 默认 fail-fast，错误信息包含至多 5 个重复样例。
10. 覆盖率优先使用 hard filter rows 的 stock_code 并集推断 universe。
11. hard filter rows 不完整时仍使用并集，不使用交集。
12. hard filter rows 缺失时 fallback 到 factor_values 股票集合，并在结果或 CLI 中暴露提示。
13. 覆盖率和缺失率公式正确。
14. Rank IC 使用 Spearman average rank，结果与手算一致。
15. 有效样本数不足 `min_ic_observations` 时 IC 为空。
16. 横截面 factor rank 标准差为 0 时 IC 为空。
17. 横截面 forward return rank 标准差为 0 时 IC 为空。
18. ICIR 使用样本标准差，少于 2 个有效 IC 时为空。
19. `lower_is_better` 因子的 `oriented_rank_ic` 符号正确，测试中必须覆盖 `pe_ttm_percentile`。
20. `boolean_filter` 的 `oriented_rank_ic` 为 `NaN`，不参与 oriented ICIR 聚合。
21. Top / Bottom 分组按因子方向调整。
22. 分组 tied value 时排序确定。
23. `valid_n < n_groups * min_group_size` 时跳过该日 group return。
24. `long_short_return` 等于 `top_return - bottom_return`，并仅作为分析字段。
25. decay curve 对每个 factor / horizon 输出聚合结果。
26. decay curve 区分 `valid_ic_dates` 和 `valid_group_dates`。
27. 默认不验证 hard filter；`include_hard_filters=True` 时可以纳入但 warning 明确。
28. 未知 factor name 报错。
29. 数据字典缺少方向时报错。
30. CLI flag 覆盖 `configs/validation.yaml`，优先级为 CLI flag > YAML > 内置默认。
31. CLI `--source-run-id` 缺失时非 0 退出。
32. CLI 输出每个 horizon 的 `valid_label_count` 和 `latest_usable_signal_date`。
33. 使用 fixture + `ingest_local` + `calculate-factors` 构造临时 DuckDB 后，`validate_factors` 可返回非空结果。
34. `ashare validate-factors --from ... --to ... --source-run-id ...` 可以成功运行。
35. `ashare validate-factors` 不创建报告文件，不写入新表。
36. `ashare --help` 仍能看到前置命令：

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
  --to 2026-05-29 \
  --db-path data/processed/ashare.duckdb \
  --index-code LOCAL_FIXTURE \
  --source-run-id phase1a5-validation
```

```bash
conda run -n ashare-research-lab ashare validate-factors \
  --from 2026-03-30 \
  --to 2026-05-29 \
  --db-path data/processed/ashare.duckdb \
  --source-run-id phase1a5-validation \
  --factor return_20d \
  --factor pe_ttm_percentile \
  --horizon 5,20
```

```bash
conda run -n ashare-research-lab python - <<'PY'
import duckdb
from ashare.validation.runner import validate_factors

con = duckdb.connect("data/processed/ashare.duckdb", read_only=True)
result = validate_factors(
    connection=con,
    start_date="2026-03-30",
    end_date="2026-05-29",
    source_run_id="phase1a5-validation",
    factor_names=["return_20d", "pe_ttm_percentile"],
    horizons=[5, 20],
)
assert not result.coverage.empty, "coverage should not be empty"
assert not result.label_summary.empty, "label_summary should not be empty"
assert not result.rank_ic.empty, "rank_ic should not be empty"
assert not result.decay_curve.empty, "decay_curve should not be empty"
assert {"factor_name", "horizon"}.issubset(result.decay_curve.columns)
print(result.decay_curve[["factor_name", "horizon"]].drop_duplicates().to_dict("records"))
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

1. 运行 `git status`，确认只包含 Phase 1a-5 相关改动。
2. 执行 `git add .`。
3. 执行：

```bash
git commit -m "feat: phase 1a-5 single factor validation"
```

4. 最终回复说明：
   - 修改了哪些文件。
   - future return label 如何构造。
   - signal_dates 如何确定。
   - 覆盖率和缺失率分母如何确定。
   - Rank IC、ICIR、Top / Bottom、衰减曲线如何计算。
   - 多空收益为何只作为分析口径。
   - 验收命令是否全部通过。
   - commit hash。
   - 是否发现 plan 或前置 phase 的缺口。

## 不要实现

- 不实现新因子。
- 不重新计算 Phase 1a-4 因子。
- 不写入 `factor_values`。
- 不写入 `research_runs`。
- 不新增验证结果表。
- 不修改 DuckDB schema。
- 不生成 Markdown 报告。
- 不生成 CSV 报告。
- 不实现报告渲染。
- 不实现 `scan` 真实逻辑。
- 不实现候选股票排序。
- 不实现综合打分。
- 不实现因子标准化到 0-100。
- 不实现行业中性化。
- 不实现分年度表现。
- 不实现分行业表现。
- 不实现换手率。
- 不实现事件研究。
- 不实现组合回测。
- 不实现交易撮合、手续费、滑点、调仓或持仓逻辑。
- 不把 `long_short_return` 解释成可执行多空策略。
- 不接真实 AkShare 数据。
- 不调用 LLM。
- 不实现服务化 API。

## 发现的缺口

- Phase 1a-4.5 的 plan phase 归属可能把部分尚未实现的新因子标为 `phase: 1a-5`；本 goal 按本次要求将 Phase 1a-5 限定为单因子验证，不新增 `roe`、`gross_margin_change`、`ps_percentile` 等因子。
- Plan 第 11 节还列出分年度表现、分行业表现和换手率；本 phase 暂不覆盖，推迟到后续验证增强 phase。
- `factor_values` 没有唯一键；本 phase 不改 schema，验证层对重复 key 采用 fail-fast。
- `factor_values` 没有显式保存每个日期的完整 universe；本 phase 优先用 hard filter rows 的并集推断覆盖率分母，缺失时 fallback 并提示覆盖率可能高估。
- 停牌、退市、涨跌停等可交易性约束需要组合回测阶段处理；本 phase 的 forward return 仅是统计标签。
