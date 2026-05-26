# Phase Followups

本文件登记前置 phase 已识别但当前系列 phase 暂不解决的工程债。D 系列编号来自 phase 1a-4.5 review 中的工程债扫描，保留编号是为了便于后续审计回溯。

## Phase 7 更新

- 已解决: `ashare daily-report` 已支持从显式 `scan`、`scoring`、`backtest`、`event_study` 和可选 `factor_validation` audited artifacts 组装正式日报，输出 Markdown、CSV、JSON 明细，先写 `data_quality_gate.csv/json`，并接入 `research_runs`、`research_run_inputs`、`research_artifacts` 与 `run_manifest.json`。
- 已解决: `ashare stock-report` 已从 TODO 改为真实单股复核报告，基于 `as_of_date` PIT 数据和显式评分 artifact 展示候选状态、综合评分、硬过滤、因子、风险和公告证据。
- 已解决: 服务 artifact registry 已识别 `daily_report`、`stock_report` 和 `data_quality_gate` 类型产物，可通过通用 artifact index 查询。
- 部分解决: D22 的完整日报缺口已形成可用闭环；日报仍只汇总显式传入的既有产物，不在日报命令内重算因子、评分、回测或事件研究。
- 仍保留: 正式生产数据管线、真实历史指数成分库、timestamp 级 PIT、更多财务质量和软风险因子、生产部署 / RBAC / durable scheduler、自动交易 / OMS / 审批流和券商接口仍不在 Phase 7 内完成。

## Phase 8 更新

- 已解决: D2 增加 `factor_values` migration 预检、DuckDB unique index 与写入层 fail-fast 共同治理；重复键会在旧库升级或写入时明确失败。
- 已解决: D5 建立 `src/ashare/storage/migrations/` 与 `schema_version` 连续版本记录；`init_db` 会按序幂等应用 migration。
- 已解决: D13 增加最小 GitHub Actions CI，覆盖 Conda 环境、editable install、data dictionary 生成和 `pytest -q`。
- 已解决: D15 的 `data/raw` 与 `data/snapshots` `.gitkeep` 已存在，不再作为待办债务保留。
- 已解决: D16 增加 `factor_run_universe`，`calculate-factors` 写入显式 universe 分母，验证、评分、回测和日报 gate 优先使用该快照。
- 已解决: D23 为 `daily_prices`、`securities`、`trading_calendar` 增加 `source` 隔离，真实 pilot 的 bounded replace 限定在同一 source / source_tag 内。
- 已解决: D24 增加 `ingest-index-members` CSV / Parquet 入口，可导入 historical PIT 成分并标记 `current_snapshot`。
- 已解决: D26 增加 AkShare capability check、字段映射版本、基础重试 / 限速和可分类 provider 错误。
- 仍保留: timestamp 级 PIT、验证 / 回测 / 评分明细结果表、生产级查询筛选、商业级历史成分源、公告真实源、监控告警和多用户权限仍不在 Phase 8 内完成。

## Phase 6 更新

- 已解决: `ashare event-study` 已支持 `announcements`、`risk_events` 和 `announcement_llm_results` 三类 PIT 事件样本，输出事件样本、窗口收益、聚合统计、Markdown 报告，并接入 `research_runs`、`research_run_inputs`、`research_artifacts` 与 `run_manifest.json`。
- 已解决: 服务 artifact registry 已识别 `event_study` 类型产物，可通过通用 artifact index 查询和读取报告 / CSV。
- 仍保留: 暂未新增事件研究专用服务 API、分行业事件研究 CSV、真实指数行情基准或事件研究结果持久化明细表；如后续需要在服务内直接查询最新事件研究摘要，应补专用 endpoint 和 schema。

## Phase 5 更新

- 已解决: D32、D38、D43、D44 的 MVP 审计缺口。`calculate-factors`、`report`、`scan`、`score`、`backtest`、`validate-factors` 和 `parse-announcements` 已接入 `research_runs`、`research_artifacts`、`research_run_inputs` 与 `run_manifest.json`；服务层优先读取 artifact index，并保留文件扫描 fallback。
- 部分解决: D18 已持久化验证报告 run 与文件索引，但未新增因子验证结果明细表；Phase 8 已补齐 D2 物理唯一治理与 D16 显式 universe 快照。
- 仍保留: D1、D19、D22、D24、D33、D39、D45-D55 等超出 Phase 5 范围的生产化、事件研究、真实数据源、timestamp 级 PIT、完整日报和权限部署能力。

## 高优先

### D1. effective_date 不区分盘前 / 盘中 / 盘后

- 现状: `src/ashare/pit/effective_date.py` 与各 ingest 路径只落到 date 级 `effective_date`；Phase 2 公告 ingest / parse 也按 date 级 `effective_date` 和 date 级 `--as-of` 过滤，不能表达盘前 / 盘中 / 盘后披露对当日交易信号的差异。
- 触发: 当系统接入真实公告、财报、每日盘前报告或盘中运行时，同一天披露时间会影响是否可在 `as_of_date` 使用该信息。
- 决策: 短期继续保持 date 级 PIT 口径并在报告中披露；待真实公告 / 财报数据接入或盘中运行需求明确时，统一决策是否引入 timestamp 级可见性、同日交易可用规则和历史数据回填口径。
- 关联: Plan 第 7 节 Point-in-Time 规则；Phase 2 公告解析。

