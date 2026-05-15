# Phase 1a-4.5 Goal: 文档单一事实源与工程债登记

请在已完成 Phase 1a-4 的 `/Users/crazy/own_project/ashare-research-lab` 仓库中继续实现 Phase 1a-4.5：文档单一事实源与工程债登记。

本 phase 不实现新业务逻辑、不动 schema、不动 PIT 查询层、不动 ingest。
本 phase 只做三件事：

1. 把 Phase 1a-4 的口径决策回写到 `docs/planning/a-share-research-plan.md`，让 plan 重新成为单一事实源。
2. 把 Phase 1a-4 已实现的 11 个因子定义补齐到 `configs/data_dictionary.yaml`，并让 `docs/data_dictionary.md` / `docs/factor_definitions.md` 由脚本自动生成；加一致性测试，禁止再手写维护这两份 Markdown。
3. 建立 `docs/planning/followups.md`，登记前置 phase 已识别但本系列 phase 暂不解决的工程债，记录现状、触发条件与决策方向。

## 背景问题

Phase 1a-4 完成后，研究系统的代码层已经能算出基础因子。但文档层和 plan 层落后于代码，存在三类漂移：

- Phase 1a-4 在因子口径上做出了若干默认决策（`low_liquidity` 阈值、`pe/pb_percentile` 分位口径、`return_N` 观测窗口语义、`is_suspended` 二义性、复权近似价口径），这些决策只存在于 phase 1a-4 goal 中，没有回写到 plan，会让后续 phase 实现者重新争论或写出冲突的口径。
- `configs/data_dictionary.yaml` 仍是早期 `fields` 单层结构，只覆盖少量因子定义，缺少 `schema_fields` / `factors` 顶层拆分、schema 字段定义、`params`、`phase`、`score_group` 等信息。`docs/factor_definitions.md` 仍是空骨架，`docs/data_dictionary.md` 也未覆盖 schema 字段。Phase 1a-5 的因子验证报告需要从数据字典抓因子方向、缺失策略、是否硬过滤和参数口径，没有定义就无法继续。
- 前置 phase 累积了多条工程债（如 `factor_values` 无唯一键、`schema_version` 不演进、`effective_date` 不区分盘前盘中、`ingest_local` 清表重写等），目前散落在 phase goal 文档与代码注释中，没有集中登记。后续 phase 容易遗漏或重复识别。

本 phase 一次性把这三类漂移修齐。

## 工作约束

- 严格遵守 `docs/planning/a-share-research-plan.md`。
- 所有 Python 命令必须在 Conda 环境 `ashare-research-lab` 中执行。
- 本 phase 不实现新因子。
- 本 phase 不写入 `factor_values` 或 `research_runs`。
- 本 phase 不动 `src/ashare/storage/schema.sql`、不动 `src/ashare/storage/db.py`、不动 `src/ashare/pit/`、不动 `src/ashare/ingest/`、不动 `src/ashare/factors/`（除非纯属修复 docstring 拼写）。
- 本 phase 不实现 CI、pre-commit 或 lint hooks。
- 本 phase 不接真实 AkShare 数据，不调用 LLM。
- 本 phase 不实现 `schema_version` 真实迁移序列；该项登记进 followups。
- 本 phase 完成后单独 commit。
- 提交信息为：`docs: phase 1a-4.5 documentation single source of truth`

## 范围

允许新增或修改的文件：

```text
docs/planning/a-share-research-plan.md
docs/planning/followups.md            # 新建
configs/data_dictionary.yaml
configs/factors.yaml                  # 仅在需要补 phase 字段时
docs/data_dictionary.md               # 由脚本生成
docs/factor_definitions.md            # 由脚本生成
docs/build_data_dictionary.py
tests/test_data_dictionary_consistency.py   # 新建
tests/test_followups.py                     # 新建
```

不允许修改：

```text
src/**                  # 全部
tests/test_*.py 中除新增两个文件以外的其他文件
configs/backtest.yaml / scoring.yaml / validation.yaml / llm.yaml / universe.yaml / data.yaml
docs/backtest_assumptions.md
```

