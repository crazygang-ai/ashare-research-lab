# Phase 1a-6 Goal: 因子报告 + 候选清单

请在已完成 Phase 1a-5 的 `/Users/crazy/own_project/ashare-research-lab` 仓库中继续实现 Phase 1a-6：因子报告 + 候选清单。

本 phase 只做两件事：

1. 基于 Phase 1a-5 的单因子验证结果生成 Markdown / CSV 因子验证报告。
2. 基于已落库的 `factor_values` 生成最小候选研究清单。

不计算新因子，不新增验证指标，不做综合评分，不做组合回测，不接 LLM。

## 目标

1. 将 `FactorValidationResult` 渲染为可复盘的 Markdown 因子验证报告。
2. 将验证结果明细输出为 CSV 文件：
   - coverage
   - label_summary
   - rank_ic
   - ic_summary
   - group_returns
   - decay_curve
3. 将现有 `ashare report` 从空壳改为支持 `factor-validation` 报告生成。
4. 将现有 `ashare scan` 从空壳改为最小候选清单输出。
5. `scan` 基于单日 `factor_values`、硬过滤字段和一个显式指定的排序因子生成 Top N。
6. 候选清单输出：
   - Top N
   - 因子分项
   - 入选原因
   - 风险提示
   - Markdown
   - CSV
7. 增加测试，覆盖报告渲染、CSV 输出、候选排序、硬过滤、重复键 fail-fast、CLI 和“不写 DB”。

## 工作约束

- 严格遵守 `docs/planning/a-share-research-plan.md`。
- 所有 Python 命令必须在 Conda 环境 `ashare-research-lab` 中执行。
- 本 phase 只读取 `factor_values` 和 Phase 1a-5 验证结果。
- 本 phase 不计算新因子。
- 本 phase 不重新实现 Rank IC、ICIR、分组收益或衰减曲线。
- 因子报告必须复用 Phase 1a-5 的 `validate_factors` / `FactorValidationResult`。
- 本 phase 不写入 `factor_values`。
- 本 phase 不写入 `research_runs`。
- 本 phase 不新增 DuckDB 表，不修改 schema。
- `report` 和 `scan` 默认以 DuckDB `read_only=True` 打开数据库。
- `scan` 必须显式传入 `as_of_date`，不能默认使用当前日期。
- `scan` 必须显式传入 `source_run_id`，不能默认读取旧 run。
- `scan` 必须显式传入 `--sort-factor`，避免隐式综合打分。
- `scan` 不允许输出 `score`、`total_score`、`composite_score` 等综合评分字段。
- 不调用 AkShare。
- 不调用 LLM。
- Phase 1a-6 完成后单独 commit。
- 提交信息为：`feat: phase 1a-6 factor reports and candidate scan`

## 文件变更

建议新增或修改：

```text
src/ashare/reports/__init__.py
src/ashare/reports/factor_report.py
src/ashare/reports/candidate_report.py
src/ashare/scan/__init__.py
src/ashare/scan/candidates.py
src/ashare/cli.py
docs/planning/followups.md
tests/test_factor_report.py
tests/test_candidate_scan.py
tests/test_report_cli.py
tests/test_scan_cli.py
```

可选修改：

```text
.gitignore
```

仅当当前仓库未忽略生成报告目录时，允许加入：

```gitignore
data/reports/generated/
```

本 phase 不应提交实际生成的 Markdown / CSV 报告文件。

## 输出确定性要求

所有 CSV 和 Markdown 表格输出必须有固定排序口径。

验证报告 CSV 排序：

```text
coverage.csv:
  ORDER BY factor_name, trade_date

label_summary.csv:
  如果存在 trade_date 列，ORDER BY horizon, trade_date
  如果不存在 trade_date 列，ORDER BY horizon

rank_ic.csv:
  ORDER BY factor_name, horizon, trade_date

group_returns.csv:
  ORDER BY factor_name, horizon, trade_date

ic_summary.csv:
  ORDER BY factor_name, horizon

decay_curve.csv:
  ORDER BY factor_name, horizon
```

