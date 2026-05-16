# Phase 6 Goal: 事件研究与信号验证闭环

请在已完成 Phase 5 的 `/Users/crazy/own_project/ashare-research-lab` 仓库中继续实现 Phase 6：事件研究与信号验证闭环。

本 phase 只补齐验证层中仍缺失的 `event-study` 能力。它不新增交易逻辑，不改变候选扫描、综合评分或回测核心逻辑，不把 LLM 结果直接接入总分。

## 背景

当前仓库已经具备：

- Point-in-Time 数据查询。
- 本地 fixture 数据和真实数据 ingest pilot。
- 基础因子计算和 `factor_values` 落库。
- 单因子验证报告。
- 候选清单。
- Top N 等权组合回测。
- 公告 CSV 入库和 LLM 结构化解析。
- 综合评分报告。
- 本地服务查询和 artifact index。
- 正式 run 审计与 `run_manifest.json`。

但当前仍有一个 MVP 主线缺口：

- `ashare event-study` 仍是 TODO。
- 公告、风险事件、LLM 解析结果尚不能按历史事件做收益 / 风险验证。
- Phase 3 的 `event_score` 仍默认禁用，缺少事件研究结果作为前置依据。

Phase 6 的目标是让系统能回答：

```text
某类事件在历史上发生后，
5 / 20 / 60 个交易日内是否有统计意义上的收益或风险特征？
```

## 目标

1. 实现 `ashare event-study` CLI。
2. 支持从 `announcements`、`risk_events` 和可选 `announcement_llm_results` 构造事件样本。
3. 严格使用 `effective_date` 作为事件可见日期，不使用未来信息。
4. 支持事件类型白名单和时间区间过滤。
5. 支持未来 `5 / 20 / 60` 等交易日窗口。
6. 计算事件后绝对收益、相对基准收益和基础分布统计。
7. 输出事件样本明细、窗口收益明细、聚合统计和 Markdown 报告。
8. 接入 Phase 5 审计：`research_runs`、`research_run_inputs`、`research_artifacts` 和 `run_manifest.json`。
9. 增加测试，覆盖 PIT 事件可见性、窗口收益、基准收益、空样本、重复事件、CLI 和审计产物。

## 工作约束

- 严格遵守 `docs/planning/a-share-research-plan.md`。
- 所有 Python 命令必须在 Conda 环境 `ashare-research-lab` 中执行。
- 每个 phase 必须单独 commit。
- 本 phase 不实现真实公告源接入。
- 本 phase 不扩展 AkShare provider。
- 本 phase 不新增 LLM prompt 或 LLM client 能力。
- 本 phase 不让 LLM 输出直接进入 `score`。
- 本 phase 不实现 `event_score`。
- 本 phase 不修改 `factor_values`。
- 本 phase 不修改组合回测撮合逻辑。
- 本 phase 不新增交易建议、买入、卖出或目标价表达。
- `event-study` 必须显式传入 `--event-source`、`--event-type`、`--from`、`--to` 和 `--horizon`。
- `event-study` 不能默认使用当前日期、最近 run 或旧报告。
- 默认以 DuckDB `read_only=True` 打开数据库；只有审计写入需要通过 `AuditContext` 打开可写连接。

## 建议文件变更

新增：

```text
src/ashare/validation/event_study.py
src/ashare/reports/event_study_report.py
tests/test_event_study.py
tests/test_event_study_cli.py
```

修改：

```text
src/ashare/cli.py
src/ashare/service/artifacts.py
configs/service.yaml
docs/planning/followups.md
```

可选修改：

```text
src/ashare/service/app.py
src/ashare/service/queries.py
tests/test_service_artifacts.py
tests/test_service_api.py
```

仅当需要让服务查询最新事件研究报告时修改服务层。

不得提交：

```text
data/reports/generated/
data/processed/*.duckdb
data/service/
tests/fixtures/generated/
data/raw/announcements/
```

## 事件来源

`event-study` 初版支持三类来源。

### `announcements`

读取 `announcements` 表：

```text
announcement_id
stock_code
announcement_type
publish_time
effective_date
title
source
source_tag
url
raw_path
text_hash
```

过滤规则：

```text
event_source = announcements
event_type -> announcements.announcement_type
event_date -> announcements.effective_date
```

### `risk_events`

读取 `risk_events` 表：

```text
event_id
stock_code
event_type
event_date
publish_time
effective_date
payload_json
source
```

过滤规则：

```text
event_source = risk_events
event_type -> risk_events.event_type
event_date -> risk_events.effective_date
```

### `announcement_llm_results`

可选支持，只用于验证 LLM 解析信号，不进入总分。

读取成功解析结果：

```text
announcement_llm_results.status = 'success'
announcement_llm_results.confidence >= configured threshold
```

事件类型建议先限定为：

```text
llm_sentiment_positive
llm_sentiment_negative
llm_risk_detected
llm_catalyst_detected
```

如果实现成本过高，本 phase 可以先不做 LLM 来源，但必须在 `followups.md` 中保留后续项。

## PIT 规则

事件样本必须满足：

```text
effective_date BETWEEN --from AND --to
```

事件发生后的收益窗口从 `effective_date` 当天收盘后开始观察。

默认收益口径：

```text
event_date_close -> future_close
```

其中价格使用：

```text
adjusted_close = close * adj_factor
```

`adj_factor` 为空时 fallback 到 `close`。

如果 `effective_date` 当天没有该股票价格：

- 默认跳过该事件。
- 在样本明细中记录 `skip_reason = missing_event_date_price`。

如果未来窗口没有足够交易日：

- 不生成该窗口收益。
- 在样本明细中记录可用最大窗口。

## 基准收益

第一版不依赖真实指数行情表。

基准收益按配置选择：