例外：如 phase 1a-4 落地后 `configs/factors.yaml` 中某些字段与 plan / data_dictionary 表述不一致，允许本 phase 只做对齐式编辑（补 description 或 phase 字段），不得改业务参数（`window_days`、`min_avg_amount`、`min_observations` 等）。

## Plan 决策回写

修改 `docs/planning/a-share-research-plan.md`。

### 第 9 节：因子层设计

在因子表前后插入 Phase 1a-4 决策的明确说明，以下口径必须出现在 plan 正文，不得只留在 phase goal：

1. **复权口径**：动量类因子统一使用后复权近似价 `adjusted_close = close * adj_factor`；`adj_factor` 为空时 fallback 到 `close`。该规则由 phase 1a-4 落地，写入 plan。
2. **`return_N` 观测窗口语义**：明确 `return_20d` / `return_60d` 使用单股票 `daily_prices` 已 PIT 可见的观测行偏移（`shift(N)`），不使用 `trading_calendar` 日历偏移。停牌日如果存在 `daily_prices` 行仍计为一个观测。
3. **`above_ma60` 窗口语义**：使用最近 60 个有效价格观测的均值，少于 60 个观测时不写入。
4. **`pe_ttm_percentile` / `pb_percentile` 分位口径**：原始因子层使用单股票历史滚动分位（trailing 252 个交易日，最少 20 个有效观测），不是横截面分位。横截面排名留给第 10 节标准化层。
5. **`low_liquidity` 默认阈值**：20 个交易日均成交额低于 50,000,000 元判定为低流动性；阈值与窗口在 `configs/factors.yaml` 中可配置。
6. **`is_suspended` 二义性**：`is_suspended = 1.0` 在 MVP 下含义为不可交易，覆盖真实停牌与当日 `daily_prices` 缺失两种场景；后续如需区分，应引入独立 `data_missing` 字段，已登记到 followups。
7. **财务因子修订选择**：`revenue_yoy` / `profit_yoy` 在同一 `(stock_code, report_period)` 多条可见记录中选择 `publish_time` 最新一条；该规则只作用于因子计算阶段，不下放到 PIT 查询层。
8. **同期基准严格匹配**：财务同比的同期基准使用 `(year - 1, month, day)` 严格相等，不向最近季度末或最近披露日回退；不存在严格匹配则视为基准缺失，不写入。

### 第 10 节：因子标准化

在节首加一段说明，明确两层 percentile 的关系：

> 第 9 节中的 `pe_ttm_percentile`、`pb_percentile`、`ps_percentile` 是**单股票历史分位**，由因子层在原始因子计算阶段产出，输出范围 `0.0` 到 `1.0`。第 10 节描述的横截面 percentile rank 是**综合打分前的标准化**，在打分层产出，输出 `0`–`100` 子分。两者不是同一层，标准化阶段不应再对 `*_percentile` 因子做二次 percentile，而应直接将其纳入横截面排序或在文档中说明跳过原因。

### 第 9 节：因子表 phase 归属

为 plan 第 9 节列出的所有因子（含硬过滤、软扣分）补 `phase:` 字段，明确归属。建议格式：

```text
- revenue_yoy            phase: 1a-4
- profit_yoy             phase: 1a-4
- roe                    phase: 1a-5
- gross_margin_change    phase: 1a-5
- operating_cashflow_to_profit  phase: 1a-5
- debt_ratio             phase: 1a-5

- pe_ttm_percentile      phase: 1a-4
- pb_percentile          phase: 1a-4
- ps_percentile          phase: 1a-5
- dividend_yield         phase: 1a-5

- return_20d             phase: 1a-4
- return_60d             phase: 1a-4
- above_ma60             phase: 1a-4
- relative_strength_vs_index   phase: 1a-5
- volume_breakout        phase: 1a-5

- is_st                  phase: 1a-4
- is_suspended           phase: 1a-4
- is_delisted            phase: 1a-4
- low_liquidity          phase: 1a-4

- pledge_ratio           phase: 2 或 3（待 risk_events ingest 落地）
- inquiry_letter_count   phase: 2 或 3
- recent_big_shareholder_reduce   phase: 2 或 3
- non_standard_audit_count        phase: 2 或 3
- goodwill_to_equity     phase: 1a-5 或 3
- receivable_growth_abnormal      phase: 1a-5 或 3
- inventory_growth_abnormal       phase: 1a-5 或 3
```