规则：

- 不为了排序给 Phase 1a-5 未定义的结果表强行补列。
- 如果某个 DataFrame 缺少上述排序键中的可选列，按该表已定义的固定键排序。
- Markdown 中展示的表格必须使用与对应 CSV 相同的排序。
- warnings 按 `FactorValidationResult.warnings` 原始顺序输出，不排序。

候选清单 CSV 列顺序必须固定为：

```text
rank
stock_code
stock_name
industry_l1
industry_l2
as_of_date
source_run_id
sort_factor
sort_factor_value
factor__<factor_name>...
hard_filter__is_st
hard_filter__is_suspended
hard_filter__is_delisted
hard_filter__low_liquidity
selection_reason
risk_tips
```

候选清单行顺序必须固定为：

```text
ORDER BY rank ASC
```

`factor__<factor_name>` 列顺序：

- `--sort-factor` 永远排在第一位。
- 用户显式传入的 `--factor` 按 CLI 传入顺序保留，并去重。
- 未传 `--factor` 时，使用数据字典中 `type: factor` 的因子名按字母序排列。
- `--sort-factor` 如果未出现在展示因子列表中，自动插入到第一位。

## 因子验证报告

### 输入

报告输入来自 Phase 1a-5：

```text
FactorValidationResult.coverage
FactorValidationResult.label_summary
FactorValidationResult.rank_ic
FactorValidationResult.ic_summary
FactorValidationResult.group_returns
FactorValidationResult.decay_curve
FactorValidationResult.warnings
```

报告命令允许重新调用 `validate_factors` 生成内存结果，但不得创建验证结果表。

### metadata 约定

`render_factor_validation_markdown` 的 `metadata` 必须至少包含：

```text
generated_at
db_path
source_run_id
validation_from
validation_to
factors
horizons
n_groups
include_hard_filters
validation_config_path
data_dictionary_path
```

规则：

- 缺少必需 metadata key 时 fail-fast。
- `generated_at` 使用带时区或明确本地时区的 ISO 8601 字符串。
- `factors` 按 CLI 输入顺序；未显式传入时按实际验证因子名确定性排序。
- `horizons` 保持 CLI / config 合并后的顺序。

### 输出文件

给定 `--output-dir`，至少生成：

```text
factor_validation_report.md
coverage.csv
label_summary.csv
rank_ic.csv
ic_summary.csv
group_returns.csv
decay_curve.csv
```

Markdown 报告至少包含：

1. 标题。
2. 生成时间。
3. 数据库路径。
4. 验证区间。
5. `source_run_id`。
6. factor 列表。
7. horizon 列表。
8. label summary 摘要。
9. coverage / missing rate 摘要。
10. Rank IC / ICIR 摘要。
11. Top / Bottom 分组收益摘要。
12. 衰减曲线摘要。
13. warnings。
14. 口径说明：
    - forward return 是验证标签，不是交易收益。
    - long_short_return 只用于单因子分析，不代表可执行策略。
    - 本报告不是回测报告。
    - 本报告不包含综合评分。
    - 分年度表现、分行业表现不在 Phase 1a-6 输出范围内。

CSV 必须保留完整明细，不只输出 head。

### 不补造指标

Plan 第 15 节的因子验证报告包含分年度表现、分行业表现等内容，但 Phase 1a-5 尚未实现这些指标。

本 phase 不补造这些指标，不新增验证计算。

## 候选清单 scan 口径

### 输入

`scan` 只读取：

```text
factor_values
configs/data_dictionary.yaml
securities as-of 查询结果，可选用于 stock_name
industry_classifications as-of 查询结果，可选用于行业展示
```

候选因子数据过滤条件：

```text
source_run_id = ?
trade_date = as_of_date
as_of_date = trade_date
```

`stock_name`、`industry_l1`、`industry_l2` 必须使用 scan 的 `--as-of` 做 PIT 查询，不能读取当前状态倒推。

