# Phase 3 Goal: 综合评分

请在已完成 Phase 2 的 `/Users/crazy/own_project/ashare-research-lab` 仓库中继续实现 Phase 3：综合评分。

本 phase 只做综合评分层：因子 0-100 标准化、硬过滤、分组子分、软风险扣分、配置化权重、权重敏感性测试和分年度稳定性测试。

综合评分只能读取已落库的 `factor_values` 和已生成的因子验证报告产物。只有通过验证门槛的因子允许进入综合评分。LLM 解析结果不得直接进入总分。

## 目标

1. 增加 `ashare score` CLI 命令。
2. 基于显式传入的 `as_of_date`、`source_run_id`、`index_code` 和验证报告目录生成综合评分。
3. 实现因子横截面标准化到 `0-100`。
4. 实现硬过滤：
   - `is_st`
   - `is_suspended`
   - `is_delisted`
   - `low_liquidity`
5. 实现分组子分：
   - `financial_score`
   - `valuation_score`
   - `momentum_score`
   - `event_score` 保留配置位置，但默认禁用。
6. 实现软风险扣分框架：
   - 只消费已在 `factor_values` 中存在、已在数据字典中定义、且通过验证门槛的软风险因子。
   - 本 phase 不从 `risk_events`、财报原表或 LLM 解析表计算新风险因子。
7. 实现配置化权重：
   - 分组权重配置化。
   - 组内因子权重配置化。
   - 软风险扣分权重和扣分上限配置化。
8. 实现验证门槛：
   - 未在验证报告中出现的因子不得评分。
   - 未满足 `configs/scoring.yaml` 中验证门槛的因子不得评分。
   - strict 模式下，启用但未通过验证的评分因子必须 fail-fast。
9. 输出综合评分明细、标准化因子分、硬过滤排除明细、验证门槛结果、权重敏感性测试和分年度稳定性测试。
10. 生成 Markdown 综合评分报告和 CSV 明细。
11. 增加测试，覆盖标准化、硬过滤、权重、软扣分、验证门槛、敏感性、分年度稳定性、CLI 和“不写 DB”。

## 工作约束

- 严格遵守 `docs/planning/a-share-research-plan.md`。
- 所有 Python 命令必须在 Conda 环境 `ashare-research-lab` 中执行。
- 每个 phase 必须单独 commit。
- 本 phase 不计算新因子。
- 本 phase 不重新实现 Phase 1a-4 因子计算。
- 本 phase 不重新实现 Phase 1a-5 单因子验证。
- 本 phase 不重新实现 Phase 1a-6 单因子候选清单。
- 本 phase 不重新实现 Phase 1b 组合回测。
- 本 phase 不重新实现 Phase 2 LLM 解析。
- 本 phase 不实现事件研究。
- 本 phase 不实现 LLM 事件分。
- 本 phase 不直接读取 `announcement_llm_results`、`announcement_llm_evidence` 参与评分。
- 本 phase 不写入 `factor_values`。
- 本 phase 不写入 `research_runs`。
- 本 phase 不新增 DuckDB 表，不修改 schema。
- `score` 默认以 DuckDB `read_only=True` 打开数据库。
- `score` 必须显式传入 `--as-of`、`--source-run-id`、`--index-code` 和 `--validation-dir`。
- `score` 不能默认使用当前日期、最近 run 或旧报告。
- `score` 的单日因子读取语义必须与 Phase 1a-6 `scan` 对齐：`trade_date = as_of_date` 且 `factor_values.as_of_date = trade_date`。
- `score` 不替代 `scan`：`scan` 仍是单因子 Top N 候选清单；`score` 是通过验证门槛后的多因子综合评分报告。
- 权重敏感性测试只做诊断，不自动调权。
- 分年度稳定性测试只验证综合评分信号稳定性，不做组合回测。
- Phase 3 完成后单独 commit。
- 提交信息为：`feat: phase 3 composite scoring`

## 文件变更

建议新增或修改：

```text
src/ashare/scoring/__init__.py
src/ashare/scoring/config.py
src/ashare/scoring/validation_gate.py
src/ashare/scoring/loaders.py
src/ashare/scoring/normalization.py
src/ashare/scoring/filters.py
src/ashare/scoring/scorer.py
src/ashare/scoring/diagnostics.py
src/ashare/reports/scoring_report.py
src/ashare/cli.py
configs/scoring.yaml
docs/planning/followups.md
tests/test_scoring_config.py
tests/test_scoring_validation_gate.py
tests/test_scoring_normalization.py
tests/test_scoring_filters.py
tests/test_scoring_scorer.py
tests/test_scoring_diagnostics.py
tests/test_scoring_report.py
tests/test_score_cli.py
```

可选修改：

```text
.gitignore
```

仅当当前仓库未忽略生成报告目录时，允许加入：

```gitignore
data/reports/generated/
```

本 phase 不应提交生成的评分报告、CSV、DuckDB、公告正文、fixture 生成产物或缓存数据。

## 输入数据

综合评分只读取：

```text
factor_values
trading_calendar
universe_members
securities
industry_classifications
configs/scoring.yaml
configs/data_dictionary.yaml
Phase 1a-6 生成的 factor-validation 报告目录
```

验证报告目录至少包含：

```text
coverage.csv
rank_ic.csv
ic_summary.csv
group_returns.csv
decay_curve.csv
```

规则：

- `factor_values` 读取条件必须包含 `source_run_id = ?`。
- 单日评分使用 `score_date = --as-of`。
- 因子值读取必须使用：

```text
source_run_id = ?
trade_date = score_date
as_of_date = score_date
```

- 本 phase 不实现 `as_of_date <= score_date` 的 lookback 取数，避免与 Phase 1a-6 `scan` 出现同日候选口径不一致。
- 如果过滤后的数据中同一键出现 2 行或更多，必须 fail-fast：

```text
(source_run_id, stock_code, trade_date, as_of_date, factor_name)
```

- 错误信息必须打印至多 5 个重复样例。
- 不允许用 `drop_duplicates`、取第一行或聚合均值静默处理重复键。
- 股票池必须来自 `query_universe_members_as_of(index_code=..., as_of_date=score_date)`。
- 股票名称和行业展示必须使用同一个 `score_date` 的 PIT 查询结果。
- 不得读取当前证券名称、当前行业或当前指数成分倒推历史。