具体 phase 归属如有疑义，本 phase 实施者必须在 commit 描述中显式说明判断理由。允许保守标记为 `phase: TBD`，但 1a-4 已实现的 11 个因子必须明确标 `phase: 1a-4`。

### 第 17 节：configs/factors.yaml 示例同步

把第 17 节中 `configs/factors.yaml` 的示例代码块替换为 phase 1a-4 落地后的真实结构，包含 `factors.*.params` 与 `hard_filters.*.params`。要求示例与本仓库实际 `configs/factors.yaml` 内容字段对齐，不必逐键复制全部因子，但 `pe_ttm_percentile`、`low_liquidity` 至少要展示 `params` 子结构。

## 数据字典补齐

`configs/data_dictionary.yaml` 必须从空骨架补齐到能驱动 phase 1a-5 验证报告。本 phase 至少补：

### Schema 字段

为以下表的关键字段写出数据字典条目，每个字段至少包含 `type`、`source`、`description`、`unit`、`pit_visibility`：

```text
daily_prices.adj_factor
daily_prices.is_suspended
daily_prices.amount
valuation_daily.pe_ttm
valuation_daily.pb
fundamental_reports.revenue
fundamental_reports.net_profit
fundamental_reports.publish_time
fundamental_reports.effective_date
securities.delist_date
securities.delist_publish_time
securities.delist_effective_date
universe_members.in_effective_date
universe_members.out_effective_date
st_status.in_effective_date
st_status.out_effective_date
industry_classifications.in_effective_date
industry_classifications.out_effective_date
factor_values.factor_value
factor_values.as_of_date
factor_values.source_run_id
```

### 11 个 phase 1a-4 因子

每个因子至少包含以下键：

```text
factor_name
type: factor 或 hard_filter
source           # 数据来源表
raw_fields       # 原始字段列表
formula          # 公式
unit             # ratio / boolean / yuan / percentile_0_1
frequency        # daily / report_period
effective_date   # 生效时间规则
direction        # higher_is_better / lower_is_better / boolean_filter
missing          # 缺失值处理
outlier          # 极值处理（本 phase 因子大多不做，可写 none）
normalize        # 标准化方式（原始因子层一般 none）
hard_filter      # true / false
soft_penalty     # true / false
score_group      # financial / valuation / momentum / risk
phase            # 1a-4
description      # 含义说明，对 is_suspended 必须写出二义性
params           # 与 configs/factors.yaml 对齐
```

`is_suspended` 的 `description` 必须显式说明：`is_suspended = 1.0` 含义为不可交易，覆盖真实停牌与当日 `daily_prices` 行缺失两种场景；后续 phase 如需区分应引入独立 `data_missing` 字段。

`pe_ttm_percentile` / `pb_percentile` 的 `description` 必须显式说明这是单股票历史滚动分位，不是横截面分位。

`return_20d` / `return_60d` / `above_ma60` 的 `description` 必须显式说明使用 `daily_prices` 观测行偏移而非 `trading_calendar` 偏移。

数据字典 yaml 顶层结构：

```yaml
schema_fields:
  daily_prices.adj_factor:
    type: column
    source: daily_prices
    description: ...
    unit: ratio
    pit_visibility: trade_date <= as_of_date
  ...

factors:
  return_20d:
    type: factor
    ...
  ...
```

## 文档生成脚本扩展

修改 `docs/build_data_dictionary.py`：

1. 读取 `configs/data_dictionary.yaml` 顶层 `schema_fields` 与 `factors` 两个 section。
2. 生成 `docs/data_dictionary.md`，按字母序输出全部 `schema_fields` 与全部 `factors`，每条字段使用一个二级标题。
3. 生成 `docs/factor_definitions.md`，只输出 `type: factor` 和 `type: hard_filter` 的条目，按 `score_group` 分组、组内按字母序排序，每条使用一个三级标题。
4. 两份 Markdown 文件头部都必须含一行说明：