### 重复键 fail-fast

`scan` 读取 `factor_values` 后，必须复用 Phase 1a-5 的重复键检查口径。

如果过滤后的数据中同一键出现 2 行或更多，必须 fail-fast：

```text
(source_run_id, stock_code, trade_date, as_of_date, factor_name)
```

错误信息必须打印至多 5 个重复样例，方便定位问题。

不得通过 `drop_duplicates`、取第一行或聚合均值静默处理重复键。

### 空输入语义

规则：

- 如果 `(source_run_id, as_of_date)` 下没有任何符合 `trade_date = as_of_date AND as_of_date = trade_date` 的 `factor_values` 行，CLI 必须非 0 退出，并说明没有可扫描的因子输入。
- 如果存在因子输入，但所有股票因硬过滤或排序因子缺失被排除，CLI 退出码为 0，生成空候选文件，并打印 warning。
- 空候选文件仍必须包含固定 CSV 表头和 Markdown 口径说明。

### 硬过滤

默认硬过滤字段：

```text
is_st
is_suspended
is_delisted
low_liquidity
```

默认规则：

```text
is_st == 0.0
is_suspended == 0.0
is_delisted == 0.0
low_liquidity == 0.0
```

规则：

- 硬过滤字段缺失时，默认保守排除该股票。
- 硬过滤值为 `1.0` 时排除。
- 被排除股票不进入 Top N。
- `selection_reason` 只对入选股票生成；硬过滤被保守排除的股票不在候选 CSV 中。
- 本 phase 不输出被排除股票明细，除非实现者为了测试增加内部返回字段；CLI 默认只输出候选清单。

### 排序规则

`--sort-factor` 必填。

规则：

- `--sort-factor` 必须存在于 `configs/data_dictionary.yaml`。
- `--sort-factor` 的 `type` 必须是 `factor`，不能是 `hard_filter`。
- 排序方向来自数据字典：
  - `higher_is_better`：因子值降序。
  - `lower_is_better`：因子值升序。
- 排序因子缺失的股票不进入候选。
- tied factor value 使用 `stock_code` 升序作为稳定 tie-breaker。
- `--top` 默认 `20`。
- 不做多因子加权。
- 不做 0-100 标准化。
- 不做行业中性化。
- 不根据 ICIR 自动调权或自动剔除因子。

### `--factor` 语义

`--factor` 只控制候选清单展示哪些连续因子分项。

规则：

- `--factor` 只接受数据字典中 `type: factor` 的因子名。
- 如果传入 `type: hard_filter` 的名称，例如 `--factor is_st`，必须报错。
- hard filter 列固定输出四列，不通过 `--factor` 控制：
  - `hard_filter__is_st`
  - `hard_filter__is_suspended`
  - `hard_filter__is_delisted`
  - `hard_filter__low_liquidity`
- 未知 factor name 必须报错。
- 不传 `--factor` 时，默认展示数据字典中 `type: factor` 的全部因子。
- `--sort-factor` 必须自动加入展示因子列表。

### 入选原因

`selection_reason` 必须是确定性文本，不使用 LLM。

至少包含：

- 按哪个 `sort_factor` 排序进入 Top N。
- 该排序因子的方向和数值。
- 硬过滤均通过。

示例语义：

```text
按 return_20d higher_is_better 排序进入 Top 3；return_20d=0.1234；硬过滤均通过。
```

### 风险提示

`risk_tips` 必须是规则生成，不使用 LLM。

固定规则：

- 展示因子缺失：输出对应缺失因子名。
- `pe_ttm_percentile >= 0.8`：估值处于自身历史高位。
- `pb_percentile >= 0.8`：PB 处于自身历史高位。
- `return_20d < 0`：20 日动量为负。
- `return_60d < 0`：60 日动量为负。
- `above_ma60 == 0.0`：价格低于 60 日均线。

`above_ma60` 缺失和 `above_ma60 == 0.0` 必须区分：

