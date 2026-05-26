# HS300 Personal Research Stage Prompts

本文件把“个人可用的 A 股分析工具”拆成可连续执行的阶段 prompt。每个阶段都有两个 prompt：

- `执行 prompt`: 交给新 session 做本阶段开发、验证和文档沉淀。
- `验收 prompt`: 在进入下一阶段前交给新 session 审查上一阶段结果。只有验收结论是 `PASS` 时，才执行下一阶段；如果是 `PARTIAL` 或 `FAIL`，先回到上一阶段修复。

所有阶段都必须遵守仓库 `AGENTS.md`：默认用简体中文回复；代码、命令、路径和专有名词保持英文原文；所有 Python/CLI 命令优先使用 `conda run -n ashare-research-lab ...`；不生成买入、卖出、目标价、仓位或自动交易建议；不提交 `data/` 下 DuckDB、cache、report、snapshot 或真实 LLM 原始响应。

## 阶段总览

| 阶段 | 目标 | 对应优先级 |
| --- | --- | --- |
| Stage 1 | 把每日 HS300 exploratory 链路跑实，并补齐失败定位和产物摘要 | 真实数据可信、一键日常研究链路、长期维护 |
| Stage 2 | 补强真实数据可信度，重点是 historical PIT universe 和数据源隔离复核 | 真实数据可信、长期维护 |
| Stage 3 | 扩展个人研究分析能力，增加因子、验证切片和评分解释 | 分析能力增强、长期维护 |
| Stage 4 | 改进日报、单股报告和 watchlist 复核体验 | 报告和使用体验、一键日常研究链路 |
| Stage 5 | 让回测更接近 A 股现实，并明确 historical simulation 边界 | 回测更接近 A 股现实、真实数据可信 |
| Stage 6 | 固化日常维护、CI、备份和发布纪律 | 长期维护 |

## 通用开工检查 Prompt

每个阶段开工前先运行这个 prompt。

```text
你在 /Users/crazy/own_project/ashare-research-lab 工作。请先执行：

pwd
test -f pyproject.toml && test -d src/ashare
git status --short
git log -1 --oneline --decorate

要求：
- 默认用简体中文回复。
- 不还原用户已有改动。
- 如果工作区有未提交改动，先说明哪些文件已改，并判断是否和本阶段有关。
- 所有 Python/CLI 命令优先使用 `conda run -n ashare-research-lab ...`。
- 不提交 DuckDB、cache、report、snapshot、真实公告正文或 LLM 原始响应。
- 所有候选、评分、验证、回测、日报、单股报告都必须表述为研究输出，不是交易指令。
```

## Stage 1: 每日 HS300 Exploratory 链路跑实

### 执行 Prompt

