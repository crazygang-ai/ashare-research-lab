# Phase 7 Goal: 正式每日研究可用闭环

请在已完成 Phase 6 的 `/Users/crazy/own_project/ashare-research-lab` 仓库中继续实现 Phase 7：正式每日研究可用闭环。

本 phase 的目标不是把系统变成自动交易平台，也不是输出买入 / 卖出指令。它要把当前已经可运行的离线研究链路，提升到每天可以稳定生成、复核、审计和解释的正式研究辅助流程。

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
- 事件研究。
- 本地服务查询、workflow、scheduler 和 repo-local Skill。
- 正式 run 审计、artifact index 和 `run_manifest.json`。

当前系统已经可以作为本地离线研究实验版使用，但还不能直接作为正式每日投资决策系统使用，主要缺口是：

- 每日运行缺少统一的数据质量门禁。
- 候选清单、综合评分、回测摘要、事件研究和公告证据还没有汇总成完整日报。
- `stock-report` 仍是 TODO，单股展开复核能力不足。
- 真实数据路径仍是 pilot，不是生产级数据管线。
- 因子集仍偏基础，软风险因子和更多财务质量因子尚未稳定落库。
- 服务化仍偏本地查询，不具备生产部署、权限、原子发布和 durable scheduler 能力。

Phase 7 先补“每天正式复盘和辅助决策”必需的闭环，不处理自动交易和生产部署。

## 目标

1. 增加每日研究运行的统一入口或 workflow 模板。
2. 增加每日数据质量门禁，数据异常时 fail-fast 或明确降级。
3. 生成完整每日研究报告。
4. 实现 `ashare stock-report`，支持单股展开复核。
5. 将候选清单、综合评分、因子验证摘要、回测摘要、事件研究摘要和公告证据汇总到报告层。
6. 每日报告必须接入 Phase 5 审计：`research_runs`、`research_run_inputs`、`research_artifacts` 和 `run_manifest.json`。
7. 报告中明确区分研究候选、验证结论、风险提示和不可交易状态。
8. 增加测试，覆盖每日运行、数据质量门禁、日报渲染、单股报告、artifact index、审计 manifest 和失败路径。

## 非目标

- 不实现自动交易。
- 不实现 OMS、实盘下单、交易审批或券商接口。
- 不输出买入、卖出、目标价或仓位指令。
- 不把 LLM 输出未经验证直接接入总分。
- 不实现公网服务、用户系统、RBAC、生产监控或远程部署。
- 不一次性补齐全 A 数据平台。
- 不在本 phase 内做权重自动优化。
- 不把单因子统计收益描述为可执行交易收益。

## 工作约束

- 严格遵守 `docs/planning/a-share-research-plan.md`。
- 所有 Python 命令必须在 Conda 环境 `ashare-research-lab` 中执行。
- 每个 phase 必须单独 commit。
- 所有日期必须显式传入，不能默认使用当前日期、最近 run 或旧报告。
- 正式日报必须带 `run_id`、`as_of_date`、`source_run_id`、配置哈希、数据快照指纹、git sha 和 worktree 状态。
- 数据质量未通过时，不得生成看似正常的正式日报。
- 探索性运行可以生成草稿报告，但必须标记 `run_mode = exploratory`。
- 正式运行必须支持 `run_mode = formal` 并遵守 clean worktree 策略。
- 报告中任何候选股票都必须能追溯到数据、因子、验证、风险和证据来源。
- 所有新增报告必须输出 Markdown 和 CSV / JSON 明细。
- 不提交生成的报告、DuckDB、cache、workflow 日志或公告正文。

## 建议文件变更

新增：

```text
src/ashare/reports/daily.py
src/ashare/reports/stock_report.py
src/ashare/reports/data_quality_gate.py
src/ashare/reports/run_summary.py
tests/test_daily_report.py
tests/test_stock_report.py
tests/test_data_quality_gate.py
tests/test_daily_report_cli.py
tests/test_stock_report_cli.py
```

修改：