## 验证门槛

只有满足以下全部条件的因子允许进入综合评分：

1. 出现在 `configs/scoring.yaml` 的启用因子列表中。
2. 出现在 `configs/data_dictionary.yaml` 中。
3. `type` 不是 `hard_filter`。
4. 有明确 `direction`。
5. 有明确 `score_group` 或在 `configs/scoring.yaml` 中显式指定 group。
6. 出现在 `--validation-dir` 的验证报告 CSV 中。
7. 满足 `configs/scoring.yaml.validation_gate` 的阈值。
8. 不是同一个名字同时用于硬过滤和软扣分。
9. 不是同一个名字同时用于正向子分和软风险扣分。

验证门槛必须直接使用 Phase 1a-5 / Phase 1a-6 已输出的真实列名，不得另造同义列名。

`ic_summary.csv` 映射固定为：

```text
valid_oriented_ic_dates   <- ic_summary.csv.valid_oriented_ic_dates
mean_oriented_rank_ic     <- ic_summary.csv.mean_oriented_rank_ic
oriented_icir             <- ic_summary.csv.oriented_icir
```

默认验证门槛建议：

```yaml
validation_gate:
  mode: strict
  required_horizons: [20]
  min_coverage: 0.2
  min_valid_oriented_ic_dates: 1
  min_mean_oriented_rank_ic: 0.0
  min_oriented_icir: -999.0
  require_group_return_rows: true
```

说明：

- `min_oriented_icir` 默认保守放宽，避免小样本 fixture 因标准差为 0 导致 MVP 无法验收；但 `min_coverage`、`min_valid_oriented_ic_dates`、`min_mean_oriented_rank_ic` 仍必须真实生效。
- strict 模式下，启用但未通过验证门槛的评分因子必须让 CLI 非 0 退出。
- strict 模式 fail-fast 前必须写出 `validation_gate.csv` 和包含错误摘要的 `score_metadata.json`，便于审计失败原因。
- 非 strict 模式可以跳过未通过因子，但必须在 `validation_gate.csv` 和 Markdown 报告中明确列出。
- hard filter 字段不进入综合评分，不要求通过单因子验证。
- 硬验收必须覆盖 strict 模式因门槛过高而失败的路径，不能只覆盖所有因子 PASS 的路径。

## 标准化口径

标准化发生在硬过滤之后、组内加权之前。

流程：

```text
PIT universe
  -> 读取 factor_values
  -> 重复键检查
  -> 硬过滤
  -> 验证门槛
  -> 因子方向统一
  -> 横截面 percentile rank
  -> 0-100 标准化分
  -> 组内加权
  -> 分组子分
  -> 软风险扣分
  -> total_score
```

规则：

- 每个 `score_date` 独立横截面标准化。
- 标准化范围只包含硬过滤通过的股票。
- `higher_is_better`：原始值越大，标准化分越高。
- `lower_is_better`：原始值越小，标准化分越高。
- `boolean_filter` 不允许作为标准化子分。
- 缺失值不填 `0`，该股票该因子不产生标准化分。
- 若某因子当日有效样本数为 `0`，该因子当日不可用。
- 若某因子当日有效样本数为 `1`，该股票该因子标准化分为 `50.0`。
- 若某因子当日所有有效值相同，所有有效股票该因子标准化分为 `50.0`。
- 其他情况使用稳定 percentile rank，输出范围包含 `0.0` 到 `100.0`。
- tied value 使用平均 rank。
- 标准化结果必须 clamp 到 `[0.0, 100.0]`。
- `pe_ttm_percentile`、`pb_percentile`、`ps_percentile` 是原始因子层的单股票历史分位，本 phase 不重新计算历史分位；它们只作为原始因子值参与本 phase 的横截面标准化。

建议公式：

```text
oriented_value =
  raw_value                    if direction == higher_is_better
  -raw_value                   if direction == lower_is_better

normalized_score =
  50.0                         if n == 1 or all oriented_value equal
  100 * (rank - 1) / (n - 1)   otherwise
```

其中 `rank` 为 `oriented_value` 升序平均 rank，因此最大 `oriented_value` 得到 `100`。

## 硬过滤

默认硬过滤字段：

```text
is_st
is_suspended
is_delisted
low_liquidity
```

规则：

- 硬过滤字段来自 `factor_values`。
- 缺少任一硬过滤字段时，保守排除该股票。
- 硬过滤值不等于 `0.0` 时，排除该股票。
- 被硬过滤排除的股票不参与标准化、不参与分组子分、不参与总分。
- 被排除股票必须输出到 `hard_filter_exclusions.csv`。
- 硬过滤字段不得作为连续因子进入子分。
- 硬过滤字段不得作为软风险扣分项。
- `hard_filter_exclusions.csv` 即使为空，也必须输出固定表头。

`hard_filter_exclusions.csv` 固定列：

```text
as_of_date
source_run_id
index_code
stock_code
hard_filter_name
factor_value
exclusion_reason
```

排序：

```text
ORDER BY stock_code, hard_filter_name
```

## 分组子分

默认支持这些正向分组：

```text
financial
valuation
momentum
event
```

输出列名固定为：

```text
financial_score
valuation_score
momentum_score
event_score
```

规则：

- `event` 分组保留配置位置，但默认 `enabled: false`、`weight: 0.0`。
- 每个启用分组的组内因子必须通过验证门槛。
- 组内因子权重来自 `configs/scoring.yaml`。
- 启用分组的因子权重必须大于等于 `0`。
- 启用分组中所有 enabled 因子权重和必须为 `1.0`，允许 `1e-9` 浮点容差。
- 启用正向分组的 group weight 必须大于等于 `0`。
- 所有启用正向分组的 group weight 和必须为 `1.0`，允许 `1e-9` 浮点容差。
- 股票在某个 `required: true` 分组下有效因子权重覆盖不足时，该股票不得进入最终评分。
- 默认 `min_available_factor_weight = 0.5`。
- 缺失因子不得填 `0`。
- 组内可用因子权重达到门槛后，按可用权重重新归一化计算 group score。
- 分组子分必须 clamp 到 `[0.0, 100.0]`。
- 测试必须覆盖 `required: true` 分组因有效因子权重不足导致股票被剔除的路径。