- 缺失：只触发“展示因子缺失”风险。
- 存在且等于 `0.0`：触发“价格低于 60 日均线”风险。
- 两者互斥。

没有触发风险时写：

```text
未触发本阶段规则风险提示
```

`pe_ttm_percentile` / `pb_percentile` 的 `0.8` 阈值本 phase 暂时硬编码，不做配置化；配置化需求登记到 `docs/planning/followups.md`。

## 候选清单报告

### metadata 约定

`render_candidate_markdown` 的 `metadata` 必须至少包含：

```text
generated_at
db_path
source_run_id
as_of_date
sort_factor
sort_factor_direction
top_n
factor_names
hard_filter_names
data_dictionary_path
```

规则：

- 缺少必需 metadata key 时 fail-fast。
- `generated_at` 使用带时区或明确本地时区的 ISO 8601 字符串。
- `factor_names` 使用最终展示因子顺序。
- `hard_filter_names` 固定为 `is_st, is_suspended, is_delisted, low_liquidity`。

### 输出文件

给定 `--output-dir`，至少生成：

```text
candidate_list.md
candidates.csv
```

Markdown 至少包含：

1. 标题。
2. 生成时间。
3. 数据库路径。
4. `as_of_date`。
5. `source_run_id`。
6. `sort_factor` 和排序方向。
7. Top N。
8. 因子分项。
9. 入选原因。
10. 风险提示。
11. 口径说明：
    - candidate list is for research only and is not a trading instruction.
    - 候选清单未做综合评分。
    - 候选清单未做组合回测。
    - 候选清单未应用真实交易约束。
    - 候选清单未接入 LLM。
    - 排序只使用显式传入的 `sort_factor`。

## 接口建议

### 因子报告

建议在 `src/ashare/reports/factor_report.py` 中提供：

```python
def render_factor_validation_markdown(
    result: FactorValidationResult,
    metadata: Mapping[str, object],
) -> str:
    ...

def write_factor_validation_report(
    result: FactorValidationResult,
    output_dir: str | Path,
    metadata: Mapping[str, object],
    overwrite: bool = False,
) -> dict[str, Path]:
    ...
```

要求：

- 纯渲染函数不读写文件。
- 写文件函数只写入 `output_dir`。
- `overwrite=False` 且目标文件已存在时 fail-fast。
- CSV 输出按本 goal 的固定排序键排序。
- Markdown 输出按本 goal 的固定章节顺序和表格排序输出。

### 候选清单

建议在 `src/ashare/scan/candidates.py` 中提供：

```python
@dataclass(frozen=True)
class CandidateScanResult:
    candidates: pd.DataFrame
    warnings: tuple[str, ...] = ()

def scan_candidates(
    connection: duckdb.DuckDBPyConnection,
    as_of_date: DateLike,
    source_run_id: str,
    sort_factor: str,
    factor_names: Sequence[str] | None = None,
    top_n: int = 20,
    data_dictionary: Mapping[str, object] | None = None,
) -> CandidateScanResult:
    ...
```

建议在 `src/ashare/reports/candidate_report.py` 中提供：

```python
def render_candidate_markdown(
    result: CandidateScanResult,
    metadata: Mapping[str, object],
) -> str:
    ...

def write_candidate_report(
    result: CandidateScanResult,
    output_dir: str | Path,
    metadata: Mapping[str, object],
    overwrite: bool = False,
) -> dict[str, Path]:
    ...
```

## CLI 要求

### `ashare report`

将现有 `report` 命令接入因子验证报告。

本 phase 明确替换 Phase 0 placeholder 的 `--as-of` 参数；新的 `report` 命令不保留旧 `--as-of` 占位参数。

`--kind` 必填，本 phase 只接受：

```text
factor-validation
```

如果 `--kind` 不是 `factor-validation`，必须报错并说明本 phase 只支持因子验证报告。

建议参数：