### D2. factor_values 唯一键治理已落地，仍需长期监控

- 现状: Phase 8 已在 migration 中增加 `idx_factor_values_unique_key` 等价治理，不依赖 DuckDB `PRIMARY KEY` 语法；升级前检查 `(source_run_id, stock_code, trade_date, as_of_date, factor_name)` 重复键；`src/ashare/factors/store.py` 仍保留写入层 fail-fast 与显式 `--overwrite-run` 治理。
- 触发: 当重复运行同一批因子并写入同一数据库时，重复行会污染单因子验证、候选清单排序、回测输入和审计追踪。
- 决策: 当前采用 migration 预检、DuckDB unique index 和应用层治理的组合；后续只在需要跨库 merge 或 upsert 语义时再扩展冲突处理策略。
- 关联: Phase 1a-4 因子写入路径；Phase 1a-5 单因子验证输入检查；Phase 1a-6 候选扫描输入检查；Phase 5 run audit。

### D3. fundamental 同期基准与 trading_calendar 起点的张力

- 现状: `src/ashare/fixtures/builder.py` 已把主样本长度扩展到 `MAIN_SAMPLE_DAYS = 125`，并补了 2025 与 2026 同期财报样本；Phase 1a-4 的严格同期基准测试已闭环。
- 触发: 如果后续 fixture 再缩短交易日长度或改用 trading_calendar 派生财报同期样本，`revenue_yoy` / `profit_yoy` 可能重新缺少可见基准。
- 决策: 保留严格 `(year - 1, month, day)` 匹配，不向最近季度末或最近披露日回退；fixture 继续显式提供 pre-history 财报。
- 关联: Plan 第 9 节财务同比口径。

### D4. is_suspended = 1.0 二义性

- 现状: `src/ashare/factors/risk.py` 将当日 `daily_prices.is_suspended = true` 与 universe 内股票缺失当日 `daily_prices` 行都映射为 `is_suspended = 1.0`。
- 触发: 当报告需要区分真实停牌、行情缺失、指数成分异常或数据供应延迟时，单一布尔值会掩盖原因。
- 决策: 后续 phase 如需区分，应新增独立 `data_missing` 字段，不改变当前 `is_suspended` 的不可交易语义。
- 关联: Plan 第 9 节与 `configs/data_dictionary.yaml`。

### D5. 最小 migration 机制已落地，仍非生产级回滚体系

- 现状: Phase 8 已新增 `src/ashare/storage/migrations/0001_initial.sql` 到 `0004_source_isolation_and_factor_keys.sql` 的迁移序列，`init_db` 会幂等应用 migration 并在 `schema_version` 记录连续版本；旧库升级会对重复 `factor_values` fail-fast。
- 触发: 一旦继续变更表结构、补唯一键、拆分 JSON 字段或回填历史公告 / 解析数据，缺少明确 migration 记录会使本地数据库状态不可审计。
- 决策: 当前 migration 覆盖本地 DuckDB 无损升级和关键约束校验；schema 演进仍不提供自动回滚、在线迁移、备份编排或历史大规模回填审计。
- 关联: `src/ashare/storage/schema.sql`；`src/ashare/storage/db.py`；Phase 2 公告与 LLM 解析表。

### D6. ingest_local 是清表重写，不能用于真实数据

- 现状: `src/ashare/ingest/local.py` 的 `ingest_local` 面向 fixture 和本地快照，采用清表重写而不是增量 / upsert。
- 触发: 接入真实 AkShare 数据、增量行情或多来源快照时，清表会破坏历史审计和并发运行安全。
- 决策: Phase 1a-7 已新增独立的 `src/ashare/ingest/real_pilot.py` 真实数据试点路径，不复用 `ingest_local` 的清表重写语义；`ingest_local` 继续保持 fixture-only，后续真实数据正式化时再设计完整增量 / upsert 机制。
- 关联: Phase 1a-2 / 1a-3 ingest 设计；Phase 1a-7 real data ingest pilot。

### D16. factor_values 显式 universe 快照已落地，仍未持久化验证明细

- 现状: Phase 8 新增 `factor_run_universe`，`calculate-factors` 为每个 `source_run_id` / `trade_date` 写入完整 universe、`source_tag`、`universe_kind` 和 fingerprint；验证、评分、回测和日报 gate 会优先使用该快照。
- 触发: 当 hard filter 未完整写入、局部因子重算、跨 run 比较或正式报告要求精确覆盖率时，推断分母可能高估覆盖率或掩盖 universe 变化。
- 决策: 覆盖率分母不再只能从 hard filter 或因子行推断；后续如需数据库内长期查询 IC / coverage 历史，仍需另建验证结果明细表。
- 关联: Phase 1a-5 覆盖率与缺失率口径；Plan 第 6 节 `factor_values`。

### D17. 单因子 forward_return 是统计标签，不是可执行收益

