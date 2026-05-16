# Phase 8 Goal: followups 修复与真实研究数据就绪

请在已完成 Phase 7 的 `/Users/crazy/own_project/ashare-research-lab` 仓库中继续实现 Phase 8：followups 修复与真实研究数据就绪。

本 phase 的目标不是继续堆新报告或新界面，而是把当前已经可运行的本地离线研究系统，推进到可以更严肃地接入真实 A 股历史数据的状态。重点是修正已经过期的工程债记录，补齐真实数据接入前会影响 PIT、覆盖率、审计和复现可信度的基础能力。

## 背景

当前仓库已经具备：

- 本地 fixture 研究闭环。
- 真实数据 ingest pilot。
- `factor_values` 落库和应用层重复键治理。
- 单因子验证、候选清单、综合评分、回测、事件研究、日报和单股报告。
- `research_runs`、`research_run_inputs`、`research_artifacts` 与 `run_manifest.json` 审计链路。
- 本地 FastAPI 查询、workflow、scheduler 和 repo-local Skill。

当前系统可以作为本地离线研究实验版使用，但还不适合直接用作真实 A 股每日正式研究系统。主要缺口集中在：

- `docs/planning/followups.md` 和部分文档已经与当前实现不一致。
- 真实沪深 300 历史 PIT 成分库尚未落地。
- 部分核心表缺少 `source` 或等价数据源隔离字段，真实源和 fixture / fallback 共库风险高。
- `factor_values` 缺少物理唯一键和正式 migration 序列。
- 覆盖率验证缺少显式 universe 快照，仍可能从因子行推断分母。
- AkShare provider 仍是试点薄封装，缺少生产化前的重试、限速、字段版本探测和 smoke check。
- 仓库没有 CI，无法自动保护当前 293 个测试覆盖的行为。

## 目标

1. 修复 `followups.md` 与当前实现不一致的条目。
2. 修复 `docs/backtest_assumptions.md` 中已经过期的 backtest 审计描述。
3. 建立最小 schema migration 机制，停止只靠零散 `CREATE TABLE IF NOT EXISTS` / `ALTER TABLE` 演进关键表结构。
4. 为 `factor_values` 增加正式唯一键或等价唯一索引 / 约束治理，并提供旧库兼容升级路径。
5. 增加显式 universe snapshot 机制，让因子验证、日报 gate、评分和回测覆盖率不再只能从 hard filters 或已有因子行推断分母。
6. 为真实数据路径补数据源隔离能力，优先解决 `daily_prices`、`securities`、`trading_calendar` 与 fixture / real / fallback 混源风险。
7. 落地历史沪深 300 PIT 成分数据入口，至少支持可审计 CSV / snapshot 导入；如果继续使用免费源，必须在质量报告中明确披露当前快照和历史 PIT 的差异。
8. 加固 AkShare provider pilot，使真实数据试跑失败原因可分类、可重试、可审计。
9. 增加最小 CI，自动运行安装、文档一致性检查和测试。

## 非目标

- 不实现自动交易、OMS、实盘下单、交易审批或券商接口。
- 不实现生产级公网服务、RBAC、监控、告警、日志聚合或 durable scheduler。
- 不一次性补齐全 A 数据平台。
- 不新增复杂策略平台、权重自动优化、风格归因或行业归因。
- 不把 LLM 输出未经验证直接接入总分。
- 不强制接入商业数据源；但必须让可靠历史 PIT 数据可以被导入、校验和审计。

## 工作约束

- 严格遵守 `docs/planning/a-share-research-plan.md`。
- 所有 Python 命令必须在 Conda 环境 `ashare-research-lab` 中执行。
- 每个 phase 必须单独 commit。
- 所有正式运行必须显式传入日期、`run_id`、`source_run_id` 和输入 artifact id。
- 不允许用当前成分快照倒推历史 universe。
- 不允许把 fixture 数据和真实数据静默混写到同一逻辑数据源。
- schema 变更必须可重复执行，并能在已有 DuckDB 上无损升级或明确 fail-fast。
- 不提交生成的报告、DuckDB、cache、workflow 日志或公告正文。

## 任务拆分

### 1. 文档一致性修复

必须修复：