```text
--kind                 必填，只支持 factor-validation
--db-path              默认 data/processed/ashare.duckdb
--from                 必填，验证起始日期
--to                   必填，验证结束日期
--source-run-id        必填，无默认值
--factor               可重复传入
--horizon              逗号分隔，例如 5,20
--n-groups             可选
--validation-config    默认 configs/validation.yaml
--data-dictionary      默认 configs/data_dictionary.yaml
--include-hard-filters 默认 false
--output-dir           必填或默认 data/reports/generated/factor-validation
--overwrite            默认 false
```

行为：

- 只读打开 DuckDB。
- 调用 Phase 1a-5 `validate_factors`。
- `--horizon`、`--n-groups` 与 Phase 1a-5 一致，配置优先级为：

```text
CLI flag > configs/validation.yaml > 内置默认
```

- `--include-hard-filters` 原样透传给 `validate_factors`。
- 如果 `--include-hard-filters` 打开，Markdown warnings 区域必须复述 Phase 1a-5 关于 boolean filter 的 warning。
- 生成 Markdown / CSV 报告。
- 成功后打印输出文件路径。
- 不写 DB。
- 不调用 `scan`。
- 不调用 `backtest`。

### `ashare scan`

将现有 `scan` 命令接入最小候选清单。

建议参数：

```text
--db-path              默认 data/processed/ashare.duckdb
--as-of                必填，ISO 日期
--source-run-id        必填，无默认值
--sort-factor          必填
--factor               可重复传入，用于展示 type: factor 的因子
--top                  默认 20
--data-dictionary      默认 configs/data_dictionary.yaml
--output-dir           必填或默认 data/reports/generated/scan
--overwrite            默认 false
```

行为：

- 只读打开 DuckDB。
- 基于单日 `factor_values` 生成候选 Top N。
- 写出 `candidates.csv` 和 `candidate_list.md`。
- 控制台打印 Top N 摘要。
- 明确打印：`candidate list is for research only and is not a trading instruction.`
- 不写 DB。
- 不生成综合评分。
- 不调用回测。
- 不调用 LLM。

## followups 更新

修改 `docs/planning/followups.md`，追加本 phase 新留下的工程债。

至少新增：

```text
D20 candidate scan 风险阈值硬编码
D21 candidate scan 暂不支持多因子加权 / 行业中性化
D22 candidate report 与 plan 第 15 节每日研究报告仍有差距
```

每条仍按 Phase 1a-4.5 约定格式记录：

```markdown
### Dxx. <债标题>

- 现状: ...
- 触发: ...
- 决策: ...
- 关联: ...
```

不得借本 phase 实现 D20-D22。

## 测试要求

新增或更新测试，至少覆盖：