- 现状: `src/ashare/validation/labels.py` 使用 `close * adj_factor` 构造 close-to-close 未来收益标签，不因停牌、退市、涨跌停或不可交易状态主动剔除样本。
- 触发: 当用户把 Rank IC、Top / Bottom 或 `long_short_return` 解释成可执行策略收益时，会忽略 A 股交易约束、成交价、停牌、涨跌停、退市和成本。
- 决策: Phase 1a-5 继续把 forward return 定义为单因子统计标签；Phase 1b 已在组合回测层加入基础交易约束、撮合和成本，但不改变单因子验证标签口径。报告中必须明确区分统计标签和回测可执行收益。
- 关联: Plan 第 11 节单因子检验；Plan 第 12 节回测假设；`docs/backtest_assumptions.md`。

## 中优先

### D7. init_db JSON extension 异常字符串匹配

- 现状: `src/ashare/storage/db.py` 的 JSON extension 加载异常处理依赖错误字符串匹配，缺少 fail-fast 级别的明确错误分类。
- 触发: DuckDB 或运行环境改变错误文本时，init_db 可能误判 JSON extension 是否可用。
- 决策: 后续补显式 capability check 或更窄的异常类型；本 phase 不修复。
- 关联: 数据库初始化路径。

### D8. ingest_local._load_json_extension_if_available 静默吞错

- 现状: `src/ashare/ingest/local.py` 中 `_load_json_extension_if_available` 对 JSON extension 加载失败采取静默降级。
- 触发: 真实数据包含 JSON 字段且 DuckDB 环境异常时，静默吞错会延迟暴露数据写入问题。
- 决策: 后续改为可配置的 fail-fast 或显式 warning；Phase 1a-4.5 只登记。
- 关联: D7。

### D9. test_asof 硬编码具体日期

- 现状: `tests/test_asof.py` 中多处断言硬编码具体 fixture 日期，与 `src/ashare/fixtures/builder.py` 的交易日长度和样本索引耦合。
- 触发: fixture 起始日、样本长度、事件索引或日期边界覆盖调整时，测试会因日期漂移失败而不是因 PIT 语义失败。
- 决策: 后续改为从 fixture builder 暴露的样本索引或查询结果推导关键日期。
- 关联: Phase 1a-3.5 PIT 测试。

### D13. 最小 CI 已落地，仍未覆盖 lint / type check

- 现状: Phase 8 已增加 GitHub Actions，运行 Conda 环境创建、`python -m pip install -e .`、`python docs/build_data_dictionary.py` 和 `pytest -q`。
- 触发: 多人协作、长期分支开发或单因子验证统计继续扩展后，未运行验收命令的提交可能进入主线并造成产物漂移。
- 决策: CI 先保护核心离线行为，不默认触发真实 AkShare 网络 smoke；后续再补 ruff、mypy、coverage 或更细的 artifact drift 检查。
- 关联: Plan 第 20 节测试要求。

### D18. 单因子验证结果未持久化

- 现状: Phase 5 已把 `validate-factors` 和 `report --kind factor-validation` 的 run metadata、输入指纹、报告文件和 manifest 写入 `research_runs` / `research_artifacts`；但仍不新增 DuckDB 因子验证明细结果表。
- 触发: 当需要跨 `source_run_id` 查询历史验证结论、在数据库中审计报告生成参数，或把验证摘要稳定接入正式 run / 服务化接口时，仅靠文件报告仍不足以支撑机器查询。
- 决策: Phase 5 先完成报告级索引和审计；后续如需数据库内直接查询 Rank IC / coverage 历史，再设计验证结果持久化表。
- 关联: Plan 第 15 节因子验证报告；Phase 1a-5 单因子验证；Phase 1a-6 因子报告。

### D19. 单因子验证暂未覆盖分年度、分行业和换手率

- 现状: Phase 1a-5 实现覆盖率、缺失率、Rank IC、ICIR、Top / Bottom 分组收益和衰减曲线，但未实现 Plan 第 11 节列出的分年度表现、分行业表现和单因子 / 候选池换手率；Phase 1b 的 `average_turnover` / `max_turnover` 是组合回测层指标，不补齐单因子验证口径。
- 触发: 当需要判断因子稳定性、行业结构偏误或实际调仓冲击时，当前验证摘要不足以支撑因子保留 / 剔除结论。
- 决策: 后续验证增强 phase 中补充分年度、分行业和单因子 / 候选池换手率口径；实现时应复用已明确的调仓日期、排序和入选规则，避免把组合回测换手率与因子验证换手率混同。
- 关联: Plan 第 11 节单因子检验；Phase 1b 组合回测指标。

### D20. candidate scan 风险阈值硬编码

- 现状: Phase 1a-6 候选清单的 `pe_ttm_percentile >= 0.8`、`pb_percentile >= 0.8`、`return_20d < 0`、`return_60d < 0`、`above_ma60 == 0.0` 等风险提示规则和阈值写在扫描规则中。
- 触发: 当不同市场环境、行业或研究口径需要不同风险阈值时，硬编码会降低复盘透明度并增加改代码成本。
- 决策: 后续引入 scan 配置或扩展数据字典来管理风险提示阈值；本 phase 只登记，不做配置化。
- 关联: Phase 1a-6 候选清单风险提示；Plan 第 15 节每日研究报告。

