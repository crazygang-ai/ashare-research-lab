# Phase Followups

本文件登记前置 phase 已识别但当前系列 phase 暂不解决的工程债。D 系列编号来自 phase 1a-4.5 review 中的工程债扫描，保留编号是为了便于后续审计回溯。

## 高优先

### D1. effective_date 不区分盘前 / 盘中 / 盘后

- 现状: `src/ashare/pit/effective_date.py` 与各 ingest 路径只落到 date 级 `effective_date`，不能表达盘前 / 盘中 / 盘后披露对当日交易信号的差异。
- 触发: 当系统接入真实公告、财报或盘中运行时，同一天披露时间会影响是否可在 `as_of_date` 使用该信息。
- 决策: 待真实公告 / 财报数据接入或盘中运行需求出现时，统一决策是否引入 timestamp 级可见性；短期继续保持 date 级 PIT 口径并在报告中披露。
- 关联: Plan 第 7 节 Point-in-Time 规则。

### D2. factor_values 无唯一键

- 现状: `src/ashare/storage/schema.sql` 中 `factor_values` 没有 `(stock_code, trade_date, factor_name, as_of_date, source_run_id)` 或等价 PRIMARY KEY。
- 触发: 当重复运行同一批因子并写入同一数据库时，重复行会污染单因子验证、候选清单排序、回测输入和审计追踪。
- 决策: Phase 1a-5 已在 `src/ashare/validation/runner.py` 对重复验证输入 fail-fast；Phase 1a-6 已在 `src/ashare/scan/candidates.py` 对候选扫描输入 fail-fast。待写入策略稳定后仍应增加唯一键或 upsert 语义。
- 关联: Phase 1a-4 因子写入路径；Phase 1a-5 单因子验证输入检查；Phase 1a-6 候选扫描输入检查。

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

### D5. schema_version 不演进

- 现状: `schema_version` 表存在，但没有真实迁移序列、版本演进规则或 schema 变更校验流程。
- 触发: 一旦需要变更表结构、补唯一键或回填历史数据，缺少迁移记录会使本地数据库状态不可审计。
- 决策: 待 schema 进入稳定期后建立显式 migration 序列；Phase 1a-4.5 只登记不实现。
- 关联: `src/ashare/storage/schema.sql`。

### D6. ingest_local 是清表重写，不能用于真实数据

- 现状: `src/ashare/ingest/local.py` 的 `ingest_local` 面向 fixture 和本地快照，采用清表重写而不是增量 / upsert。
- 触发: 接入真实 AkShare 数据、增量行情或多来源快照时，清表会破坏历史审计和并发运行安全。
- 决策: Phase 1a-7 已新增独立的 `src/ashare/ingest/real_pilot.py` 真实数据试点路径，不复用 `ingest_local` 的清表重写语义；`ingest_local` 继续保持 fixture-only，后续真实数据正式化时再设计完整增量 / upsert 机制。
- 关联: Phase 1a-2 / 1a-3 ingest 设计；Phase 1a-7 real data ingest pilot。

### D16. factor_values 缺少显式验证 universe 快照

- 现状: `factor_values` 只保存已写出的因子值，没有保存每个 `source_run_id` / `trade_date` 的完整 universe；Phase 1a-5 在 `src/ashare/validation/runner.py` 中用 hard filter 行的 `stock_code` 并集推断覆盖率分母，缺失时 fallback 到同日可见因子行。
- 触发: 当 hard filter 未完整写入、局部因子重算、跨 run 比较或正式报告要求精确覆盖率时，推断分母可能高估覆盖率或掩盖 universe 变化。
- 决策: 后续正式 run / snapshot 管理落地时，引入显式 universe 快照或验证输入快照；短期保留 Phase 1a-5 的 union + fallback，并在 CLI warning 中披露。
- 关联: Phase 1a-5 覆盖率与缺失率口径；Plan 第 6 节 `factor_values`。

### D17. 单因子 forward_return 是统计标签，不是可执行收益