```text
目标：在当前 `scripts/run_hs300_daily_research.sh` 基础上，把每日 HS300 exploratory 链路跑实，让它不只是 dry-run，而是能用真实 AkShare 数据或清晰失败原因支撑个人日常研究。

请先阅读：
- AGENTS.md
- README.md 中“每日 HS300 个人研究链路”
- scripts/run_hs300_daily_research.sh
- configs/scoring_hs300_daily_exploratory.yaml
- src/ashare/ingest/akshare_provider.py
- src/ashare/ingest/real_pilot.py
- src/ashare/cli.py

必须完成：
1. 用显式日期跑 dry-run，确认命名规范、窗口、输出路径和命令链正确：
   `scripts/run_hs300_daily_research.sh --as-of 2026-05-22 --dry-run`
2. 跑 AkShare capability smoke。如果失败，确认是外部网络 / AkShare API / 本地安装问题，并给出明确修复建议。
3. 跑单股票 `002594.SZ` 日线和估值 smoke，确认真实 AkShare provider 能返回 daily_prices 和 valuation_daily。
4. 跑小样本链路：
   `scripts/run_hs300_daily_research.sh --as-of 2026-05-22 --max-symbols 20`
5. 如果小样本通过，再跑完整 HS300：
   `scripts/run_hs300_daily_research.sh --as-of 2026-05-22`
6. 检查并记录关键产物：
   - data quality report
   - factor validation report
   - candidates.csv
   - scored_candidates.csv
   - stock_report.md
   - run_manifest.json
7. 如果脚本缺少运行结束摘要，请补一个简洁 summary，打印关键路径、CSV 行数、目标股票是否出现在 scan/score/stock-report 中。
8. 如果失败点来自代码或脚本，直接修复；如果失败点来自外部网络或 AkShare 当前不可用，保留最小复现命令和错误分类，不要伪造成功。
9. 不要把生成的 `data/processed/*.duckdb`、`data/raw/cache`、`data/reports/generated` 提交。

建议验证：
conda run -n ashare-research-lab pytest -q tests/test_hs300_daily_research_script.py
conda run -n ashare-research-lab python -m compileall -q src/ashare tests

最终回复必须给：
- 实际跑过哪些命令
- 每一步是否 PASS / WARN / FAIL
- 生成了哪些关键文件
- 关键 CSV 行数和日期范围
- 目标股票 `002594.SZ` 在 as-of、scan、score、stock-report 中的结果
- 测试结果
- 仍然存在的限制，特别是 AkShare 指数成分是当前快照，不是严格历史 PIT
```

### 验收 Prompt

```text
请审查 Stage 1 的执行结果，判断是否允许进入 Stage 2。不要写新功能，先做审查。

请检查：
1. `git status --short` 是否只包含 Stage 1 应有的源码 / 文档改动，不能包含 DuckDB、cache、report 或 raw data。
2. `scripts/run_hs300_daily_research.sh --as-of 2026-05-22 --dry-run` 是否通过，并展示完整命令链。
3. 是否实际跑过 AkShare capability smoke 和 `002594.SZ` 单股日线 / 估值 smoke。
4. 是否跑过 `--max-symbols 20` 小样本链路；如果未跑通，失败原因是否明确分类为代码问题、环境问题、网络问题或 AkShare API 问题。
5. 如果跑过完整 HS300，是否存在 data-quality、factor-validation、scan、score、stock-report 产物，并能给出行数和路径。
6. 脚本是否有运行结束 summary，能帮助个人每天复盘。
7. 报告和 README 是否明确写明 candidate list / composite score / stock report 都不是交易指令。
8. 测试是否至少通过：
   - `conda run -n ashare-research-lab pytest -q tests/test_hs300_daily_research_script.py`
   - `conda run -n ashare-research-lab python -m compileall -q src/ashare tests`

输出格式：
- 结论: PASS / PARTIAL / FAIL
- 阻塞项: 如果不是 PASS，列出必须先修的问题。
- 证据: 列出命令、关键输出路径和行数。
- 下一步: 只有 PASS 时才建议进入 Stage 2。
```

## Stage 2: 真实数据可信度和 Historical PIT Universe

### 执行 Prompt

```text
目标：把 Stage 1 的 exploratory 链路推进到更可信的数据基础。重点不是增加新报告，而是让 historical PIT universe、source 隔离和数据质量检查更可靠。

前置条件：必须先用 Stage 1 验收 prompt 得到 PASS；如果 Stage 1 验收结论是 PARTIAL 或 FAIL，先回到 Stage 1 修复，不要执行 Stage 2。

请先阅读：
- docs/planning/followups.md 中 D1、D16、D23、D24、D26、D29
- src/ashare/ingest/index_members.py
- src/ashare/storage/universe_snapshots.py
- src/ashare/pit/asof.py
- src/ashare/reports/data_quality_gate.py
- docs/backtest_assumptions.md

必须完成：
1. 复核 `ingest-index-members` 对 historical PIT HS300 成分的字段、重叠区间、source_tag、effective_date 校验是否足够。
2. 新增或完善一个 historical PIT universe 导入样例说明，使用本地 CSV / Parquet，不提交真实商业数据。
3. 增强数据质量检查或文档，明确区分：
   - `current_snapshot`
   - `historical_pit`
   - `unknown_legacy`
4. 确认 formal validation / formal backtest 遇到非 `historical_pit` universe 会 fail-fast。
5. 确认 `daily_prices`、`securities`、`trading_calendar`、`valuation_daily`、`universe_members` 的 source / source_tag 在 as-of、factor、validation、score、backtest 中不会静默混用。
6. 如发现缺口，补测试和文档；不要接入未经授权的商业数据源。
7. 更新 README 或 docs，让个人用户知道如何从 exploratory 当前快照链路升级到 historical PIT 链路。

建议验证：
conda run -n ashare-research-lab pytest -q tests/test_index_member_ingest.py tests/test_universe_snapshots.py tests/test_asof.py
conda run -n ashare-research-lab pytest -q tests/test_storage_migrations.py tests/test_ingest_real_pilot.py
conda run -n ashare-research-lab python -m compileall -q src/ashare tests

最终回复必须给：
- historical PIT universe 当前能力边界
- 新增或修改的文件
- formal 模式如何阻止 current snapshot 被误用
- source / source_tag 隔离验证结果
- 测试结果
- 仍然不能解决的问题，例如真实历史成分数据源需要外部提供
```

### 验收 Prompt

```text
请审查 Stage 2 的执行结果，判断是否允许进入 Stage 3。不要写新功能，先做审查。

请检查：
1. 是否有清楚的 historical PIT universe 导入说明或测试样例。
2. `current_snapshot` 是否仍被明确标记为 exploratory，不允许 formal 历史验证 / 回测伪装使用。
3. formal validation / backtest 遇到非 `historical_pit` universe 是否会 fail-fast，并有测试覆盖。
4. source / source_tag 混源风险是否有测试覆盖。
5. 是否没有提交真实数据、DuckDB、cache、report。
6. 文档是否告诉个人用户：AkShare 当前快照链路适合每日探索，不适合严肃历史回测。
7. 相关测试是否通过。

输出格式：
- 结论: PASS / PARTIAL / FAIL
- 阻塞项
- 证据
- 下一步: 只有 PASS 时才建议进入 Stage 3。
```

## Stage 3: 分析能力增强

### 执行 Prompt

```text
目标：在数据基础更可信后，扩展个人研究可用的因子、验证切片和评分解释能力。不要为了增加数量而牺牲可解释性。

前置条件：必须先用 Stage 2 验收 prompt 得到 PASS；如果 Stage 2 验收结论是 PARTIAL 或 FAIL，先回到 Stage 2 修复，不要执行 Stage 3。

请先阅读：
- configs/data_dictionary.yaml
- configs/factors.yaml
- configs/scoring.yaml
- src/ashare/factors/
- src/ashare/validation/
- src/ashare/scoring/
- docs/factor_definitions.md
- docs/data_dictionary.md

必须完成：
1. 盘点当前因子覆盖：动量、估值、硬过滤、财务同比，指出缺哪些个人研究常用维度。
2. 优先新增低风险、字段可得、PIT 语义清楚的因子，例如：
   - 波动率 / 回撤类风险因子
   - 换手率或成交额稳定性
   - 行业内相对估值分位
   - 财务质量或现金流质量，但必须确认字段来源和 PIT 语义
3. 每新增一个因子，必须同步：
   - `configs/factors.yaml`
   - `configs/data_dictionary.yaml`
   - 因子实现
   - 单元测试
   - 生成 `docs/data_dictionary.md` 和 `docs/factor_definitions.md`
4. 增强单因子验证摘要，优先考虑分年度、分行业或稳定性切片；不要把 forward_return 说成可执行收益。
5. 评分配置保持人工可读，新增因子必须经过 validation gate，不允许自动调参黑箱。

建议验证：
conda run -n ashare-research-lab python docs/build_data_dictionary.py
conda run -n ashare-research-lab pytest -q tests/test_factors.py tests/test_data_dictionary_consistency.py tests/test_validation_runner.py tests/test_scoring_scorer.py
conda run -n ashare-research-lab python -m compileall -q src/ashare tests

最终回复必须给：
- 新增或调整的因子
- 每个因子的 PIT 语义、公式、缺失处理和研究解释
- 哪些因子进入评分，哪些只展示不评分
- 测试结果
- 未解决的分析能力缺口
```

### 验收 Prompt

```text
请审查 Stage 3 的执行结果，判断是否允许进入 Stage 4。不要写新功能，先做审查。

请检查：
1. 新因子是否都有清楚的 PIT 语义和 data dictionary 描述。
2. 是否同步更新了 `configs/factors.yaml`、`configs/data_dictionary.yaml`、生成文档和测试。
3. 是否避免了用未来数据、当前行业 / 当前成分倒推历史。
4. validation gate 是否仍保护评分，不让未经验证的因子直接影响总分。
5. 报告措辞是否区分统计标签和可执行交易收益。
6. 相关测试是否通过。

输出格式：
- 结论: PASS / PARTIAL / FAIL
- 阻塞项
- 证据
- 下一步: 只有 PASS 时才建议进入 Stage 4。
```

## Stage 4: 日报、单股报告和 Watchlist 体验

### 执行 Prompt

```text
目标：把个人每天真正会看的复核体验做好，包括 daily-report、stock-report 和 watchlist。重点是复盘效率，不是营销式页面。

前置条件：必须先用 Stage 3 验收 prompt 得到 PASS；如果 Stage 3 验收结论是 PARTIAL 或 FAIL，先回到 Stage 3 修复，不要执行 Stage 4。

请先阅读：
- src/ashare/reports/daily.py
- src/ashare/reports/stock_report.py
- src/ashare/reports/run_summary.py
- src/ashare/service/app.py
- scripts/run_hs300_daily_research.sh
- README.md 中每日 HS300 链路

必须完成：
1. 把 `daily-report` 接入每日 HS300 workflow，仍保持 exploratory，不隐式重算上游研究。
2. 支持 watchlist，多只股票批量生成 `stock-report`。默认可以读取一个简单文本或 CSV，例如 `configs/watchlist.example.csv`，但不要提交私人真实 watchlist。
3. 单股报告增强：
   - 是否在本次 universe
   - 是否进入 scan
   - 是否进入 score top N
   - 硬过滤结果
   - 主要因子和 score breakdown
   - 近期公告 / risk_events 证据
4. 日报增强：
   - 今日候选 top N
   - 与上次同类 run 的排名变化，若无上次 run 要明确说明
   - validation gate 摘要
   - data quality gate 摘要
   - watchlist 股票摘要
5. 可选：服务层增加读取 latest daily report / stock report 的查询入口，但不要先做复杂前端。
6. 文档说明个人每天怎么跑、怎么看、哪些情况要停止解读。

建议验证：
conda run -n ashare-research-lab pytest -q tests/test_daily_report.py tests/test_stock_report.py tests/test_daily_report_cli.py tests/test_stock_report_cli.py
conda run -n ashare-research-lab pytest -q tests/test_service_api.py tests/test_service_artifacts.py
conda run -n ashare-research-lab python -m compileall -q src/ashare tests

最终回复必须给：
- daily-report 和 stock-report 的新能力
- watchlist 格式和运行方式
- 关键输出路径
- 测试结果
- 哪些报告内容仍然只是研究复核，不是交易指令
```

### 验收 Prompt

```text
请审查 Stage 4 的执行结果，判断是否允许进入 Stage 5。不要写新功能，先做审查。

请检查：
1. 每日 workflow 是否能生成 daily-report，并且不隐式重算上游研究。
2. watchlist 是否支持多只股票批量 stock-report，且不会提交私人真实 watchlist。
3. 报告是否能追溯输入 artifact run id、source_run_id、as_of_date、config_hash、data_snapshot_id。
4. formal / exploratory 口径是否清楚。
5. 所有报告是否没有买入、卖出、目标价、仓位建议。
6. 相关测试是否通过。

输出格式：
- 结论: PASS / PARTIAL / FAIL
- 阻塞项
- 证据
- 下一步: 只有 PASS 时才建议进入 Stage 5。
```

## Stage 5: 回测现实化和 Benchmark

### 执行 Prompt

```text
目标：让回测更接近 A 股现实，同时继续明确它只是 historical simulation，不是表现承诺。

前置条件：必须先用 Stage 4 验收 prompt 得到 PASS；如果 Stage 4 验收结论是 PARTIAL 或 FAIL，先回到 Stage 4 修复，不要执行 Stage 5。

请先阅读：
- docs/backtest_assumptions.md
- configs/backtest.yaml
- src/ashare/backtest/
- tests/test_backtest_*.py
- docs/planning/followups.md 中 D27-D32

必须完成：
1. 评估当前回测差距：
   - 小数股
   - 无 100 股整数手
   - 无真实指数行情
   - 无公司行为现金流
   - 无成交量 / 冲击成本约束
2. 优先实现对个人研究影响最大且字段可得的改进，例如：
   - 100 股整数手和零股卖出规则
   - 真实指数行情 schema / ingest 入口，或至少明确待接入接口
   - 更明确的停牌、涨跌停、退市处理报告
3. 更新 `configs/backtest.yaml`、`docs/backtest_assumptions.md` 和测试。
4. 如果接入真实指数行情，必须 source 隔离，不和股票行情混表。
5. 不把 backtest 输出写成收益承诺；所有输出继续说明是 historical simulation。

建议验证：
conda run -n ashare-research-lab pytest -q tests/test_backtest_broker.py tests/test_backtest_engine.py tests/test_backtest_cli.py tests/test_backtest_metrics.py tests/test_backtest_benchmark.py
如果不存在某个测试文件，先用 `rg --files tests | rg backtest` 找实际文件名。
conda run -n ashare-research-lab python -m compileall -q src/ashare tests

最终回复必须给：
- 回测假设改了什么
- 哪些 A 股现实约束已实现
- 哪些仍未实现，以及为什么
- 测试结果
- 报告中如何表述 historical simulation
```

### 验收 Prompt

```text
请审查 Stage 5 的执行结果，判断是否允许进入 Stage 6。不要写新功能，先做审查。

请检查：
1. 回测假设、代码、配置和测试是否一致。
2. 新增交易约束是否有边界测试。
3. benchmark 是否仍清楚区分 synthetic benchmark 和真实指数 benchmark。
4. 公司行为、成交量约束等未实现内容是否在文档中明确披露。
5. 报告是否仍然只表述为 historical simulation，不是表现承诺。
6. 相关测试是否通过。

输出格式：
- 结论: PASS / PARTIAL / FAIL
- 阻塞项
- 证据
- 下一步: 只有 PASS 时才建议进入 Stage 6。
```

## Stage 6: 长期维护和个人日常使用纪律

### 执行 Prompt

```text
目标：把个人日常使用变成可长期维护的工程流程，减少“今天能跑、明天忘了怎么复现”的风险。

前置条件：必须先用 Stage 5 验收 prompt 得到 PASS；如果 Stage 5 验收结论是 PARTIAL 或 FAIL，先回到 Stage 5 修复，不要执行 Stage 6。

请先阅读：
- .github/workflows/ci.yml
- README.md
- skills/ashare-research-lab/SKILL.md
- configs/service.yaml
- docs/planning/followups.md

必须完成：
1. 确认 CI 覆盖：
   - editable install
   - data dictionary 生成一致性
   - pytest
   - 必要时增加 compileall、ruff 或更聚焦的 workflow 测试
2. 增加个人本地维护文档：
   - 每日怎么跑
   - 每周怎么复核报告
   - 每月怎么备份 DuckDB / cache
   - 失败后怎么定位
   - 哪些文件永远不提交
3. 增加或完善 `.gitignore`，确保生成产物不会误提交。
4. 服务化只保留本地只读查询，不做公网生产部署、RBAC 或交易接口。
5. 明确真实 LLM 调用策略：默认不触发；只有配置、成本、证据定位和 schema 校验都准备好后才启用。
6. 清理过期 followups，保留仍真实存在的工程债。

建议验证：
conda run -n ashare-research-lab pytest -q
conda run -n ashare-research-lab python -m compileall -q src/ashare tests
git status --short

最终回复必须给：
- 长期维护文档和脚本入口
- CI / 测试覆盖情况
- 备份和不提交规则
- 仍保留的工程债
- 个人日常使用建议
```

### 验收 Prompt

```text
请审查 Stage 6 的执行结果，判断个人可用 A 股研究工具是否达到当前目标。不要写新功能，先做审查。

请检查：
1. 新用户是否能从 README 或维护文档知道每日怎么跑、怎么看结果、怎么排错。
2. CI 是否覆盖核心离线行为，不依赖真实 AkShare 网络。
3. 生成产物是否被 `.gitignore` 保护。
4. 全量测试或合理替代测试是否通过。
5. followups 是否没有明显过期内容。
6. 系统定位是否仍是研究实验室，不是自动交易系统。

输出格式：
- 结论: PASS / PARTIAL / FAIL
- 阻塞项
- 证据
- 当前可用边界
- 下一轮建议
```