```text
benchmark = synthetic_equal_weight
benchmark = synthetic_cap_weight
benchmark = none
```

默认使用 `synthetic_equal_weight`。

合成基准 universe 使用事件日期 `as_of_date = event_date` 的 PIT `universe_members`。

基准收益同样使用 `adjusted_close`。

输出：

```text
event_return
benchmark_return
excess_return = event_return - benchmark_return
```

## 去重规则

同一股票在同一 `effective_date` 同一 `event_type` 可能出现多条事件。

默认策略：

```text
deduplicate = false
```

即保留全部事件样本，并在报告中披露重复样本数。

可配置或 CLI 支持：

```text
--deduplicate same-stock-date-type
```

去重后保留排序最前的一条，排序键：

```text
effective_date
publish_time
source_tag
event_id 或 announcement_id
```

## 输出产物

输出目录默认由 Phase 5 审计上下文决定：

```text
data/reports/generated/event_study/{run_id}/
```

必须输出：

```text
event_study_report.md
event_samples.csv
event_window_returns.csv
event_summary.csv
run_manifest.json
```

可选输出：

```text
event_distribution.csv
event_by_year.csv
event_by_industry.csv
```

## 输出字段

`event_samples.csv` 至少包含：

```text
event_source
event_id
stock_code
event_type
event_date
publish_time
effective_date
source
source_tag
title
included
skip_reason
duplicate_group_id
```

`event_window_returns.csv` 至少包含：

```text
event_source
event_id
stock_code
event_type
event_date
horizon
event_price_date
future_price_date
event_return
benchmark_return
excess_return
```

`event_summary.csv` 至少包含：

```text
event_source
event_type
horizon
sample_count
mean_event_return
median_event_return
win_rate
mean_benchmark_return
mean_excess_return
median_excess_return
excess_win_rate
p25_excess_return
p75_excess_return
```

## CLI 设计

目标命令：

```bash
ashare event-study \
  --db-path data/processed/phase5_fixture.duckdb \
  --event-source announcements \
  --event-type earnings_forecast \
  --from 2026-01-01 \
  --to 2026-06-26 \
  --horizon 5,20,60 \
  --index-code LOCAL_FIXTURE \
  --benchmark synthetic_equal_weight \
  --run-id phase6-fixture-event-study
```

建议参数：

```text
--db-path
--event-source announcements|risk_events|announcement_llm_results
--event-type
--from
--to
--horizon
--index-code
--benchmark synthetic_equal_weight|synthetic_cap_weight|none
--deduplicate none|same-stock-date-type
--min-confidence
--output-dir
--overwrite
--run-id
--run-mode exploratory|formal
--overwrite-run / --no-overwrite-run
--audit-config
```

## 报告要求

Markdown 报告必须明确：

- 本报告是事件研究，不是组合回测。
- 本报告不是交易指令。
- 样本来源和事件类型。
- PIT 口径和 `effective_date` 规则。
- 样本数、跳过样本数和主要跳过原因。
- 各 horizon 的平均收益、中位数、胜率、超额收益。
- 是否存在样本过少风险。
- 是否存在重复事件样本。
- 当前基准是合成基准还是不使用基准。

## 测试要求

核心测试：

- `effective_date > --to` 的事件不可见。
- `effective_date < --from` 的事件不可见。
- 事件窗口收益使用 `adjusted_close`。
- `adj_factor` 为空时 fallback 到 `close`。
- 缺失事件日价格时事件被跳过并记录原因。
- 未来窗口不足时不生成该 horizon。
- `announcements` 来源按 `announcement_type` 过滤。
- `risk_events` 来源按 `event_type` 过滤。
- 重复事件默认保留。
- `--deduplicate same-stock-date-type` 后只保留一条。
- 空样本时 fail-fast 或输出空报告的规则必须固定，并有测试。
- CLI 输出 Markdown 和 CSV。
- 审计记录写入 `research_runs`。
- 产物写入 `research_artifacts`。
- 生成 `run_manifest.json`。

## 验收命令

以下命令必须成功：

```bash
conda run -n ashare-research-lab python -m pip install -e .
conda run -n ashare-research-lab pytest -q
conda run -n ashare-research-lab ashare --help
```

使用 fixture 跑通事件研究：

```bash
conda run -n ashare-research-lab ashare event-study \
  --db-path data/processed/phase6_fixture.duckdb \
  --event-source announcements \
  --event-type earnings_forecast \
  --from 2026-01-01 \
  --to 2026-06-26 \
  --horizon 5,20,60 \
  --index-code LOCAL_FIXTURE \
  --benchmark synthetic_equal_weight \
  --run-id phase6-fixture-event-study \
  --overwrite-run
```

验收后应能看到：

```text
event_study_report.md
event_samples.csv
event_window_returns.csv
event_summary.csv
run_manifest.json
```

并且服务 artifact registry 能识别 `event_study` 类型产物；如果本 phase 不接服务查询，需要在 `followups.md` 中说明。

## 完成后

1. 运行 `git status`，确认只包含 Phase 6 相关改动。
2. 执行 `git add .`。
3. 执行 `git commit -m "feat: phase 6 event study validation"`。
4. 最终回复说明：
   - 改了哪些文件。
   - `event-study` 支持哪些事件来源。
   - PIT 口径如何保证。
   - 输出了哪些报告和 CSV。
   - 审计记录是否写入。
   - 验收命令是否全部通过。
   - commit hash。
   - 是否新增 followup。

## 不要实现

- 完整每日研究报告。
- 单股研究报告。
- 真实公告源接入。
- 新的 LLM prompt / schema。
- `event_score`。
- 把 LLM 或事件研究结果直接接入 `score`。
- 生产级服务部署。
- 多用户权限系统。
- 自动交易。