- `docs/planning/followups.md` 中 D15 过期问题：`data/raw` 与 `data/snapshots` 已有 `.gitkeep`，应标记为已解决或移出待办。
- `docs/planning/followups.md` 中 D22 过期描述：Phase 7 已有 `daily-report`，应改为“日报已形成可用闭环，但只汇总显式 artifacts，不重算因子、评分、回测或事件研究”。
- D32、D38、D43、D44 的标题和正文状态应统一：MVP 审计链路已解决，剩余问题是明细结果表、真实数据快照层、生产级查询能力等。
- `docs/backtest_assumptions.md` 中 “Backtest results are file artifacts only; this phase does not write research_runs.” 已过期，应改成 Phase 5 之后的真实状态。
- `tests/test_followups.py` 如仍强制要求已解决债务文本存在，应更新为验证当前债务清单质量，而不是保留过期条目。

验收：

- `followups.md` 不再包含已被当前实现明显解决但仍描述为未解决的条目。
- `backtest_assumptions.md` 与 `ashare backtest` 当前审计行为一致。
- 文档测试仍通过。

### 2. schema migration 与唯一键治理

必须完成：

- 增加 repo 内显式 migration 目录或等价机制，例如：

```text
src/ashare/storage/migrations/
  0001_initial.sql
  0002_pit_effective_dates.sql
  0003_run_audit.sql
  0004_source_isolation_and_factor_keys.sql
```

- `init_db` 必须按版本顺序应用 migration，并在 `schema_version` 中记录已应用版本。
- 对旧库升级时，必须先做兼容检查；发现会导致数据丢失或重复键冲突的情况时 fail-fast，并输出可执行的修复提示。
- 为 `factor_values` 建立 `(source_run_id, stock_code, trade_date, as_of_date, factor_name)` 唯一治理。DuckDB 物理约束如不可行，可使用唯一索引或迁移级重复检查加写入层强制校验，但文档必须说明实际机制。
- 更新 `configs/data_dictionary.yaml` 中 `factor_values.source_run_id` 相关描述，避免只写“当前 phase 尚不强制唯一键”。

验收：

- 新库初始化后 schema version 连续可查。
- 旧 fixture DB 或测试 DB 可通过 migration 兼容路径初始化。
- 重复 `factor_values` 在 migration 或写入时明确 fail-fast。
- 相关测试覆盖新库、旧库补列、重复键和幂等初始化。

### 3. 数据源隔离

必须完成：

- 为 `daily_prices`、`securities`、`trading_calendar` 增加 `source` / `source_tag` 或等价隔离字段；如果选择不改表结构，必须提供同等可审计的数据快照隔离方案。
- 更新 ingest 写入逻辑，真实数据、fixture、CSV fallback 不能静默互相覆盖。
- `real_pilot` 的 bounded replace 必须只替换同一 source / source_tag 范围内的数据。
- 数据质量报告必须展示 source / source_tag 覆盖情况和混源检查结果。
- `as-of`、因子计算、回测、评分和日报 gate 必须明确使用哪个 source / snapshot，而不是隐式混用全库。

验收：

- 同一 DuckDB 中写入 fixture 与 real pilot 时，要么按 source 隔离可查，要么 fail-fast 要求分库。
- 混源场景有测试覆盖。
- 质量报告能显示实际使用的数据源。

### 4. 显式 universe snapshot

必须完成：

- 增加 `universe_snapshots` / `research_run_universe` / `factor_run_universe` 等等价表，用来保存每次正式因子计算的完整 universe 分母。
- `calculate-factors` 在写入 `factor_values` 时同步记录本次 `source_run_id`、`trade_date`、`as_of_date`、`index_code`、`stock_code` 和 universe 来源。
- `validate-factors` 优先使用显式 universe snapshot 计算覆盖率；只有缺失 snapshot 时才降级到 hard filter / factor row fallback，并在报告中明确 warning。
- `daily-report` data quality gate 使用 universe snapshot 验证 hard filter 和 factor 覆盖率。
- `score` 和 `backtest` 读取输入时保留 universe snapshot fingerprint，写入 `research_run_inputs`。

验收：

- 覆盖率分母不再依赖“某个因子是否写出”来推断。
- 缺失 universe snapshot 的旧 run 仍可探索性运行，但 formal 模式应 fail-fast 或明确降级策略。
- 报告中可追溯某只股票是否属于当次 universe，以及缺失因子的真实原因。

### 5. 历史沪深 300 PIT 成分入口

必须完成：

- 增加历史指数成分导入入口，至少支持 CSV / Parquet，本 phase 不强制商业 API。
- 输入字段至少包括：