```text
This file is generated from configs/data_dictionary.yaml by docs/build_data_dictionary.py.
Do not edit by hand.
```

5. 脚本必须支持以模块方式调用：`python -m docs.build_data_dictionary` 或 `python docs/build_data_dictionary.py`。
6. 脚本必须暴露纯渲染函数，便于测试不写临时文件也能做字节级一致性检查：

```python
def render_data_dictionary(config: dict[str, object]) -> str: ...
def render_factor_definitions(config: dict[str, object]) -> str: ...
```

7. CLI / `main()` 路径不得读取或写入除上述 3 个路径以外的任何文件。
8. 纯渲染函数不得读写文件。
9. 脚本不得依赖 `src/ashare/` 中的代码，避免循环依赖。

## 一致性测试

### `tests/test_data_dictionary_consistency.py`

至少覆盖：

1. `configs/data_dictionary.yaml` 可被 `yaml.safe_load` 正确解析。
2. `schema_fields` 与 `factors` 两个 section 同时存在。
3. Phase 1a-4 落地的 11 个因子全部出现在 `factors`，且 `phase` 字段值为 `1a-4`。
4. 11 个因子的 `direction` 字段值在 `{higher_is_better, lower_is_better, boolean_filter}` 集合中。
5. 11 个因子的 `params` 字段与 `configs/factors.yaml` 中对应位置完全相等。测试必须读取两份 YAML 实际内容并对比，禁止把数值二次硬编码进测试。对齐路径：
    - `return_20d` 对齐 `configs.factors.return_20d.params`
    - `return_60d` 对齐 `configs.factors.return_60d.params`
    - `above_ma60` 对齐 `configs.factors.above_ma60.params`
    - `pe_ttm_percentile` 对齐 `configs.factors.pe_ttm_percentile.params`
    - `pb_percentile` 对齐 `configs.factors.pb_percentile.params`
    - `revenue_yoy` 对齐 `configs.factors.revenue_yoy.params`
    - `profit_yoy` 对齐 `configs.factors.profit_yoy.params`
    - `low_liquidity` 对齐 `configs.hard_filters.low_liquidity.params`
    - `is_st` 对齐 `configs.hard_filters.is_st.params`
    - `is_suspended` 对齐 `configs.hard_filters.is_suspended.params`
    - `is_delisted` 对齐 `configs.hard_filters.is_delisted.params`
6. `is_suspended.description` 必须包含「不可交易」「daily_prices」「data_missing」三个关键词。
7. `pe_ttm_percentile.description` 与 `pb_percentile.description` 必须包含「单股票」「历史」「分位」「不是横截面」四个关键词。
8. `docs/data_dictionary.md` 与 `docs/factor_definitions.md` 是 `docs/build_data_dictionary.py` 的当前生成产物：测试读取 `configs/data_dictionary.yaml`，调用脚本暴露的纯渲染函数生成字符串，再与仓库内 Markdown 字节级对比，不一致即 fail。
9. 两份 Markdown 头部必须含 "Do not edit by hand"。

### `tests/test_followups.py`

至少覆盖：

1. `docs/planning/followups.md` 文件存在。
2. 文件不为空。
3. 至少包含以下小节标题（在文件中以 Markdown 标题形式出现，不限层级）：
    - `## 高优先`（或同义中文，如「数据正确性」）
    - `## 中优先`（或同义中文，如「工程债」）
    - `## 低优先`（或同义中文，如「基础设施」）
4. 每条债务条目必须同时包含「现状」「触发」「决策」三个关键词中的至少两个，确保不只是 TODO 占位。
5. 至少登记下列条目（按其出现的关键字检索）：
    - `effective_date`（盘前 / 盘中 / 盘后）
    - `factor_values`（唯一键 / PRIMARY KEY）
    - `schema_version`（迁移序列 / 演进）
    - `ingest_local`（清表 / 真实数据）
    - `JSON extension`（fail-fast）
    - `is_suspended`（data_missing）
    - `test_asof`（硬编码日期）
    - `pre-commit`（或 `lint hook`）
    - `data/raw`（空目录 / .gitkeep）