1. `render_factor_validation_markdown` 输出包含 metadata、coverage、IC、group return、decay curve 和 warnings。
2. `render_factor_validation_markdown` 缺少必需 metadata key 时 fail-fast。
3. `write_factor_validation_report` 写出 1 个 Markdown 和 6 个 CSV。
4. 验证报告 CSV 文件包含预期列，且不是只输出空壳。
5. 验证报告 CSV 按本 goal 固定排序键排序。
6. `overwrite=False` 时目标文件存在会 fail-fast。
7. `ashare report --kind factor-validation ...` 可以成功生成报告。
8. `ashare report --kind other ...` 非 0 退出。
9. `ashare report --help` 能看到 `factor-validation`。
10. `ashare report` 不写入 DuckDB 新表，不写入 `factor_values`。
11. `scan_candidates` 只读取 `source_run_id`、`trade_date=as_of_date`、`as_of_date=trade_date` 的因子值。
12. `scan_candidates` 对重复 `(source_run_id, stock_code, trade_date, as_of_date, factor_name)` fail-fast，错误信息包含至多 5 个样例。
13. `scan_candidates` 默认应用 `is_st`、`is_suspended`、`is_delisted`、`low_liquidity` 硬过滤。
14. 硬过滤字段缺失时默认排除该股票。
15. `higher_is_better` 因子按降序排序。
16. `lower_is_better` 因子按升序排序，必须覆盖 `pe_ttm_percentile`。
17. tied factor value 使用 `stock_code` 稳定排序。
18. `--sort-factor` 为 hard filter 时必须报错。
19. `--factor` 为 hard filter 时必须报错。
20. 未知 factor name 必须报错。
21. 排序因子缺失的股票不进入候选。
22. 没有任何可扫描 `factor_values` 输入时 CLI 非 0 退出。
23. 存在输入但硬过滤后候选为空时 CLI 成功生成空候选文件并打印 warning。
24. 输出候选数量不超过 `top_n`。
25. candidates CSV 列顺序与本 goal 固定列顺序一致。
26. candidates CSV 行顺序为 `rank` 升序。
27. candidates CSV 不包含 `score`、`total_score`、`composite_score` 字段。
28. `selection_reason` 包含排序因子、方向、数值和硬过滤通过说明。
29. `risk_tips` 覆盖估值高位、动量为负、低于 MA60、展示因子缺失。
30. `above_ma60` 缺失和 `above_ma60 == 0.0` 的风险提示互斥。
31. 无规则风险时输出固定文本。
32. `candidate_list.md` 包含 Top N、因子分项、入选原因、风险提示和研究用途口径说明。
33. `render_candidate_markdown` 缺少必需 metadata key 时 fail-fast。
34. `ashare scan ...` 可以成功生成 `candidates.csv` 和 `candidate_list.md`。
35. `ashare scan` 不写入 DuckDB。
36. `docs/planning/followups.md` 包含 D20、D21、D22。
37. `ashare --help` 仍能看到前置命令：

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

测试数据必须通过 fixture builder、`ingest_local`、`calculate-factors`、`validate_factors` 在 `tmp_path` 下构造，不依赖仓库内已有 DuckDB 文件。

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
  --source-run-id phase1a6-validation
```

```bash
conda run -n ashare-research-lab ashare report \
  --kind factor-validation \
  --from 2026-03-30 \
  --to 2026-05-29 \
  --db-path data/processed/ashare.duckdb \
  --source-run-id phase1a6-validation \
  --factor return_20d \
  --factor pe_ttm_percentile \
  --horizon 5,20 \
  --output-dir data/reports/generated/phase1a6/factor-validation \
  --overwrite
```

```bash
conda run -n ashare-research-lab ashare calculate-factors \
  --as-of 2026-06-26 \
  --db-path data/processed/ashare.duckdb \
  --index-code LOCAL_FIXTURE \
  --source-run-id phase1a6-scan
```

```bash
conda run -n ashare-research-lab ashare scan \
  --as-of 2026-06-26 \
  --db-path data/processed/ashare.duckdb \
  --source-run-id phase1a6-scan \
  --sort-factor return_20d \
  --factor return_20d \
  --factor pe_ttm_percentile \
  --factor revenue_yoy \
  --top 3 \
  --output-dir data/reports/generated/phase1a6/scan \
  --overwrite
```

```bash
conda run -n ashare-research-lab python - <<'PY'
from pathlib import Path
import pandas as pd

factor_dir = Path("data/reports/generated/phase1a6/factor-validation")
scan_dir = Path("data/reports/generated/phase1a6/scan")

expected_factor_files = {
    "factor_validation_report.md",
    "coverage.csv",
    "label_summary.csv",
    "rank_ic.csv",
    "ic_summary.csv",
    "group_returns.csv",
    "decay_curve.csv",
}
missing = [name for name in expected_factor_files if not (factor_dir / name).exists()]
assert not missing, f"missing factor report files: {missing}"

rank_ic = pd.read_csv(factor_dir / "rank_ic.csv")
if not rank_ic.empty:
    expected = rank_ic.sort_values(["factor_name", "horizon", "trade_date"]).reset_index(drop=True)
    pd.testing.assert_frame_equal(rank_ic.reset_index(drop=True), expected)