### D21. candidate scan 仍保持单因子排序口径

- 现状: Phase 1a-6 `scan` 仍只按显式传入的 `sort_factor` 输出最小候选清单，不做多因子加权、0-100 标准化、行业中性化或基于 ICIR 的自动调权；Phase 3 已新增独立 `ashare score` 综合评分报告，但不改变 `scan` 的单因子候选语义。
- 触发: 当用户把 `scan` 输出误解为多因子综合排序，或希望在单因子候选清单中直接控制行业暴露时，两个报告层的用途容易混淆。
- 决策: 保持 `scan` 作为单因子 Top N 研究入口；多因子综合排序使用 Phase 3 `score`，行业中性化另按 D41 单独设计。
- 关联: Plan 第 10 节因子标准化；Plan 第 14 节打分层设计；Phase 1a-6 scan 约束；Phase 3 综合评分。

### D22. 日报已形成可用闭环，但不重算上游研究

- 现状: Phase 7 已有 `ashare daily-report`，能汇总显式 `scan`、`scoring`、`backtest`、`event_study` 与可选 `factor_validation` artifacts，并输出日报、候选、变动和 data quality gate；日报命令只汇总显式 artifacts，不在命令内重算因子、评分、回测或事件研究。
- 触发: 当需要正式每日研究报告或研究员日常复盘时，当前候选报告和评分报告仍是分散产物，不能替代完整日报。
- 决策: 保持日报作为审计汇总层；后续增强应先让上游 run 显式产出所需 artifacts，再由日报读取，避免隐式重算造成复现口径不清。
- 关联: Plan 第 15 节报告生成；Phase 1a-6 候选清单；Phase 3 综合评分。

### D23. 核心行情表已增加 source 隔离，仍缺正式快照层

- 现状: Phase 8 已为 `daily_prices`、`securities`、`trading_calendar` 增加 `source` 字段，并让 real pilot / fixture ingest 按 source 写入和 bounded replace；as-of、因子、验证、评分、回测和日报 gate 可显式传入 `--data-source`。
- 触发: 当同一 DuckDB 同时写入 fixture ingest 与真实数据 ingest 时，缺少 source 的表可能被不可审计地覆盖。
- 决策: 当前先采用表内 source 隔离；后续若需要强复现、跨供应商冲突管理或生产发布，应补正式数据快照层和来源优先级。
- 关联: Phase 1a-7 real data ingest pilot；Plan 第 6 节核心数据表。

### D24. 历史沪深 300 PIT 成分导入入口已落地，可靠数据源仍需外部提供

- 现状: Phase 8 增加 `ashare ingest-index-members`，支持 CSV / Parquet 导入 `index_code`、`stock_code`、进入 / 退出日期、披露时间、生效日期、`source` 和 `source_tag`；`current_snapshot` 会显式标记，formal 历史验证和回测要求 `historical_pit`。
- 触发: 当回测或 as-of 查询需要严格使用历史沪深 300 PIT universe 时，当前快照不能倒推成历史成分。
- 决策: 仓库提供可审计入口和校验，不伪造商业历史库；后续仍需接入可靠历史成分源或持续自建快照。
- 关联: Plan 第 6 节指数成分与 Point-in-Time 规则；Phase 1a-7 universe ingest。

### D25. --max-symbols 只是试点限流

- 现状: Phase 1a-7 的 `--max-symbols` 只按 `stock_code` 升序抽取少量股票，用于真实数据接入试点、缓存和报告验证。
- 触发: 当进入正式沪深 300 或更大 universe 接入时，抽样会造成覆盖率和质量报告不代表完整 universe。
- 决策: 后续明确撤除 `--max-symbols`、替换为正式分批 ingest，或把抽样标记提升为数据快照元数据。
- 关联: Phase 1a-7 CLI；Plan 第 5 节数据层与第 16 节 CLI 运行。

### D26. AkShare provider 已加固试点能力，仍非生产数据平台

- 现状: Phase 8 为 `src/ashare/ingest/akshare_provider.py` 增加 capability check、字段映射版本、基础重试 / 限速和可分类 provider 错误；质量报告会记录 capability check 结果，CSV fallback 仍必须显式 opt-in。
- 触发: 当真实源网络不稳定、AkShare API 改名 / 改字段、接口限流，或需要定期批量接入完整沪深 300 时，当前薄封装可能导致 ingest 失败或质量报告频繁暴露字段缺失。
- 决策: 当前仍定位为真实数据试跑入口，不承诺生产级 SLA、熔断、全量补数、字段漂移自动修复或多 provider 仲裁。
- 关联: Phase 1a-7 AkShare provider；Plan 第 21 节免费数据源字段变更风险。

### D27. 回测暂不处理公司行为现金流