```text
src/ashare/cli.py
src/ashare/service/artifacts.py
configs/service.yaml
configs/audit.yaml
skills/ashare-research-lab/SKILL.md
skills/ashare-research-lab/references/commands.md
docs/planning/followups.md
```

可选修改：

```text
src/ashare/service/app.py
src/ashare/service/queries.py
tests/test_service_artifacts.py
tests/test_service_api.py
```

仅当需要让服务直接查询最新日报或单股报告时修改服务层。

不得提交：

```text
data/reports/generated/
data/processed/*.duckdb
data/service/
tests/fixtures/generated/
data/raw/announcements/
```

## CLI 设计

### `daily-report`

新增或完善：

```text
ashare daily-report \
  --as-of 2026-05-13 \
  --db-path data/processed/ashare.duckdb \
  --source-run-id factor-run-20260513 \
  --scan-run-id scan-20260513 \
  --score-run-id score-20260513 \
  --backtest-run-id backtest-base \
  --event-study-run-id event-study-latest \
  --output-dir data/reports/generated/daily/daily-20260513 \
  --run-id daily-20260513 \
  --run-mode formal
```

规则：

- `--as-of` 必填。
- `--source-run-id` 必填。
- 不允许自动读取最近 run，除非显式传入 `--allow-latest-artifacts`。
- 如果显式允许读取 latest artifact，报告 metadata 必须列出实际采用的 artifact id 和 run id。
- 默认只读取已存在产物，不重复计算因子、评分、回测或事件研究。
- 如果关键输入产物缺失，formal 模式必须 fail-fast。
- exploratory 模式可以生成降级报告，但必须在 Markdown 和 metadata 中列出缺失项。

### `stock-report`

将现有 `ashare stock-report` 从 TODO 改为真实报告命令：

```text
ashare stock-report \
  --code 000001.SZ \
  --as-of 2026-05-13 \
  --db-path data/processed/ashare.duckdb \
  --source-run-id factor-run-20260513 \
  --score-run-id score-20260513 \
  --output-dir data/reports/generated/stock/000001.SZ-20260513 \
  --run-id stock-000001SZ-20260513 \
  --run-mode formal
```

规则：

- `--code`、`--as-of`、`--source-run-id` 必填。
- 只使用 `as_of_date` 当时 PIT 可见的数据。
- 不能读取当前股票名称、当前行业或当前指数成分倒推历史。
- 报告必须说明是否进入候选池，以及进入 / 未进入的原因。
- 报告必须展示硬过滤、主要因子、综合评分、风险提示和近期公告证据。

## 数据质量门禁

正式日报前必须生成数据质量 gate 结果。

建议输出：

```text
data_quality_gate.json
data_quality_gate.csv
```

最小检查项：

- `trading_calendar` 是否包含 `as_of_date` 且为开市日。
- `daily_prices` 是否覆盖目标 universe 的主要股票。
- `valuation_daily` 是否覆盖目标 universe。
- `factor_values` 是否存在指定 `source_run_id` 和 `as_of_date`。
- hard filter 是否覆盖候选 universe。
- `announcements` / `risk_events` 缺失时是否按配置允许降级。
- 输入 artifact 是否存在且 hash 可计算。
- 关键配置文件是否存在且 hash 可计算。
- 数据库 schema 是否满足当前版本。

gate 结果至少包含：

```text
check_name
status
severity
observed_value
threshold
message
```

规则：

- `status` 取 `PASS`、`WARN`、`FAIL`。
- `severity` 取 `info`、`warning`、`blocking`。
- formal 模式中存在 blocking `FAIL` 时必须中止。
- exploratory 模式允许继续，但报告必须显示降级原因。

## 每日研究报告

Markdown 报告至少包含：

1. 标题。
2. `as_of_date`。
3. `run_id`。
4. `run_mode`。
5. 数据库路径。
6. `source_run_id`。
7. 输入 artifact id / run id 清单。
8. 数据质量 gate 摘要。
9. 今日候选 Top N。
10. 新增 / 移出 / 排名变化。
11. 综合评分 Top N。
12. 因子贡献拆解。
13. 主要硬过滤排除原因。
14. 主要风险提示。
15. 近期公告 / 事件摘要。
16. 事件研究摘要。
17. 单因子验证摘要。
18. 回测表现摘要。
19. 数据限制和已知风险。
20. 明确声明：本报告是研究辅助输出，不是交易指令。