- 现状: `src/ashare/validation/labels.py` 使用 `close * adj_factor` 构造 close-to-close 未来收益标签，不因停牌、退市、涨跌停或不可交易状态主动剔除样本。
- 触发: 当用户把 Rank IC、Top / Bottom 或 `long_short_return` 解释成可执行策略收益时，会忽略 A 股交易约束、成交价、停牌、涨跌停、退市和成本。
- 决策: Phase 1a-5 继续把 forward return 定义为单因子统计标签；交易可执行性、撮合和成本只在后续组合回测中处理，报告中必须明确区分统计标签和可执行收益。
- 关联: Plan 第 11 节单因子检验；Plan 第 12 节回测假设。

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

### D13. 无 CI 配置

- 现状: 仓库没有 GitHub Actions 或等价 CI 配置来自动运行安装、生成文档与 pytest。
- 触发: 多人协作、长期分支开发或单因子验证统计继续扩展后，未运行验收命令的提交可能进入主线并造成产物漂移。
- 决策: 待项目进入持续迭代阶段后增加最小 CI，至少覆盖 `pip install -e .`、文档生成和 `pytest -q`。
- 关联: Plan 第 20 节测试要求。

### D18. 单因子验证结果未持久化

- 现状: Phase 1a-5 的 `validate_factors` 返回 DataFrame；Phase 1a-6 已通过 `src/ashare/reports/factor_report.py` 生成 Markdown / CSV 因子验证报告，但仍不写 DuckDB 验证结果表，也不把报告元数据写入 `research_runs`。
- 触发: 当需要跨 `source_run_id` 查询历史验证结论、在数据库中审计报告生成参数，或把验证摘要稳定接入正式 run / 服务化接口时，仅靠文件报告仍不足以支撑机器查询。
- 决策: Phase 1a-6 先保留报告文件输出和只读验证流程；后续正式 run 管理落地时，再设计验证结果持久化、报告索引和 `research_runs` 关联。
- 关联: Plan 第 15 节因子验证报告；Phase 1a-5 单因子验证；Phase 1a-6 因子报告。

### D19. 单因子验证暂未覆盖分年度、分行业和换手率

- 现状: Phase 1a-5 实现覆盖率、缺失率、Rank IC、ICIR、Top / Bottom 分组收益和衰减曲线，但未实现 Plan 第 11 节列出的分年度表现、分行业表现和换手率。
- 触发: 当需要判断因子稳定性、行业结构偏误或实际调仓冲击时，当前验证摘要不足以支撑因子保留 / 剔除结论。
- 决策: 后续验证增强 phase 中补充分年度、分行业和换手率口径；其中换手率应等组合或候选池调仓规则明确后再实现，避免伪精确。
- 关联: Plan 第 11 节单因子检验。

### D20. candidate scan 风险阈值硬编码

- 现状: Phase 1a-6 候选清单的 `pe_ttm_percentile >= 0.8`、`pb_percentile >= 0.8`、`return_20d < 0`、`return_60d < 0`、`above_ma60 == 0.0` 等风险提示规则和阈值写在扫描规则中。
- 触发: 当不同市场环境、行业或研究口径需要不同风险阈值时，硬编码会降低复盘透明度并增加改代码成本。
- 决策: 后续引入 scan 配置或扩展数据字典来管理风险提示阈值；本 phase 只登记，不做配置化。
- 关联: Phase 1a-6 候选清单风险提示；Plan 第 15 节每日研究报告。

### D21. candidate scan 暂不支持多因子加权 / 行业中性化

- 现状: Phase 1a-6 候选清单只按显式传入的 `sort_factor` 排序，不做多因子加权、0-100 标准化、行业中性化或基于 ICIR 的自动调权。
- 触发: 当候选池需要综合多个维度或控制行业暴露时，单因子排序不足以表达完整研究偏好。
- 决策: 待单因子表现与候选研究流程稳定后，再设计可审计的多因子排序和行业约束；本 phase 不实现综合评分。
- 关联: Plan 第 10 节因子标准化；Plan 第 14 节打分层设计；Phase 1a-6 scan 约束。

### D22. candidate report 与 plan 第 15 节每日研究报告仍有差距