- 现状: Phase 1b 组合回测使用未复权开盘价成交、收盘价估值，并使用复权价只计算合成基准收益；组合账本没有分红、送转、配股或除权除息现金流。
- 触发: 当样本跨越真实除权除息日或需要精确复盘长期组合现金收益时，当前 NAV 会缺少公司行为现金流调整。
- 决策: 本 phase 不实现公司行为现金流；后续接入可靠公司行为表后，再统一定义组合持仓、现金和复权价格之间的账务关系。
- 关联: Plan 第 12 节回测假设；`docs/backtest_assumptions.md`。

### D28. 回测暂不处理 A 股 100 股整数手和零股卖出细节

- 现状: 已在 Phase 8 后补齐基础 A 股数量规则：买入按 `trading_rules.board_lot_size` 向下舍入到 100 股整数手；卖出按整数手向下舍入，并可按 `allow_odd_lot_sell` 一次性卖出未拆分的零股余额。无法形成一手或完整零股块的订单会在 `trade_ledger.csv` 中记录 `reject_reason = below_board_lot`。
- 触发: 当回测资金规模较小、目标权重较细或需要模拟真实交易订单数量时，整数手约束会影响可成交数量、现金余额和跟踪误差。
- 决策: 当前只实现基础数量舍入和零股清仓，不实现最小价格单位、盘口队列、撤单、部分成交或交易所更细规则。
- 关联: Plan 第 12 节回测假设；Phase 1b broker。

### D29. 当前 schema 缺少真实指数行情表，基准为合成基准

- 现状: `src/ashare/storage/schema.sql` 没有指数日行情表；Phase 1b 只能基于同一 PIT universe 构造市值加权和等权合成基准。`benchmark.real_index.enabled = true` 会 fail-fast，避免静默伪装成真实指数基准。
- 触发: 当报告需要对比真实沪深 300、中证 500 或其他指数官方收益时，合成基准不能替代真实指数。
- 决策: 本 phase 不接入真实指数行情；后续新增指数行情 ingest 和 schema 后，再在 backtest benchmark 中加入真实指数基准。
- 关联: Plan 第 6 节核心表；Plan 第 12 节回测假设。

### D30. 回测未实现部分成交、盘口深度和成交量约束

- 现状: Phase 1b 只判断停牌、涨跌停、退市和缺价；通过检查后即按目标金额一次性成交，不限制成交量、盘口深度或冲击成本。
- 触发: 当组合规模变大、股票流动性较低或需要接近真实订单执行时，一次性全额成交会低估交易成本和不可成交风险。
- 决策: 本 phase 不实现部分成交和成交量约束；后续在有可靠成交量、盘口或冲击成本假设后增加撮合模型。
- 关联: Plan 第 12 节回测假设；Phase 1b broker。

### D31. 回测暂不做风格归因和行业归因

- 现状: Phase 1b 输出收益、回撤、成本、换手和相对合成基准表现，但不拆解风格暴露、行业暴露或行业归因。
- 触发: 当组合相对基准的收益需要解释为风格、行业或个股贡献时，当前指标不足以支持归因分析。
- 决策: 本 phase 不实现复杂风格归因和行业归因；后续在组合回测稳定后结合行业分类和风格因子补齐。
- 关联: Plan 第 12 节回测假设；Plan 第 14 节打分层设计。

### D32. backtest 审计链路已落地，仍无回测明细结果表

- 现状: Phase 5 已让 `ashare backtest` 写入 `research_runs`、`research_run_inputs`、`research_artifacts` 和 `run_manifest.json`，回测报告 Markdown / CSV 可按 `run_id` 查回。
- 触发: 当需要跨运行查询回测历史、审计参数、关联 git sha 或统一管理报告索引时，仅靠文件产物不足。
- 决策: MVP 已解决回测 run 审计和产物索引；仍不新增回测结果明细数据库表，不改变回测撮合、调仓或指标核心逻辑。
- 关联: D16 显式 universe 快照；D18 单因子验证结果未持久化；Plan 第 6 节 `research_runs`。

### D33. 真实公告源接入未落地

- 现状: Phase 2 只支持 CSV 公告源、fixture 公告正文和 fixture LLM response，不接入巨潮、交易所或第三方真实公告接口。
- 触发: 当研究流程需要每日真实公告增量、公告补录或跨来源校验时，CSV fixture 路径不能覆盖真实源分页、限流、字段漂移和公告正文格式差异。
- 决策: 真实公告源接入留给后续 Phase 2.5，单独设计 provider contract、缓存、质量报告和失败恢复，不混入 Phase 2 硬验收路径。
- 关联: Phase 2 公告与 LLM 解析；Plan 第 5 节数据层；Plan 第 21 节免费数据源字段变更风险。

### D34. 跨 source 的同一逻辑公告暂不自动合并

- 现状: Phase 2 的公告去重只使用 `(source_tag, announcement_id)`，不同 `source` / `source_tag` 下的同一逻辑公告允许并存。
- 触发: 当 CSV、真实公告源、交易所镜像或补录源同时写入同一 DuckDB 时，同一公告可能因为来源不同而重复出现。
- 决策: 本 phase 不做跨 source 身份归并；后续需要引入公告规范化身份、来源优先级和冲突审计后再合并。
- 关联: Phase 2 `announcements.source` / `source_tag`；D23 数据源隔离；Plan 第 6 节核心数据表。