candidates_csv = scan_dir / "candidates.csv"
candidate_md = scan_dir / "candidate_list.md"
assert candidates_csv.exists(), "missing candidates.csv"
assert candidate_md.exists(), "missing candidate_list.md"

candidates = pd.read_csv(candidates_csv)
assert len(candidates) <= 3
assert "selection_reason" in candidates.columns
assert "risk_tips" in candidates.columns
for forbidden in ["score", "total_score", "composite_score"]:
    assert forbidden not in candidates.columns
if not candidates.empty:
    assert candidates["rank"].tolist() == sorted(candidates["rank"].tolist())

text = candidate_md.read_text(encoding="utf-8")
assert "candidate list is for research only" in text
assert "综合评分" in text
assert "组合回测" in text
assert "风险" in text or "risk" in text
print("OK phase1a6 artifacts")
PY
```

```bash
conda run -n ashare-research-lab python - <<'PY'
from pathlib import Path

text = Path("docs/planning/followups.md").read_text(encoding="utf-8")
required = ["D20", "D21", "D22", "风险阈值", "多因子", "每日研究报告"]
missing = [item for item in required if item not in text]
assert not missing, f"followups.md missing: {missing}"
print("OK followups D20-D22")
PY
```

```bash
conda run -n ashare-research-lab pytest -q
```

```bash
conda run -n ashare-research-lab ashare --help
```

## 完成后

1. 运行 `git status`，确认只包含 Phase 1a-6 相关代码、测试和必要文档改动。
2. 确认未提交 `data/reports/generated/` 下的生成报告。
3. 执行 `git add .`。
4. 执行：

```bash
git commit -m "feat: phase 1a-6 factor reports and candidate scan"
```

5. 最终回复说明：
   - 修改了哪些文件。
   - 因子验证报告输出了哪些 Markdown / CSV。
   - `scan` 如何排序、如何硬过滤、如何生成入选原因和风险提示。
   - 如何保证没有综合评分、没有回测、没有 LLM。
   - followups 是否追加 D20-D22。
   - 验收命令是否全部通过。
   - commit hash。
   - 是否发现 plan 或前置 phase 的缺口。

## 不要实现

- 不实现新因子。
- 不重新计算 Phase 1a-4 因子。
- 不新增 Rank IC、ICIR、分组收益或衰减曲线计算口径。
- 不写入 `factor_values`。
- 不写入 `research_runs`。
- 不新增验证结果表。
- 不修改 DuckDB schema。
- 不实现综合评分。
- 不实现 factor weighting。
- 不实现 0-100 标准化。
- 不实现行业中性化。
- 不实现组合回测。
- 不实现交易撮合、手续费、滑点、调仓或持仓逻辑。
- 不实现事件研究。
- 不实现 LLM 公告解析。
- 不从公告正文生成风险提示。
- 不接真实 AkShare 数据。
- 不实现服务化 API。
- 不实现完整每日研究报告。
- 不实现单股研究报告。
- 不把候选清单描述为买入、卖出或交易指令。
- 不实现 D20-D22，只登记。

## 发现的缺口

- Phase 1a-5 只返回内存中的验证结果，不持久化验证结果表；本 phase 的因子报告应重新调用验证 runner，不应假设数据库里已有验证结果表。
- Plan 第 15 节的因子验证报告包含分年度表现、分行业表现，但 Phase 1a-5 尚未实现这些指标；本 phase 不补造，报告中只呈现已有验证结果。
- Phase 0 的 `.gitignore` 未明确忽略生成报告目录；如果本 phase 默认向 `data/reports/generated/` 输出，应补充忽略规则或确保生成报告不进入 commit。
- 本 phase 的候选清单距离 plan 第 15 节“每日研究报告”仍有差距：不包含公告摘要、相对强弱、上一交易日新增 / 移出 / 排名变化。
- 本 phase 风险提示阈值暂硬编码，后续如要用于正式研究运行，应配置化并纳入数据字典或 scan 配置。