## 软风险扣分

软风险扣分只消费已经存在于 `factor_values` 的软风险因子。

默认配置可以为空：

```yaml
risk_penalty:
  enabled: true
  max_penalty: 15.0
  factors: {}
```

规则：

- 软风险因子必须通过验证门槛。
- 软风险因子必须在 `configs/scoring.yaml` 中显式配置。
- 软风险因子不得同时作为硬过滤。
- 软风险因子不得同时作为正向子分。
- 软风险因子标准化为 `0-100` 的风险严重度，越高表示风险越大。
- `risk_direction` 必须显式配置：
  - `higher_is_worse`
  - `lower_is_worse`
- 启用软风险因子的配置权重和必须为 `1.0`，允许 `1e-9` 浮点容差。
- 对单只股票计算风险扣分时，缺失或未通过验证的风险因子不填 `0`。
- 对单只股票可用风险因子权重达到 `score.min_available_factor_weight` 后，按可用权重重新归一化。
- 单只股票全部软风险因子缺失，或可用风险因子权重不足时，`risk_penalty = 0.0`，并产生 warning。
- 单因子风险扣分贡献：

```text
factor_penalty = risk_severity_score / 100 * max_penalty * renormalized_available_penalty_weight
```

- 总软风险扣分：

```text
risk_penalty = min(max_penalty, sum(factor_penalty))
```

- 没有已验证软风险因子时，`risk_penalty = 0.0`，并在报告 warnings 中说明。
- `risk_penalty` 单位是总分点数，不是百分比。

## 总分公式

```text
positive_score =
  financial_weight * financial_score
+ valuation_weight * valuation_score
+ momentum_weight * momentum_score
+ event_weight * event_score

total_score = clamp(positive_score - risk_penalty, 0.0, 100.0)
```

规则：

- `total_score` 输出范围必须为 `[0.0, 100.0]`。
- 排名按 `total_score DESC, stock_code ASC`。
- `rank` 从 `1` 开始。
- 输出 Top N，但 `score_breakdown.csv` 和 `factor_normalized_scores.csv` 应保留所有硬过滤通过且可评分股票。
- `scored_candidates.csv.hard_filter_passed` 保留用于审计，候选行中恒为 `true`；被硬过滤排除的股票只出现在 `hard_filter_exclusions.csv`。
- 综合评分报告必须明确：候选清单仅供研究，不是交易指令。

## `configs/scoring.yaml`

将 Phase 0 骨架补为可运行配置，建议结构：

```yaml
version: phase3.v1

score:
  top_n: 20
  min_available_factor_weight: 0.5

validation_gate:
  mode: strict
  required_horizons: [20]
  min_coverage: 0.2
  min_valid_oriented_ic_dates: 1
  min_mean_oriented_rank_ic: 0.0
  min_oriented_icir: -999.0
  require_group_return_rows: true

normalization:
  method: percentile_rank
  output_min: 0.0
  output_max: 100.0
  single_observation_score: 50.0
  all_equal_score: 50.0
  tie_method: average
  industry_neutral:
    enabled: false

hard_filters:
  is_st:
    enabled: true
    pass_value: 0.0
    missing: exclude
  is_suspended:
    enabled: true
    pass_value: 0.0
    missing: exclude
  is_delisted:
    enabled: true
    pass_value: 0.0
    missing: exclude
  low_liquidity:
    enabled: true
    pass_value: 0.0
    missing: exclude

groups:
  financial:
    enabled: true
    required: false
    weight: 0.30
    factors:
      revenue_yoy:
        enabled: true
        weight: 0.50
      profit_yoy:
        enabled: true
        weight: 0.50

  valuation:
    enabled: true
    required: false
    weight: 0.30
    factors:
      pe_ttm_percentile:
        enabled: true
        weight: 0.50
      pb_percentile:
        enabled: true
        weight: 0.50

  momentum:
    enabled: true
    required: false
    weight: 0.40
    factors:
      return_20d:
        enabled: true
        weight: 0.50
      above_ma60:
        enabled: true
        weight: 0.50

  event:
    enabled: false
    required: false
    weight: 0.0
    factors: {}

risk_penalty:
  enabled: true
  max_penalty: 15.0
  factors: {}

diagnostics:
  sensitivity:
    enabled: true
    perturbation_pct: 0.10
    top_n: 20
  yearly_stability:
    enabled: true
    signal_frequency: month_end
    horizons: [20]
    min_signal_dates_per_year: 1
```

如果 fixture 数据导致默认启用因子覆盖不足，实现者可以在配置中保守禁用该因子，但不得绕过验证门槛。硬验收要求 `validation_gate.csv` 中 `validation_status = PASS` 的启用评分因子数量至少为 `3`，避免通过禁用全部因子绕过综合评分逻辑。

## 输出文件

给定 `--output-dir`，至少生成：

```text
scoring_report.md
scored_candidates.csv
score_breakdown.csv
factor_normalized_scores.csv
hard_filter_exclusions.csv
validation_gate.csv
weight_sensitivity.csv
yearly_stability.csv
score_metadata.json
```

### `scored_candidates.csv`

固定列：

```text
rank
stock_code
stock_name
industry_l1
industry_l2
as_of_date
source_run_id
index_code
total_score
positive_score
financial_score
valuation_score
momentum_score
event_score
risk_penalty
hard_filter_passed
selection_reason
risk_tips
```

排序：

```text
ORDER BY rank ASC
```

`hard_filter_passed` 在候选表中保留用于审计，恒为 `true`。

### `score_breakdown.csv`

固定列：

```text
as_of_date
source_run_id
index_code
stock_code
score_group
group_enabled
group_required
group_weight
group_score
weighted_contribution
available_factor_weight
missing_factor_count
```

排序：

```text
ORDER BY stock_code, score_group
```

### `factor_normalized_scores.csv`

固定列：

```text
as_of_date
source_run_id
index_code
stock_code
factor_name
score_role
score_group
raw_factor_value
direction
normalized_score
factor_weight
weighted_contribution
validation_status
```

排序：

```text
ORDER BY stock_code, score_group, factor_name
```

### `validation_gate.csv`

固定列：