### D35. 公告更正版 / 版本合并未实现

- 现状: Phase 2 不建模公告更正、补充、撤回或版本链，解析结果只绑定当前入库的单条公告。
- 触发: 当上市公司发布更正版公告或交易所披露补充材料时，旧版本与新版本之间的事实冲突可能影响研究证据解释。
- 决策: 本 phase 不处理版本合并；后续真实公告源稳定后再设计公告版本关系、有效版本选择和解析结果失效规则。
- 关联: Phase 2 公告正文保存；D33 真实公告源接入；Plan 第 7 节 Point-in-Time 规则。

### D36. candidate report 暂不注入 LLM 公告摘要

- 现状: Phase 2 只把 LLM 解析结果写入独立表，candidate report 仍只使用因子和规则风险提示，不展示 LLM 公告摘要。
- 触发: 当研究员希望在候选清单中直接看到新增公告摘要、催化剂或风险提示时，需要显式定义报告口径和 PIT 可见性。
- 决策: 本 phase 不把 LLM 结果接入 candidate report；后续报告增强时再以只读方式引入，并保持不影响排序和总分。
- 关联: Phase 2 LLM 解析结果表；D22 candidate report 差距；Plan 第 15 节每日研究报告。

### D37. OpenAI-compatible LLM client 仍是未产品化薄封装

- 现状: Phase 2 硬验收只覆盖 `FixtureLLMClient`；`OpenAICompatibleLLMClient` 只是可选路径，默认 Conda 环境和 `pyproject.toml` 未声明 `openai` optional extra，也没有重试、超时、限流、token / cost budget、结构化输出约束或审计级错误分类。
- 触发: 当真实 LLM API 用于批量解析公告时，网络错误、限流、模型输出漂移、非 JSON 响应或成本失控会影响可复现性和运行稳定性。
- 决策: 后续真实 LLM 接入前，先补可选依赖声明、client contract、超时 / 重试 / 限流 / token budget、结构化输出约束和 smoke test；默认仍保持 fixture 模式可离线验收。
- 关联: Phase 2 LLM client；Plan 第 13 节 LLM 层设计；Plan 第 21 节风险。

### D38. 综合评分 run 索引已落地，仍无评分明细结果表

- 现状: Phase 5 已让 `ashare score` 写入 `research_runs`、`research_run_inputs`、`research_artifacts` 和 `run_manifest.json`，包括 strict gate 失败路径的审计记录和实际已生成文件索引；仍不新增评分结果明细表。
- 触发: 当需要跨日期查询历史综合评分、比较不同权重配置、做线上报告检索或统一审计运行状态时，文件目录不足以支撑稳定机器查询。
- 决策: MVP 已解决评分报告级 run 审计和产物索引；后续如需服务直接查询历史评分明细，再设计数据库摘要表。
- 关联: Phase 3 综合评分；D18 单因子验证结果未持久化；D32 回测产物仅以文件形式保存。

### D39. LLM event_score 需要事件研究验证后才能启用

- 现状: Phase 3 在 `configs/scoring.yaml` 中保留 `event` 分组和 `event_score` 输出列，但默认禁用，且不读取 `announcement_llm_results` 或 `announcement_llm_evidence` 参与评分。
- 触发: 如果直接把 LLM 公告摘要、催化剂或风险抽取结果转成事件分进入总分，会绕过 Plan 要求的事件研究验证，也会放大 LLM 输出漂移对排序的影响。
- 决策: 只有当 LLM 事件信号先落成可审计因子或事件表，并通过事件研究 / 单因子验证后，才允许在后续 phase 中启用 `event_score`。
- 关联: Phase 2 LLM 解析；Phase 3 综合评分；Plan 第 13 节 LLM 层设计；Plan 第 14 节打分层设计。

### D40. 软风险因子尚未全部由因子层稳定落库

- 现状: Phase 3 只实现 `risk_penalty` 框架，默认 `risk_penalty.factors` 为空；评分层不从 `risk_events`、财报原表或 LLM 解析表临时生产风险因子。
- 触发: 当需要把质押、减持、问询函、监管处罚、非标审计、公告风险或财务质量风险纳入软扣分时，缺少稳定落库且已验证的 `factor_values` 风险因子会导致扣分口径不可复现。
- 决策: 后续应先把软风险信号作为普通因子生产、写入 `factor_values` 并通过验证门槛，再接入 `risk_penalty`；评分层继续只消费已验证因子。
- 关联: Phase 3 综合评分；Plan 第 9 节风险因子；Plan 第 14 节打分层设计；Phase 2 LLM 解析。

### D41. scoring 暂不做行业中性化

- 现状: `configs/scoring.yaml` 已保留 `normalization.industry_neutral.enabled: false` 配置位置，但 Phase 3 标准化只做全市场横截面 percentile rank，不做行业内标准化、行业暴露约束或行业配额。
- 触发: 当综合评分候选集中于少数行业，或需要与行业中性组合构建衔接时，当前总分可能混入行业暴露影响。
- 决策: 后续单独设计行业中性化口径、行业分类 PIT 依赖、缺失行业处理和报告披露；不在 Phase 3 MVP 中隐式启用。
- 关联: Phase 3 综合评分；Plan 第 10 节因子标准化；Plan 第 14 节打分层设计。