CSV / JSON 明细至少包含：

```text
daily_candidates.csv
daily_score_summary.csv
daily_factor_contributions.csv
daily_risk_summary.csv
daily_changes.csv
daily_input_artifacts.json
daily_metadata.json
data_quality_gate.csv
```

## 单股研究报告

Markdown 报告至少包含：

1. 股票代码和名称。
2. `as_of_date`。
3. 所属行业。
4. 是否在目标 universe。
5. 是否进入候选池。
6. 候选排名和综合评分排名。
7. 财务因子。
8. 估值因子。
9. 动量因子。
10. 硬过滤状态。
11. 软风险提示。
12. 近期公告摘要和证据片段。
13. 相关事件研究结果摘要。
14. 最近回测中是否常见入选 / 持有。
15. 数据来源、配置、run id 和 artifact id。
16. 明确声明：本报告是研究辅助输出，不是交易指令。

CSV / JSON 明细至少包含：

```text
stock_factor_values.csv
stock_score_breakdown.csv
stock_risk_flags.csv
stock_recent_announcements.csv
stock_metadata.json
```

## 候选变化口径

日报需要展示与上一个显式对比日的变化。

CLI 设计：

```text
--compare-as-of 2026-05-12
--compare-scan-run-id scan-20260512
--compare-score-run-id score-20260512
```

规则：

- 默认不自动读取昨日或最近报告。
- 如果未传对比参数，`daily_changes.csv` 输出空表，并在报告中说明未执行对比。
- 新增 / 移出 / 排名变化必须基于显式输入 artifact。
- 不能用当前日期推导上一交易日。

## Artifact 和服务查询

新增 artifact kind：

```text
daily_report
stock_report
data_quality_gate
```

服务层如扩展 endpoint，建议增加：

```text
GET /api/v1/daily/latest
GET /api/v1/daily/{artifact_id}
GET /api/v1/stocks/{stock_code}/reports/latest
GET /api/v1/stocks/{stock_code}/reports/{artifact_id}
```

规则：

- 服务只读。
- 优先读取 `research_artifacts`。
- DuckDB 不可用时可以 fallback 文件扫描。
- 不在服务层重新计算报告。

## 验收标准

Phase 7 完成后，系统至少能回答：

```text
今天为什么生成 / 未生成正式日报？
今天用了哪些数据、配置和产物？
数据质量是否足以支撑正式报告？
哪些股票进入候选池？
每只候选股票为什么入选？
主要风险是什么？
哪些股票相对上次新增、移出或排名变化？
相关因子历史验证表现如何？
近期公告和事件研究是否支持或削弱信号？
任意单股能否展开复核？
本次报告能否按 run_id 复现？
```

硬验收：

- `ashare daily-report` 可生成 Markdown、CSV 和 JSON 明细。
- `ashare stock-report` 可生成 Markdown、CSV 和 JSON 明细。
- formal 模式下数据质量 blocking failure 会非 0 退出。
- 所有正式报告写入 `research_runs`、`research_run_inputs`、`research_artifacts` 和 `run_manifest.json`。
- 服务 artifact registry 可识别 `daily_report` 和 `stock_report`。
- 全量测试通过。

## 后续仍保留

以下能力不在 Phase 7 内完成，但应继续保留在 `followups.md`：

- 真实历史沪深 300 / 中证 500 PIT 成分库。
- 真实公告源 provider。
- 生产级 AkShare / Tushare / baostock provider。
- timestamp 级 PIT 可见性。
- 更多财务质量因子和软风险因子。
- 单因子分年度、分行业和换手率验证。
- 真实指数行情基准。
- 行业中性化和组合风控约束。
- 生产部署、权限、监控、告警和 durable scheduler。
- 自动交易、OMS、审批流和券商接口。