```text
factor_name
score_role
score_group
configured_enabled
validation_status
reason
required_horizons
coverage
valid_oriented_ic_dates
mean_oriented_rank_ic
oriented_icir
group_return_rows
```

排序：

```text
ORDER BY score_role, score_group, factor_name
```

### `weight_sensitivity.csv`

固定列：

```text
scenario_name
scenario_type
changed_key
change_direction
change_pct
top_n
baseline_candidate_count
scenario_candidate_count
spearman_rank_corr
top_n_overlap_count
top_n_overlap_ratio
max_abs_rank_change
mean_abs_score_change
warning
```

排序：

```text
ORDER BY scenario_type, changed_key, change_direction
```

### `yearly_stability.csv`

固定列：

```text
year
horizon
signal_date_count
stock_observation_count
rank_ic_mean
rank_ic_std
rank_icir
top_bottom_spread_mean
positive_rank_ic_rate
status
warning
```

排序：

```text
ORDER BY year, horizon
```

### `score_metadata.json`

至少包含：

```text
generated_at
db_path
as_of_date
source_run_id
index_code
scoring_config_path
data_dictionary_path
validation_dir
config_hash
top_n
horizons
diagnostics_from
diagnostics_to
skip_diagnostics
enabled_groups
enabled_factors
enabled_risk_penalty_factors
warnings
```

## 权重敏感性测试

权重敏感性测试用于诊断综合评分对权重扰动是否过度敏感，不用于自动寻找最优权重。

固定规则：

- `scenario_type` 只允许：
  - `group_weight`
  - `factor_weight`
- `change_direction` 只允许：
  - `up`
  - `down`
- `baseline` 不单独写入 `weight_sensitivity.csv`；baseline 只作为内存对照。
- `change_pct` 使用 `configs/scoring.yaml.diagnostics.sensitivity.perturbation_pct`。
- `group_weight` 场景：
  - 对每个 enabled 且 weight > 0 的 score group 分别生成 up / down 两个场景。
  - `changed_key` 格式为 `groups.<group>.weight`。
  - 扰动目标 group 后，同一层级的其他 enabled group 权重必须等比重归一，使 group weight 总和仍为 `1.0`。
  - 如果没有其他 enabled group 可重归一，该场景输出 warning，不崩溃。
- `factor_weight` 场景:
  - 对每个 enabled group 内每个 enabled 且 weight > 0 的因子分别生成 up / down 两个场景。
  - `changed_key` 格式为 `groups.<group>.factors.<factor>.weight`。
  - 扰动目标 factor 后，同一 group 内其他 enabled factor 权重必须等比重归一，使组内因子权重总和仍为 `1.0`。
  - 如果该 group 内没有其他 enabled factor 可重归一，该场景输出 warning，不崩溃。
- 本 phase 不扰动 soft risk penalty 权重；风险扣分敏感性后续单独设计。
- 每个场景重新计算单日综合评分，并与 baseline 比较：
  - Spearman rank correlation。
  - Top N overlap count。
  - Top N overlap ratio。
  - max absolute rank change。
  - mean absolute score change。
- 候选数量不足 2 时，相关系数可为 `NaN`，但必须输出 warning，不崩溃。

## 分年度稳定性测试

分年度稳定性测试把 `total_score` 当作一个合成因子来验证，不验证每个组件子分。

固定口径：

- `signal_frequency: month_end` 表示 `trading_calendar` 中每个自然月最后一个开市交易日。
- signal date 范围来自 `--diagnostics-from` 到 `--diagnostics-to`。
- 每个 signal date 使用与单日 `score` 相同的因子读取口径：

```text
source_run_id = ?
trade_date = signal_date
as_of_date = signal_date
```

- 对每个 signal date 重新计算 `total_score`。
- 使用 Phase 1a-5 的 forward return label 口径构造未来收益标签。
- 对 `total_score` 与 future return 计算 Rank IC。
- Top / Bottom spread 使用 `total_score` 分组，不使用组件子分。
- 每个自然年单独聚合：
  - `rank_ic_mean`
  - `rank_ic_std`
  - `rank_icir`
  - `top_bottom_spread_mean`
  - `positive_rank_ic_rate`
- 如果某年 `signal_date_count < min_signal_dates_per_year`，输出：

```text
status = insufficient
```

并写明 warning，不崩溃。

- 正常年份输出：

```text
status = ok
```

- 本测试不调仓、不撮合、不计算交易成本、不输出持仓、不调用 Phase 1b 回测引擎。

## Markdown 报告

`scoring_report.md` 至少包含：

1. 标题。
2. 生成时间。
3. 数据库路径。
4. `as_of_date`。
5. `source_run_id`。
6. `index_code`。
7. 配置文件路径和配置哈希。
8. 验证报告目录。
9. 启用分组、分组权重和组内因子权重。
10. 验证门槛结果摘要。
11. 硬过滤排除摘要。
12. Top N 综合评分候选。
13. 每只候选的分组子分、软风险扣分和总分。
14. 权重敏感性测试摘要。
15. 分年度稳定性测试摘要。
16. warnings。
17. 口径说明：
    - 综合评分仅供研究，不是交易指令。
    - `score` 不替代 Phase 1a-6 的 `scan`；`scan` 是单因子候选清单，`score` 是多因子综合评分报告。
    - 只有通过验证门槛的因子进入总分。
    - hard filters 不参与连续打分。
    - soft risk penalty 是扣分项，不是交易卖出信号。
    - 本报告不是组合回测报告。
    - 本报告未接入 LLM 事件分。
    - 本报告不包含事件研究。

## 接口建议

### 配置

在 `src/ashare/scoring/config.py` 中提供：

```python
def load_scoring_config(config_path: str | Path = "configs/scoring.yaml") -> dict[str, object]:
    ...

def validate_scoring_config(config: Mapping[str, object]) -> None:
    ...

def enabled_scoring_factors(config: Mapping[str, object]) -> list[str]:
    ...
```

### 验证门槛

在 `src/ashare/scoring/validation_gate.py` 中提供：

```python
@dataclass(frozen=True)
class ValidationGateResult:
    eligible_factors: frozenset[str]
    table: pd.DataFrame
    warnings: tuple[str, ...] = ()

def load_validation_artifacts(validation_dir: str | Path) -> dict[str, pd.DataFrame]:
    ...

def evaluate_validation_gate(
    artifacts: Mapping[str, pd.DataFrame],
    scoring_config: Mapping[str, object],
    data_dictionary: Mapping[str, object],
) -> ValidationGateResult:
    ...
```