### D42. scoring 权重敏感性不是权重优化

- 现状: Phase 3 的 `weight_sensitivity.csv` 只对配置权重做固定比例上 / 下扰动并输出 rank correlation、Top N overlap 和 score delta，不做参数寻优、网格搜索、walk-forward 或自动调权。
- 触发: 当用户把敏感性诊断误读为最优权重选择，或希望根据历史表现自动生成权重时，当前结果不足以支持生产级调权决策。
- 决策: 保持权重敏感性作为诊断报告；后续如需权重优化，必须先定义样本外验证、过拟合控制、约束条件和审计输出。
- 关联: Phase 3 权重敏感性测试；Plan 第 14 节打分层设计；Plan 第 12 节回测假设。

### D43. scoring MVP 审计链路已解决，仍缺真实数据快照层

- 现状: Phase 5 已为 scoring 记录 `research_runs`、`config_hash`、`data_snapshot_id`、`git_sha`、`worktree_clean`、`validation-dir` 文件 sha256、`factor_values` metadata fingerprint 和输出 artifact sha256。
- 触发: 当需要长期复现某次综合评分、比较不同数据版本或把评分报告纳入服务化查询时，仅靠本地文件路径和松散 metadata 不足。
- 决策: MVP 已解决评分 run 的审计链路；仍不把 metadata fingerprint 误称为完整物理快照，后续如需强复现应补真实数据快照层。
- 关联: Phase 3 综合评分；D16 显式 universe 快照；D18 单因子验证结果未持久化；D38 综合评分产物暂不写入数据库或 run 索引。

### D44. 服务层已读取正式 run/artifact index，仍缺生产级查询能力

- 现状: Phase 5 服务层优先读取 DuckDB 中的 `research_runs` 与 `research_artifacts`，并新增 `/api/v1/runs`、`/api/v1/runs/{run_id}`、`/api/v1/runs/{run_id}/artifacts` 和 `/api/v1/runs/{run_id}/manifest`；DuckDB 缺表或不可用时仍 fallback 到 Phase 4 文件扫描。
- 触发: 当需要跨运行稳定检索、审计某次报告输入、比较不同数据快照或按 run 状态治理产物时，文件 registry 不足以替代结构化运行记录。
- 决策: MVP 已解决服务层读取正式 run/artifact index；后续仍需生产级分页、权限、远程部署和更丰富的查询筛选。
- 关联: Phase 4 服务；Plan 第 18 节服务化；D18；D32；D38；D43。

### D45. 服务默认仅本地使用，未实现多用户鉴权

- 现状: Phase 4 服务默认绑定 `127.0.0.1`，workflow API 默认关闭，仅对 workflow 触发保留单值 token 配置，不实现用户系统。
- 触发: 当服务需要供多人访问、跨机器访问或接入共享网络时，需要用户身份、会话、权限边界和审计日志。
- 决策: 本 phase 只服务本地研究复盘，不实现登录、RBAC、多用户权限或公网暴露。
- 关联: Phase 4 本地服务；Plan 第 18 节服务化。

### D46. 定时任务为进程内调度，未实现 durable queue

- 现状: Phase 4 使用 APScheduler 作为本地进程内 scheduler，任务状态只写 workflow run JSON 日志，没有持久化队列、重试队列或跨进程协调。
- 触发: 当任务需要跨进程恢复、失败重试、可观测队列状态或多节点运行时，进程内 scheduler 不具备 durable queue 语义。
- 决策: 本 phase 不引入 Celery、Redis、数据库队列或分布式调度；后续如需生产任务平台再单独设计。
- 关联: Phase 4 service-scheduler；D54。

### D47. 本 phase 选择轻量 Web 查询，未实现真实报告推送

- 现状: Phase 4 仅提供本地 HTML 查询页和 API 读取已有报告，不发送邮件、企业微信、钉钉、飞书或 webhook。
- 触发: 当每日研究报告需要主动分发、失败告警或发送到团队协作工具时，需要单独设计推送通道、重试和密钥管理。
- 决策: 报告推送留给后续 phase；本 phase 不写任何真实 webhook、token 或推送集成。
- 关联: Plan 第 15 节每日研究报告；Phase 4 Web 查询。

### D48. Web 查询不是完整前端产品

- 现状: Phase 4 的 Web 页面是无构建链路的轻量 HTML，只展示服务状态、artifact 列表和查询入口，不提供完整交互式前端。
- 触发: 当研究员需要多维筛选、图表、报告对比、历史趋势和可保存视图时，轻量页面体验不足。
- 决策: 本 phase 不引入 React、Vue、Svelte 或前端构建工具；完整 Web 产品后续单独设计。
- 关联: Phase 4 轻量 Web 查询；Plan 第 18 节服务化。

### D49. Codex Skill 仅提供 repo-local 版本，未自动安装到 CODEX_HOME