- 现状: Phase 1a-6 只输出最小候选清单、因子分项、入选原因和规则风险提示，不包含公告摘要、上一交易日新增 / 移出 / 排名变化、相对强弱或完整单股研究信息。
- 触发: 当需要正式每日研究报告或研究员日常复盘时，当前候选报告还不能替代 plan 第 15 节定义的完整报告。
- 决策: 后续在公告、LLM、组合跟踪和排名变化能力落地后补齐每日研究报告；本 phase 只登记差距。
- 关联: Plan 第 15 节报告生成；Phase 1a-6 候选清单。

### D23. daily_prices / securities / trading_calendar 缺少 source 字段

- 现状: `daily_prices`、`securities`、`trading_calendar` 没有 `source` 字段，Phase 1a-7 只能按日期或股票代码做 bounded replace，无法在表内完全隔离 fixture、AkShare 与 CSV fallback。
- 触发: 当同一 DuckDB 同时写入 fixture ingest 与真实数据 ingest 时，缺少 source 的表可能被不可审计地覆盖。
- 决策: Phase 1a-7 不修改 schema，只在 CLI 检测明显混源场景并要求使用单独 DB；后续统一评估是否补 source 或设计正式数据快照层。
- 关联: Phase 1a-7 real data ingest pilot；Plan 第 6 节核心数据表。

### D24. 历史沪深 300 PIT 成分库尚未落地

- 现状: Phase 1a-7 优先沪深 300，但免费真实源可能只给当前成分快照，无法保证完整历史进入 / 退出日期与披露时间。
- 触发: 当回测或 as-of 查询需要严格使用历史沪深 300 PIT universe 时，当前快照不能倒推成历史成分。
- 决策: 本 phase 不伪造历史 PIT 成分；质量报告标明当前快照限制，后续接入可靠历史成分源或自建定期快照。
- 关联: Plan 第 6 节指数成分与 Point-in-Time 规则；Phase 1a-7 universe ingest。

### D25. --max-symbols 只是试点限流

- 现状: Phase 1a-7 的 `--max-symbols` 只按 `stock_code` 升序抽取少量股票，用于真实数据接入试点、缓存和报告验证。
- 触发: 当进入正式沪深 300 或更大 universe 接入时，抽样会造成覆盖率和质量报告不代表完整 universe。
- 决策: 后续明确撤除 `--max-symbols`、替换为正式分批 ingest，或把抽样标记提升为数据快照元数据。
- 关联: Phase 1a-7 CLI；Plan 第 5 节数据层与第 16 节 CLI 运行。

### D26. AkShare provider 仍是试点薄封装

- 现状: `src/ashare/ingest/akshare_provider.py` 只封装 Phase 1a-7 所需的少量 AkShare API，依赖当前接口可用性和字段名映射；没有生产级重试、限速、熔断、字段版本探测或上游 schema 变更告警。
- 触发: 当真实源网络不稳定、AkShare API 改名 / 改字段、接口限流，或需要定期批量接入完整沪深 300 时，当前薄封装可能导致 ingest 失败或质量报告频繁暴露字段缺失。
- 决策: 后续真实数据路径正式化前，增加 provider capability check、版本化字段映射、重试 / 限速策略，并把 AkShare smoke 结果纳入可审计运行记录；Phase 1a-7 只保留小范围试点。
- 关联: Phase 1a-7 AkShare provider；Plan 第 21 节免费数据源字段变更风险。

## 低优先

### D14. 无 pre-commit / lint hook

- 现状: `pyproject.toml` 有 ruff / mypy 配置片段，但没有 pre-commit、lint hook 或统一格式化入口。
- 触发: Python 文件增多或 CI 落地后，导入顺序、行宽和类型注解风格会逐步漂移，开发者也会更晚发现格式问题。
- 决策: 暂不接 pre-commit；后续可在 CI 之后补最小 ruff/format hook。
- 关联: D13。

### D15. data/raw、data/snapshots 是空目录但无 .gitkeep

- 现状: 目录规划中保留 `data/raw` 与 `data/snapshots`，但空目录没有 `.gitkeep`，新 clone 后目录可能不存在。
- 触发: 文档、脚本或用户操作假定这些目录已存在时，会出现路径错误或额外手工创建步骤，并影响真实数据快照接入前的 onboarding。
- 决策: 后续在明确数据目录策略后添加 `.gitkeep` 或让脚本自动创建目录。
- 关联: Plan 第 5 节目录结构。