要求：

- `evaluate_validation_gate` 必须读取并使用 `ic_summary.csv` 的真实列名：
  - `valid_oriented_ic_dates`
  - `mean_oriented_rank_ic`
  - `oriented_icir`
- 不得在内部另造 `rank_ic_observations` 或 `oriented_rank_ic_mean` 等别名作为配置 key。
- 输出 `validation_gate.csv` 时也使用真实列名。

### 数据加载

在 `src/ashare/scoring/loaders.py` 中提供：

```python
def load_score_inputs(
    connection: duckdb.DuckDBPyConnection,
    as_of_date: DateLike,
    source_run_id: str,
    index_code: str,
    factor_names: Sequence[str],
    hard_filter_names: Sequence[str],
) -> pd.DataFrame:
    ...
```

要求：

- 读取时遵守本 goal 的 PIT 语义：`trade_date = as_of_date` 且 `factor_values.as_of_date = trade_date`。
- 对重复 `(source_run_id, stock_code, trade_date, as_of_date, factor_name)` fail-fast。
- 返回只包含同一 `score_date` universe 内股票的数据。

### 标准化

在 `src/ashare/scoring/normalization.py` 中提供：

```python
def normalize_factor_scores(
    factor_values: pd.DataFrame,
    data_dictionary: Mapping[str, object],
    scoring_config: Mapping[str, object],
) -> pd.DataFrame:
    ...
```

返回字段至少包含：

```text
stock_code
factor_name
raw_factor_value
direction
normalized_score
```

### 打分

在 `src/ashare/scoring/scorer.py` 中提供：

```python
@dataclass(frozen=True)
class CompositeScoreResult:
    scored_candidates: pd.DataFrame
    score_breakdown: pd.DataFrame
    factor_normalized_scores: pd.DataFrame
    hard_filter_exclusions: pd.DataFrame
    validation_gate: pd.DataFrame
    warnings: tuple[str, ...] = ()

def compute_composite_scores(
    connection: duckdb.DuckDBPyConnection,
    as_of_date: DateLike,
    source_run_id: str,
    index_code: str,
    scoring_config: Mapping[str, object],
    data_dictionary: Mapping[str, object],
    validation_gate: ValidationGateResult,
    top_n: int | None = None,
) -> CompositeScoreResult:
    ...
```

### 诊断

在 `src/ashare/scoring/diagnostics.py` 中提供：

```python
def run_weight_sensitivity(
    base_result: CompositeScoreResult,
    scoring_config: Mapping[str, object],
    top_n: int,
) -> pd.DataFrame:
    ...

def run_yearly_stability(
    connection: duckdb.DuckDBPyConnection,
    start_date: DateLike,
    end_date: DateLike,
    source_run_id: str,
    index_code: str,
    scoring_config: Mapping[str, object],
    data_dictionary: Mapping[str, object],
    validation_gate: ValidationGateResult,
    horizons: Sequence[int],
) -> pd.DataFrame:
    ...
```

规则：

- 权重敏感性测试只扰动本 goal 定义的 `group_weight` 和 `factor_weight`。
- 权重扰动后必须按本 goal 规则重归一化相关权重。
- 分年度稳定性测试必须把 `total_score` 作为一个合成因子。
- 分年度稳定性测试可以复用 Phase 1a-5 的 forward return label 和 Rank IC / 分组收益逻辑；不得复制出一套冲突口径。

### 报告

在 `src/ashare/reports/scoring_report.py` 中提供：

```python
def render_scoring_markdown(
    result: CompositeScoreResult,
    weight_sensitivity: pd.DataFrame,
    yearly_stability: pd.DataFrame,
    metadata: Mapping[str, object],
) -> str:
    ...

def write_scoring_report(
    result: CompositeScoreResult,
    output_dir: str | Path,
    metadata: Mapping[str, object],
    weight_sensitivity: pd.DataFrame | None = None,
    yearly_stability: pd.DataFrame | None = None,
    overwrite: bool = False,
) -> dict[str, Path]:
    ...
```

规则：

- 纯渲染函数不读写文件。
- 写文件函数只写入 `output_dir`。
- `overwrite=False` 且目标文件已存在时 fail-fast。
- 所有 CSV 按本 goal 的固定列顺序和排序键输出。
- Markdown 输出按本 goal 的固定章节顺序输出。

## CLI 要求

新增命令：

```text
ashare score
```

建议参数：

```text
--db-path              默认 data/processed/ashare.duckdb
--as-of                必填，ISO 日期
--source-run-id        必填，无默认值
--index-code           必填，例如 LOCAL_FIXTURE 或 000300.SH
--validation-dir       必填，Phase 1a-6 factor-validation 输出目录
--scoring-config       默认 configs/scoring.yaml
--data-dictionary      默认 configs/data_dictionary.yaml
--top                  可选，默认读取 configs/scoring.yaml，fallback 20
--diagnostics-from     可选，分年度稳定性测试起始日期
--diagnostics-to       可选，分年度稳定性测试结束日期
--horizon              逗号分隔，例如 5,20，默认读取 configs/scoring.yaml
--skip-diagnostics     默认 false
--output-dir           默认 data/reports/generated/phase3/scoring
--overwrite            默认 false
```

行为：

- 只读打开 DuckDB。
- 加载 scoring config 和 data dictionary。
- 加载 `--validation-dir` 验证报告。
- 执行验证门槛。
- strict 模式下，任一启用评分因子未通过验证门槛时：
  - 写出 `validation_gate.csv`。
  - 写出包含错误摘要的 `score_metadata.json`。
  - 不继续计算综合评分。
  - CLI 非 0 退出。
- 计算单日综合评分。
- 默认执行权重敏感性测试。
- 如果传入 `--diagnostics-from` 和 `--diagnostics-to`，执行分年度稳定性测试。
- 如果未传诊断区间且未显式 `--skip-diagnostics`，CLI 仍生成空 `yearly_stability.csv` 并打印 warning。
- 写出 Markdown / CSV / JSON 报告。
- 成功后打印输出文件路径、Top N 摘要、验证门槛摘要和 warnings。
- 明确打印：
  - `composite score is for research only and is not a trading instruction.`
  - `综合评分仅供研究复盘，不是交易指令。`