## followups.md 内容要求

`docs/planning/followups.md` 是工程债登记簿，不是 TODO 列表。每条条目必须严格按以下结构：

```markdown
### Dxx. <债标题>

- 现状: <一句话陈述当前实现妥协或缺口，引用具体文件路径或函数>
- 触发: <什么 phase / 条件 / 上线动作会让这条债产生实际伤害>
- 决策: <已经达成共识的修法方向，或明确写「待 phase 1a-Y 决策」>
- 关联: <可选，引用相关 phase goal 编号或 plan 章节>
```

至少登记下列 12 条（编号沿用本系列 phase 讨论中已使用的 `D` 系列，便于回溯；在 followups 内部第一次出现 D 编号时给出简短脚注，说明这是来自 phase 1a-4.5 review 中的工程债扫描）：

```text
D1  effective_date 不区分盘前 / 盘中 / 盘后
D2  factor_values 无唯一键
D3  fundamental 同期基准与 trading_calendar 起点的张力（如 phase 1a-4 实施后已修则标记已闭环）
D4  is_suspended = 1.0 二义性
D5  schema_version 不演进
D6  ingest_local 是清表重写，不能用于真实数据
D7  init_db JSON extension 异常字符串匹配
D8  ingest_local._load_json_extension_if_available 静默吞错
D9  test_asof 硬编码具体日期，与 fixture 长度耦合
D13 无 CI 配置
D14 无 pre-commit / lint hook
D15 data/raw、data/snapshots 是空目录但无 .gitkeep
```

`D3` 在 phase 1a-4 实际实施过程中可能已经通过扩展 fixture 主样本交易日长度或补充 pre-history 解决；本 phase 实施者应先检查 `src/ashare/fixtures/builder.py` 的最终实现，已闭环则在 followups 中标记为已解决并保留条目（不要删除，删除会丢失审计线索）。

`D10`（plan 因子表 phase 归属）与 `D11`（数据字典空骨架）由本 phase 直接解决，不进 followups。

CI / pre-commit（D13、D14）虽然不进本 phase 实现，但必须在 followups 中登记；否则后续 phase 实施者不会自然意识到。

## Plan 文档同步检查

修改 `docs/planning/a-share-research-plan.md` 时遵守：

- 不重写整个 plan。
- 不提前写 phase 1a-5 / 1b / 2 / 3 / 4 的具体内容。
- 第 9 节、第 10 节、第 17 节以外原则上不动。
- 例外：允许在第 21 节关键风险末尾只增加一行 `followups.md` 指向；如果不动第 21 节，则必须在第 9 节末尾增加该指向。
- Plan 中保留对 followups.md 的一处指向，例如：

```text
已识别但不在 phase 1a-4 / 1a-4.5 解决的工程债集中登记于 docs/planning/followups.md。
```

## CLI 要求

本 phase 不新增 CLI 命令。

`ashare --help` 在本 phase 完成后必须仍包含与 phase 1a-4 完成时相同的命令清单：

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

## 测试要求

新增测试：

```text
tests/test_data_dictionary_consistency.py
tests/test_followups.py
```

已有测试不得修改业务断言。允许的修改仅限：

- 如某既有测试因数据字典 yaml 现在非空导致原本依赖 `fields == {}` 的断言失败，可改为「至少包含 schema_fields 与 factors 两个 key」之类的最小迁移。
- 不允许借机重写其他测试。

## 验收命令

以下命令必须全部成功：

```bash
conda run -n ashare-research-lab python -m pip install -e .
```

```bash
conda run -n ashare-research-lab python docs/build_data_dictionary.py
```

执行后 `git status` 必须显示 `docs/data_dictionary.md` 与 `docs/factor_definitions.md` 没有未提交差异（即仓库内的 Markdown 已是脚本最新生成产物）。

```bash
conda run -n ashare-research-lab pytest -q
```