- 现状: Phase 4 在 `skills/ashare-research-lab/` 提供可复制的 repo-local Skill 文档，不自动安装到 `$CODEX_HOME/skills`。
- 触发: 当需要在任意工作区自动触发该 Skill，或团队统一分发 Skill 版本时，需要安装、发布和版本管理流程。
- 决策: 本 phase 只提交仓库内 Skill 操作说明，不修改用户全局 Codex 配置。
- 关联: Phase 4 Codex Skill；本地研究工作流。

### D50. 服务未覆盖生产部署、监控、日志聚合和告警

- 现状: Phase 4 只提供本地 FastAPI / Uvicorn 入口和 workflow JSON 日志，不包含 Docker、Kubernetes、Nginx、TLS、监控、日志聚合或告警。
- 触发: 当服务需要长期运行、多人访问、线上 SLA 或故障响应时，需要生产部署和可观测性体系。
- 决策: 本 phase 不实现生产部署；后续如需线上化再设计运行环境、监控指标、日志采集和告警规则。
- 关联: Phase 4 服务；Plan 第 18 节服务化。

### D51. 服务 Markdown HTML 预览未实现 XSS sanitization / 渲染白名单

- 现状: Phase 4 Markdown 接口只返回 raw Markdown，首页不内联渲染 Markdown，也不把报告 HTML、script、事件属性或 iframe 交给浏览器执行。
- 触发: 当 Web 页面需要直接展示 Markdown HTML 预览时，未配置 sanitizer 会带来 XSS 和 HTML 注入风险。
- 决策: 本 phase 不实现 Markdown-to-HTML；后续若做预览，必须先定义 sanitizer、标签白名单和安全测试。
- 关联: Phase 4 Web 查询；报告展示安全。

### D52. 服务无请求限速 / IP 白名单

- 现状: Phase 4 服务默认本地绑定，没有实现请求限速、IP 白名单、反向代理规则或异常流量防护。
- 触发: 当服务暴露到共享网络或公网时，查询接口和 workflow 入口需要更明确的访问控制和滥用防护。
- 决策: 本 phase 不做限速或网络边界治理；生产化前必须单独设计。
- 关联: Phase 4 FastAPI 服务；D45；D50。

### D53. token 鉴权仅使用单值环境变量，未实现轮换或细粒度权限

- 现状: Phase 4 workflow API 在显式开启后，只用 `X-Ashare-Token` 与 `ASHARE_SERVICE_TOKEN` 的单值匹配保护触发入口。
- 触发: 当多人使用、token 泄露、权限分级或定期轮换成为需求时，单值 token 不足以支撑细粒度安全管理。
- 决策: 本 phase 保持 workflow HTTP 触发默认关闭；后续如需远程触发，再设计 token 轮换、权限粒度和审计。
- 关联: Phase 4 Workflow API；D45。

### D54. 嵌入式 scheduler 与独立 scheduler 进程未实现跨进程互斥 / 去重

- 现状: `ashare serve --enable-scheduler` 和 `ashare service-scheduler` 共用 workflow runner，但没有跨进程锁、leader election 或重复触发保护。
- 触发: 当两个 scheduler 进程同时运行时，同一 workflow 可能重复触发，尤其会影响 workflow 写入 DB 或报告目录。
- 决策: 本 phase 只打印嵌入式 scheduler 互斥 warning，不实现 durable lock 或跨进程去重。
- 关联: Phase 4 scheduler；D46；D55。

### D55. service 只读查询 DB 与 workflow 写入 DB 仅做路径隔离，未实现 durable lock 或原子发布

- 现状: Phase 4 在 workflow 执行前检查 step `--db-path` 是否等于服务查询 DB，默认使用独立 workflow 写入 DB；服务只读查询 DB 与 workflow 写入 DB 只做路径隔离。
- 触发: 当需要把 workflow 结果发布给服务查询 DB、处理并发读写或保证查询看到一致快照时，需要 durable lock、原子替换或版本化发布机制。
- 决策: 本 phase 不实现 DuckDB 并发写协调、原子发布或 run snapshot 发布流程；后续正式服务化时再设计。
- 关联: Phase 4 workflow runner；只读查询 DB；workflow 写入 DB；D44。

## 低优先

### D14. 无 pre-commit / lint hook

- 现状: `pyproject.toml` 有 ruff / mypy 配置片段，但没有 pre-commit、lint hook 或统一格式化入口。
- 触发: Python 文件增多或 CI 落地后，导入顺序、行宽和类型注解风格会逐步漂移，开发者也会更晚发现格式问题。
- 决策: 暂不接 pre-commit；后续可在 CI 之后补最小 ruff/format hook。
- 关联: D13。

### D15. data/raw、data/snapshots .gitkeep 已存在

- 现状: `data/raw/.gitkeep` 与 `data/snapshots/.gitkeep` 已存在，新 clone 后目录会保留。
- 触发: 文档、脚本或用户操作假定这些目录已存在时，会出现路径错误或额外手工创建步骤，并影响真实数据快照接入前的 onboarding。
- 决策: 该目录占位问题已解决；后续真实数据快照策略仍应避免提交 DuckDB、cache、报告正文或大体积原始数据。
- 关联: Plan 第 5 节目录结构。