- 不写 DB。
- 不调用 AkShare。
- 不调用 LLM。
- 不调用 `backtest`。
- 不调用 `parse-announcements`。
- 不把评分结果写回 `factor_values`。

## Followups 更新

修改 `docs/planning/followups.md`，从现有 D37 后追加：

```text
D38 scoring 暂不写 research_runs 或 score table
D39 LLM event_score 需要事件研究验证后才能启用
D40 软风险因子尚未全部由因子层稳定落库
D41 scoring 暂不做行业中性化
D42 scoring 权重敏感性不是权重优化
D43 scoring 尚未接入正式 run 快照和数据版本审计
```

每条按现有 followups 格式记录：

```markdown
### Dxx. <债标题>

- 现状: ...
- 触发: ...
- 决策: ...
- 关联: ...
```

不得借本 phase 实现 D38-D43。

## 测试要求

新增或更新测试，至少覆盖：

1. `configs/scoring.yaml` 可以加载。
2. 配置版本必须为 `phase3.v1`。
3. 启用正向分组权重和必须为 `1.0`。
4. 组内启用因子权重和必须为 `1.0`。
5. 负权重配置 fail-fast。
6. 同一因子同时用于 hard filter 和 score group 时 fail-fast。
7. 同一因子同时用于 score group 和 risk penalty 时 fail-fast。
8. hard filter 不要求通过验证门槛。
9. 启用评分因子缺少数据字典定义时 fail-fast。
10. 启用评分因子缺少 direction 时 fail-fast。
11. 启用评分因子不在验证报告中时 fail-fast。
12. strict 模式下未通过验证门槛的因子导致 CLI 非 0 退出，并写出 `validation_gate.csv`。
13. 非 strict 模式下未通过因子不会进入评分，并写入 `validation_gate.csv`。
14. 验证门槛使用 `valid_oriented_ic_dates`、`mean_oriented_rank_ic`、`oriented_icir` 真实列名。
15. `higher_is_better` 标准化方向正确。
16. `lower_is_better` 标准化方向正确，必须覆盖 `pe_ttm_percentile`。
17. 单一有效观测标准化为 `50.0`。
18. 全部有效值相同标准化为 `50.0`。
19. tied value 使用平均 rank。
20. 标准化分全部在 `[0.0, 100.0]`。
21. 缺失因子不填 `0`。
22. `score` 读取因子时强制 `trade_date = as_of_date`。
23. `score` 与 `scan` 对同一 `source_run_id`、同一 `as_of_date` 的基础因子输入口径一致。
24. hard filter 缺失时保守排除股票。
25. hard filter 非 `0.0` 时排除股票。
26. 被硬过滤排除的股票不参与标准化。
27. `hard_filter_exclusions.csv` 固定列和排序正确。
28. `required: true` 分组有效因子权重不足时，股票不能进入最终评分。
29. 组内缺失因子按可用权重重新归一化。
30. 分组子分全部在 `[0.0, 100.0]`。
31. `positive_score` 计算正确。
32. 软风险扣分方向正确。
33. 软风险扣分按可用风险因子权重重新归一化。
34. 软风险扣分不超过 `max_penalty`。
35. 没有软风险因子时 `risk_penalty = 0.0` 并产生 warning。
36. `total_score = positive_score - risk_penalty` 且 clamp 到 `[0.0, 100.0]`。
37. 排名按 `total_score DESC, stock_code ASC`。
38. `scored_candidates.csv.hard_filter_passed` 在候选行中恒为 `true`。
39. `selection_reason` 包含综合评分、主要子分和硬过滤通过说明。
40. `risk_tips` 包含软风险扣分和缺失因子提示。
41. 重复 `(source_run_id, stock_code, trade_date, as_of_date, factor_name)` 会 fail-fast。
42. `factor_normalized_scores.csv` 固定列和排序正确。
43. `score_breakdown.csv` 固定列和排序正确。
44. `scored_candidates.csv` 固定列和排序正确。
45. `validation_gate.csv` 固定列和排序正确。
46. 权重敏感性测试生成 baseline 以外的扰动场景。
47. 权重敏感性测试 `scenario_type` 只包含 `group_weight` 和 `factor_weight`。
48. 权重敏感性测试 `change_direction` 只包含 `up` 和 `down`。
49. 权重敏感性测试扰动后相关层级权重重新归一到 `1.0`。
50. 权重敏感性测试输出 Spearman rank correlation、Top N overlap 和 score delta。
51. 候选数量不足 2 时，敏感性测试不崩溃并输出 warning。
52. 分年度稳定性测试把 `total_score` 作为合成因子。
53. 分年度稳定性测试 month-end 定义为每个自然月最后一个开市交易日。
54. 分年度稳定性测试按年份和 horizon 输出。
55. 分年度稳定性测试不调用回测撮合逻辑。
56. 分年度稳定性测试输出 insufficient 年份状态。
57. `render_scoring_markdown` 缺少必需 metadata key 时 fail-fast。
58. `write_scoring_report` 写出 1 个 Markdown、7 个 CSV 和 1 个 JSON。
59. `score_metadata.json` 包含 `horizons`、`diagnostics_from`、`diagnostics_to`、`skip_diagnostics`。
60. `overwrite=False` 且目标文件存在时 fail-fast。
61. Markdown 报告包含验证门槛、硬过滤、Top N、子分、软扣分、敏感性、年度稳定性和研究用途说明。
62. `ashare score ...` 可以成功生成报告。
63. `ashare score` 不写入 DuckDB。
64. `ashare score` 不新增 `factor_values` 行。
65. `ashare score` 不读取 LLM parse 表参与评分。
66. event group 默认禁用。
67. event group 启用但没有通过验证因子时 fail-fast。
68. 默认验收配置下 `validation_status = PASS` 的启用评分因子数量至少为 `3`。
69. `docs/planning/followups.md` 包含 D38-D43。
70. `ashare --help` 能看到 `score`，同时前置命令仍存在：

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
ingest-announcements
parse-announcements
score
```

测试数据必须通过 fixture builder、`ingest_local`、`calculate-factors` 和 `report factor-validation` 在 `tmp_path` 下构造，不依赖仓库内已有 DuckDB 文件。

## 验收命令

以下命令必须全部成功：

```bash
conda run -n ashare-research-lab python -m pip install -e .
```

```bash
rm -f data/processed/ashare_phase3.duckdb
```

```bash
conda run -n ashare-research-lab ashare ingest-local \
  --input-dir tests/fixtures/generated \
  --db-path data/processed/ashare_phase3.duckdb
