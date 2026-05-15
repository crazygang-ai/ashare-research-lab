# Phase Followups

本文件登记前置 phase 已识别但当前系列 phase 暂不解决的工程债。D 系列编号来自 phase 1a-4.5 review 中的工程债扫描，保留编号是为了便于后续审计回溯。

## 高优先

### D1. effective_date 不区分盘前 / 盘中 / 盘后

- 现状: `src/ashare/pit/effective_date.py` 与各 ingest 路径只落到 date 级 `effective_date`，不能表达盘前 / 盘中 / 盘后披露对当日交易信号的差异。
- 触发: 当系统接入真实公告、财报或盘中运行时，同一天披露时间会影响是否可在 `as_of_date` 使用该信息。
- 决策: 待 phase 1a-5 之后统一决策是否引入 timestamp 级可见性，短期继续保持 date 级 PIT 口径并在报告中披露。
- 关联: Plan 第 7 节 Point-in-Time 规则。

### D2. factor_values 无唯一键

- 现状: `src/ashare/storage/schema.sql` 中 `factor_values` 没有 `(stock_code, trade_date, factor_name, as_of_date, source_run_id)` 或等价 PRIMARY KEY。
- 触发: 当重复运行同一批因子并写入同一数据库时，重复行会污染验证报告、回测输入和审计追踪。
- 决策: 待写入策略稳定后增加唯一键或 upsert 语义；本 phase 不改 schema。
- 关联: Phase 1a-4 因子写入路径。

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
- 决策: 真实数据 ingest 落地前设计独立增量写入路径；本 phase 不重构 ingest_local。
- 关联: Phase 1a-2 / 1a-3 ingest 设计。

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
- 触发: 多人协作、长期分支开发或 Phase 1a-5 生成验证报告后，未运行验收命令的提交可能进入主线并造成产物漂移。
- 决策: 待项目进入持续迭代阶段后增加最小 CI，至少覆盖 `pip install -e .`、文档生成和 `pytest -q`。
- 关联: Plan 第 20 节测试要求。

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