```bash
conda run -n ashare-research-lab ashare --help
```

```bash
conda run -n ashare-research-lab python - <<'PY'
import yaml
from pathlib import Path

dd = yaml.safe_load(Path("configs/data_dictionary.yaml").read_text(encoding="utf-8"))
factors = dd.get("factors", {})
schema_fields = dd.get("schema_fields", {})

phase_1a4 = {
    "return_20d", "return_60d", "above_ma60",
    "low_liquidity", "is_st", "is_suspended", "is_delisted",
    "pe_ttm_percentile", "pb_percentile",
    "revenue_yoy", "profit_yoy",
}
missing = phase_1a4 - set(factors)
assert not missing, f"missing factors in data_dictionary: {sorted(missing)}"
for name in phase_1a4:
    assert factors[name].get("phase") == "1a-4", name

assert schema_fields, "schema_fields must not be empty"
print("OK", len(schema_fields), "schema fields,", len(factors), "factors")
PY
```

```bash
conda run -n ashare-research-lab python - <<'PY'
import re
from pathlib import Path

text = Path("docs/planning/followups.md").read_text(encoding="utf-8")
required = [
    "effective_date",
    "factor_values",
    "schema_version",
    "ingest_local",
    "JSON",
    "is_suspended",
    "test_asof",
    "pre-commit",
    "data/raw",
]
missing = [k for k in required if k not in text]
assert not missing, f"followups.md missing keys: {missing}"
print("OK followups.md covers", len(required), "items")
PY
```

## 完成后

1. 运行 `git status`，确认只包含 phase 1a-4.5 范围内文件改动。
2. 执行 `git add .`。
3. 执行：

```bash
git commit -m "docs: phase 1a-4.5 documentation single source of truth"
```

4. 最终回复说明：
    - 修改了哪些文件。
    - Plan 第 9 / 10 / 17 节具体回写了哪些决策。
    - 数据字典补齐了多少个 schema 字段、多少个因子。
    - `docs/build_data_dictionary.py` 是否扩展为生成两份 Markdown。
    - `followups.md` 登记了哪些条目，是否包含上面列出的至少 12 条。
    - 验收命令是否全部通过。
    - commit hash。
    - 是否在实施过程中发现任何不在范围内但需要立即处理的新缺口。

## 不要实现

- 不实现新因子、不写入 `factor_values`、不写入 `research_runs`。
- 不动 `src/ashare/storage/schema.sql`、不动 `src/ashare/storage/db.py`。
- 不实现 `schema_version` 真实迁移序列（D5 登记进 followups）。
- 不修复 `init_db` JSON extension 异常字符串匹配（D7 登记进 followups）。
- 不修复 `ingest_local` 静默吞错（D8 登记进 followups）。
- 不实现 `factor_values` 唯一键（D2 登记进 followups）。
- 不重构 `ingest_local` 为增量 / upsert（D6 登记进 followups）。
- 不修 `effective_date` 盘前 / 盘中 / 盘后（D1 登记进 followups）。
- 不重构 `test_asof.py` 硬编码日期（D9 登记进 followups）。
- 不接 CI、pre-commit、ruff、black、mypy hooks（D13 / D14 登记进 followups）。
- 不接真实 AkShare 数据。
- 不调用 LLM。
- 不实现服务化 API。
- 不实现 backtest、scan、validate-factors、event-study 真实逻辑。
- 不动 PIT 查询层语义。

## 发现的缺口

- Phase 1a-4 落地的口径决策只存在于 phase goal，未回写 plan。本 phase 解决。
- `configs/data_dictionary.yaml` 长期为空骨架，phase 1a-5 因子验证报告无法从中读取因子方向与缺失策略。本 phase 解决。
- 前置 phase 累积的工程债无集中登记位置，存在重复识别与遗漏风险。本 phase 通过新建 `followups.md` 解决。
- Plan 第 9 节因子表与 phase 实施进度脱钩，没有 phase 归属字段。本 phase 解决。
- Plan 第 10 节横截面 percentile 与第 9 节单股票历史 percentile 概念混淆风险。本 phase 通过加注释解决。