```

```bash
conda run -n ashare-research-lab ashare calculate-factors \
  --from 2026-03-30 \
  --to 2026-06-26 \
  --db-path data/processed/ashare_phase3.duckdb \
  --index-code LOCAL_FIXTURE \
  --source-run-id phase3-scoring
```

```bash
conda run -n ashare-research-lab ashare report \
  --kind factor-validation \
  --from 2026-03-30 \
  --to 2026-06-26 \
  --db-path data/processed/ashare_phase3.duckdb \
  --source-run-id phase3-scoring \
  --factor return_20d \
  --factor return_60d \
  --factor above_ma60 \
  --factor pe_ttm_percentile \
  --factor pb_percentile \
  --factor revenue_yoy \
  --factor profit_yoy \
  --horizon 5,20 \
  --output-dir data/reports/generated/phase3/factor-validation \
  --overwrite
```

```bash
conda run -n ashare-research-lab ashare score \
  --as-of 2026-06-26 \
  --db-path data/processed/ashare_phase3.duckdb \
  --source-run-id phase3-scoring \
  --index-code LOCAL_FIXTURE \
  --validation-dir data/reports/generated/phase3/factor-validation \
  --diagnostics-from 2026-03-30 \
  --diagnostics-to 2026-06-26 \
  --horizon 5,20 \
  --top 3 \
  --output-dir data/reports/generated/phase3/scoring \
  --overwrite
```

```bash
conda run -n ashare-research-lab python - <<'PY'
from pathlib import Path
import json
import pandas as pd

out = Path("data/reports/generated/phase3/scoring")
expected = {
    "scoring_report.md",
    "scored_candidates.csv",
    "score_breakdown.csv",
    "factor_normalized_scores.csv",
    "hard_filter_exclusions.csv",
    "validation_gate.csv",
    "weight_sensitivity.csv",
    "yearly_stability.csv",
    "score_metadata.json",
}
missing = [name for name in expected if not (out / name).exists()]
assert not missing, f"missing scoring files: {missing}"

candidates = pd.read_csv(out / "scored_candidates.csv")
breakdown = pd.read_csv(out / "score_breakdown.csv")
normalized = pd.read_csv(out / "factor_normalized_scores.csv")
gate = pd.read_csv(out / "validation_gate.csv")
sensitivity = pd.read_csv(out / "weight_sensitivity.csv")
yearly = pd.read_csv(out / "yearly_stability.csv")
metadata = json.loads((out / "score_metadata.json").read_text(encoding="utf-8"))

expected_candidate_cols = {
    "rank", "stock_code", "stock_name", "industry_l1", "industry_l2",
    "as_of_date", "source_run_id", "index_code", "total_score",
    "positive_score", "financial_score", "valuation_score",
    "momentum_score", "event_score", "risk_penalty",
    "hard_filter_passed", "selection_reason", "risk_tips",
}
assert expected_candidate_cols.issubset(candidates.columns)

expected_breakdown_cols = {
    "as_of_date", "source_run_id", "index_code", "stock_code",
    "score_group", "group_enabled", "group_required", "group_weight",
    "group_score", "weighted_contribution", "available_factor_weight",
    "missing_factor_count",
}
assert expected_breakdown_cols.issubset(breakdown.columns)

expected_normalized_cols = {
    "as_of_date", "source_run_id", "index_code", "stock_code",
    "factor_name", "score_role", "score_group", "raw_factor_value",
    "direction", "normalized_score", "factor_weight",
    "weighted_contribution", "validation_status",
}
assert expected_normalized_cols.issubset(normalized.columns)

expected_gate_cols = {
    "factor_name", "score_role", "score_group", "configured_enabled",
    "validation_status", "reason", "required_horizons", "coverage",
    "valid_oriented_ic_dates", "mean_oriented_rank_ic", "oriented_icir",
    "group_return_rows",
}
assert expected_gate_cols.issubset(gate.columns)
assert "rank_ic_observations" not in gate.columns
assert "oriented_rank_ic_mean" not in gate.columns

passed_enabled = gate[
    (gate["configured_enabled"] == True) & (gate["validation_status"] == "PASS")
]
assert len(passed_enabled) >= 3, "expected at least 3 enabled PASS scoring factors"

if not candidates.empty:
    assert len(candidates) <= 3
    assert candidates["rank"].tolist() == sorted(candidates["rank"].tolist())
    assert candidates["total_score"].between(0.0, 100.0).all()
    assert candidates["positive_score"].between(0.0, 100.0).all()
    assert (candidates["risk_penalty"] >= 0.0).all()
    assert candidates["hard_filter_passed"].eq(True).all()

if not normalized.empty:
    assert normalized["normalized_score"].between(0.0, 100.0).all()

assert not sensitivity.empty, "weight_sensitivity should not be empty"
assert set(sensitivity["scenario_type"].dropna()).issubset({"group_weight", "factor_weight"})
assert set(sensitivity["change_direction"].dropna()).issubset({"up", "down"})
assert {"year", "horizon", "status"}.issubset(yearly.columns)

assert metadata["as_of_date"] == "2026-06-26"
assert metadata["source_run_id"] == "phase3-scoring"
assert metadata["index_code"] == "LOCAL_FIXTURE"
for key in ["horizons", "diagnostics_from", "diagnostics_to", "skip_diagnostics"]:
    assert key in metadata, f"missing metadata key: {key}"

text = (out / "scoring_report.md").read_text(encoding="utf-8")
assert "综合评分" in text
assert "验证门槛" in text
assert "硬过滤" in text
assert "权重敏感性" in text
assert "分年度" in text
assert "不是交易指令" in text or "not a trading instruction" in text
print("OK phase3 scoring artifacts")
PY
```

严格门槛失败路径也必须验收。下面这个命令块整体应成功，但其中 `ashare score` 必须按预期非 0 退出：

```bash
mkdir -p data/reports/generated/phase3