```text
index_code
stock_code
in_date
out_date
in_publish_time
in_effective_date
out_publish_time
out_effective_date
source
source_tag
```

- 导入时校验区间重叠、缺失日期、重复成员、source_tag、effective_date 规则。
- 如果只能导入当前成分快照，必须以 `current_snapshot` 标记，禁止用于正式历史回测。
- `real_pilot` 质量报告继续允许当前快照试点，但 formal backtest / validation 不应把当前快照伪装成历史 PIT 成分。

验收：

- 可以用本地 fixture 构造一个有进入 / 退出历史的沪深 300 成分样本。
- `query_universe_members_as_of` 能正确按 `as_of_date` 查询历史成分。
- 回测和验证在 formal 模式下能识别 universe 是 historical PIT 还是 current snapshot。

### 6. AkShare provider 加固

必须完成：

- 增加 provider capability check，记录可用 API、字段映射版本和 provider version。
- 对网络错误、接口空结果、字段缺失、字段类型异常、限流和缓存缺失做可区分错误分类。
- 增加基础重试、超时和限速配置，默认保守。
- 将 AkShare smoke check 结果写入质量报告或 run input metadata。
- 保持 `csv_fallback` 显式 opt-in，不允许真实源失败后静默 fallback。

验收：

- provider 单元测试覆盖成功、字段缺失、空结果、网络失败和 fallback。
- 质量报告能说明真实数据来自 AkShare、cache 还是 CSV fallback。
- 失败时错误信息能指导用户下一步操作。

### 7. 最小 CI

必须完成：

- 增加 GitHub Actions 或等价 CI 配置。
- CI 至少运行：

```bash
conda env create -f environment.yml
conda run -n ashare-research-lab python -m pip install -e .
conda run -n ashare-research-lab python docs/build_data_dictionary.py
conda run -n ashare-research-lab pytest -q
```

- 如 CI 环境创建 Conda 过慢，可先用 micromamba，但环境名仍应保持 `ashare-research-lab`。
- CI 不应依赖真实网络数据源；AkShare smoke test 必须默认跳过或使用 mock，除非显式手动触发。

验收：

- PR / push 能自动运行核心测试。
- 文档生成不产生未提交差异，或 CI 明确检查生成文件一致性。

## 建议文件变更

可能新增：

```text
src/ashare/storage/migrations/
src/ashare/storage/migrator.py
src/ashare/ingest/index_members.py
src/ashare/ingest/provider_checks.py
tests/test_storage_migrations.py
tests/test_universe_snapshots.py
tests/test_index_member_ingest.py
tests/test_provider_checks.py
.github/workflows/ci.yml
```

可能修改：

```text
src/ashare/storage/schema.sql
src/ashare/storage/db.py
src/ashare/factors/store.py
src/ashare/factors/calculator.py
src/ashare/validation/runner.py
src/ashare/backtest/signals.py
src/ashare/scoring/loaders.py
src/ashare/reports/data_quality_gate.py
src/ashare/ingest/real_pilot.py
src/ashare/ingest/quality.py
src/ashare/ingest/akshare_provider.py
src/ashare/cli.py
configs/data_dictionary.yaml
configs/data.yaml
docs/backtest_assumptions.md
docs/data_dictionary.md
docs/planning/followups.md
tests/test_followups.py
```

不得提交：

```text
data/reports/generated/
data/processed/*.duckdb
data/service/
data/raw/cache/
data/raw/announcements/
tests/fixtures/generated/
```

## 验收命令

完成本 phase 前至少运行：

```bash
conda run -n ashare-research-lab python -m pip install -e .
conda run -n ashare-research-lab python docs/build_data_dictionary.py
conda run -n ashare-research-lab pytest -q
```

如果新增 migration 或历史成分导入 CLI，还需要增加相应 CLI smoke test，使用 fixture / mock 数据，不依赖外部网络。

## 完成定义

本 phase 完成时应满足：

- `followups.md` 只登记真实未解决或部分解决的问题，不再保留明显过期条目。
- 真实数据接入前的关键风险有明确机制治理：source 隔离、universe snapshot、schema migration、factor 唯一键、历史 PIT 成分入口。
- formal 报告不能在缺少关键真实数据治理的情况下生成看似正常的结果。
- 所有新增或修改能力都有测试覆盖。
- `pytest -q` 通过。