conda run -n ashare-research-lab python - <<'PY'
from pathlib import Path
import yaml

base = Path("configs/scoring.yaml")
out = Path("data/reports/generated/phase3/scoring_strict_fail.yaml")
config = yaml.safe_load(base.read_text(encoding="utf-8"))
config["validation_gate"]["mode"] = "strict"
config["validation_gate"]["min_mean_oriented_rank_ic"] = 999.0
out.write_text(yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding="utf-8")
print(out)
PY

set +e
conda run -n ashare-research-lab ashare score \
  --as-of 2026-06-26 \
  --db-path data/processed/ashare_phase3.duckdb \
  --source-run-id phase3-scoring \
  --index-code LOCAL_FIXTURE \
  --validation-dir data/reports/generated/phase3/factor-validation \
  --scoring-config data/reports/generated/phase3/scoring_strict_fail.yaml \
  --diagnostics-from 2026-03-30 \
  --diagnostics-to 2026-06-26 \
  --horizon 5,20 \
  --top 3 \
  --output-dir data/reports/generated/phase3/scoring-strict-fail \
  --overwrite
status=$?
set -e

if [ "$status" -eq 0 ]; then
  echo "expected strict validation gate failure, got success"
  exit 1
fi

conda run -n ashare-research-lab python - <<'PY'
from pathlib import Path
import pandas as pd

gate_path = Path("data/reports/generated/phase3/scoring-strict-fail/validation_gate.csv")
assert gate_path.exists(), "strict failure must write validation_gate.csv"
gate = pd.read_csv(gate_path)
assert not gate.empty, "validation_gate.csv should not be empty"
assert (gate["validation_status"] != "PASS").any(), "expected at least one failed gate row"
print("OK strict validation gate failure path")
PY
```

```bash
conda run -n ashare-research-lab python - <<'PY'
from pathlib import Path

text = Path("docs/planning/followups.md").read_text(encoding="utf-8")
required = [
    "D38",
    "D39",
    "D40",
    "D41",
    "D42",
    "D43",
    "research_runs",
    "event_score",
    "软风险因子",
    "行业中性化",
    "权重优化",
    "数据版本审计",
]
missing = [item for item in required if item not in text]
assert not missing, f"followups.md missing: {missing}"
print("OK followups D38-D43")
PY
```

```bash
conda run -n ashare-research-lab pytest -q
```

```bash
conda run -n ashare-research-lab ashare --help
```

## 完成后

1. 运行 `git status`，确认只包含 Phase 3 相关代码、测试、配置和必要文档改动。
2. 确认未提交：
   - `data/reports/generated/`
   - `data/processed/*.duckdb`
   - `tests/fixtures/generated/`
   - `data/raw/announcements/`
   - 任何缓存或生成产物
3. 执行 `git add .`。
4. 执行：

```bash
git commit -m "feat: phase 3 composite scoring"
```

5. 最终回复说明：
   - 修改了哪些文件。
   - 因子如何通过验证门槛。
   - 因子如何标准化到 `0-100`。
   - hard filter 如何排除股票。
   - 分组子分和总分如何计算。
   - soft risk penalty 如何计算。
   - 权重敏感性测试如何生成。
   - 分年度稳定性测试如何生成。
   - 输出了哪些 Markdown / CSV / JSON。
   - 如何保证没有未验证因子进入综合评分。
   - 如何保证 LLM 输出没有直接进入评分。
   - followups 是否追加 D38-D43。
   - 验收命令是否全部通过。
   - commit hash。
   - 是否发现 plan 或前置 phase 的新缺口。

## 不要实现

- 不实现新因子。
- 不从 `daily_prices`、`fundamental_reports`、`risk_events` 原表临时计算评分因子。
- 不重新计算 Phase 1a-4 因子。
- 不重新实现 Phase 1a-5 单因子验证。
- 不新增验证指标来替代前置验证层。
- 不把未验证因子纳入总分。
- 不把 hard filter 当连续因子打分。
- 不把同一风险同时作为 hard filter 和 soft penalty。
- 不实现事件研究。
- 不实现 LLM 事件分。
- 不直接读取 LLM 解析结果参与总分。
- 不把 LLM 输出写入 `factor_values`。
- 不调用真实 LLM。
- 不调用 AkShare。
- 不实现组合回测、调仓、撮合、交易成本、持仓或净值曲线。
- 不实现权重优化、参数搜索、网格搜索或 walk-forward 优化。
- 不实现行业中性化，除非只保留禁用配置和 followup。
- 不实现风格归因。
- 不实现 Web / FastAPI / 前端。
- 不实现定时任务或推送。
- 不写入 `research_runs`。
- 不新增 DuckDB 表。
- 不修改 DuckDB schema。
- 不把综合评分报告描述为买入、卖出或交易指令。

## 发现的缺口

- 当前 `docs/planning/followups.md` 中 D37 已被 Phase 2 的 OpenAI-compatible LLM client 工程债占用；Phase 3 新增 followups 必须从 D38 开始。
- Phase 2 明确不实现事件研究验证，也不把 LLM 输出写入 `factor_values`；因此 Phase 3 不能启用 `event_score`，只能保留禁用配置位。
- Plan 第 14 节提到 LLM 事件分经过事件研究验证后才可启用，但当前尚无事件研究结果表或事件验证报告格式；本 phase 不补这个缺口。
- Plan 中列出的多个软风险因子尚未由前置因子层稳定落库；本 phase 只能实现软风险扣分框架，不能凭空从原表计算这些因子。
- Phase 1a-5 / 1a-6 的验证报告没有显式 `pass/fail` 字段；本 phase 需要根据 `configs/scoring.yaml.validation_gate` 从 CSV 中计算 `validation_status` 并输出 `validation_gate.csv`。
- Phase 1a-5 的 `ic_summary.csv` 已有真实列名 `valid_oriented_ic_dates`、`mean_oriented_rank_ic`、`oriented_icir`；本 phase 不应引入 `rank_ic_observations` 或 `oriented_rank_ic_mean` 等新同义字段。
- 目前仍不写 `research_runs`，与 plan 中正式运行审计要求有差距；本 phase 继续以文件产物保存，并在 followups 中登记。
