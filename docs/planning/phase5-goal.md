# Phase 5 Goal: 正式 Run 审计与 Artifact 索引

请在已完成 Phase 4 的 `/Users/crazy/own_project/ashare-research-lab` 仓库中继续实现 Phase 5：正式 run 审计与 artifact 索引。

本 phase 只做研究运行审计、输入指纹、配置哈希、产物索引和服务查询衔接。它不新增因子、不改变既有选股逻辑、不重新实现回测、不引入新的真实数据源、不让 LLM 进入总分。

Phase 5 的目标是让前面已经能跑通的离线流程变成可复盘、可追踪、可被服务层稳定查询的正式研究运行。

## 背景

Phase 1a 到 Phase 4 已经具备：

- PIT 数据查询。
- 基础因子计算和 `factor_values` 落库。
- 单因子验证和因子验证报告。
- 候选清单。
- Top N 等权组合回测。
- 公告 CSV 入库和 LLM 结构化解析。
- 综合评分报告。
- 本地 FastAPI 查询服务和 artifact 文件扫描。

但当前仍有几个核心审计缺口：

- 多数 CLI 运行不写 `research_runs`。
- 报告、CSV、JSON 产物只存在于文件系统，没有结构化 artifact index。
- `factor_values.source_run_id` 与报告 run、回测 run、评分 run 之间没有统一关系。
- 服务层仍主要扫描 `data/reports/generated`，没有正式 run 索引。
- `data_snapshot_id`、`config_hash`、`git_sha`、`worktree_clean` 等字段没有贯穿研究流程。
- 重复 run、重复 `factor_values` 写入和 artifact 覆盖策略还不够清晰。

Phase 5 先补这条审计主线，再进入事件研究、完整日报或真实数据生产化。

## 目标

1. 建立统一的 run tracking 模块。
2. 将 `research_runs` 从骨架表变成真实运行审计表。
3. 新增 artifact index 表，记录每次运行输出的 Markdown、CSV、JSON 等产物。
4. 为关键 CLI 命令生成 `run_manifest.json`。
5. 记录 CLI 参数、配置哈希、输入数据指纹、输出产物哈希、git 状态和运行状态。
6. 明确 formal run 与 exploratory run 的区别。
7. 明确 `calculate-factors` 的 `source_run_id` 与 `research_runs.run_id` 关系。
8. 建立 `factor_values` 重复写入治理：默认 fail-fast，显式 overwrite 才允许替换同一 run。
9. 让服务层优先读取 artifact index，保留文件扫描 fallback。
10. 增加测试，覆盖 run 记录、artifact index、manifest、重复 run、dirty worktree、服务查询和 CLI 行为。
11. Phase 5 完成后单独 commit，提交信息为：`feat: phase 5 run audit and artifact index`。

## 工作约束

- 严格遵守 `docs/planning/a-share-research-plan.md`。
- 所有 Python 命令必须在 Conda 环境 `ashare-research-lab` 中执行。
- 每个 phase 必须单独 commit。
- 本 phase 不新增任何交易、选股、评分或回测核心逻辑。
- 本 phase 不新增新因子。
- 本 phase 不实现 `event-study`。
- 本 phase 不实现完整 `daily report` 或 `stock-report`。
- 本 phase 不接入真实公告源。
- 本 phase 不扩展 AkShare 生产级数据接入。
- 本 phase 不把 LLM 输出接入总分。
- 本 phase 不实现用户系统、权限后台、远程部署或生产监控。
- 本 phase 可以修改 DuckDB schema，但只允许新增审计 / 索引表和最小兼容 migration。
- 本 phase 不给既有核心数据表新增破坏性字段。
- 本 phase 不删除历史报告文件。
- 本 phase 不提交生成的报告、DuckDB、cache、workflow 日志或 `dist/` 打包产物。

## 命名和运行模式

Phase 5 引入两个运行模式：

```text
exploratory
formal
```

### exploratory

- 默认用于本地试验。
- 允许 dirty worktree。
- 必须记录 `worktree_clean = false`。
- 报告和 manifest 必须明确标记 `run_mode = exploratory`。
- 输出可用于研究参考，但不能被描述为正式可复盘结果。

### formal

- 用于正式研究输出。
- 必须记录完整 CLI 参数、配置哈希、git sha、worktree 状态、输入指纹和 artifact 哈希。
- 默认要求 git 工作区干净。
- 如果工作区不干净，必须 fail-fast。
- 不允许通过默认参数隐式使用当前日期、最近 run 或旧报告。

建议 CLI flag：

```text
--run-id
--run-mode exploratory|formal
--overwrite-run / --no-overwrite-run
--audit-config configs/audit.yaml
```

规则：

- `--run-id` 未传时，可以生成稳定格式的运行 ID，但必须打印出来并写入 manifest。
- 自动生成的 `run_id` 建议格式：

```text
{command}-{utc_timestamp}-{short_git_sha_or_nogit}
```

- `formal` 模式下推荐显式传入 `--run-id`，但 MVP 不强制。
- 同一 `run_id` 已存在时，默认 fail-fast。
- 只有显式传入 `--overwrite-run` 才允许覆盖同一 `run_id` 的审计记录和 artifact index。
- overwrite 必须记录在 manifest 中，不能静默覆盖。

## `source_run_id` 与 `run_id` 关系

`factor_values.source_run_id` 是因子值的来源批次 ID。Phase 5 不改名，但要明确它和 `research_runs.run_id` 的关系。

### `calculate-factors`

规则：

- `calculate-factors` 仍保留 `--source-run-id`。
- `calculate-factors` 的 `research_runs.run_id` 默认等于 `--source-run-id`。
- 如果同时传入 `--run-id` 和 `--source-run-id`，两者必须相等，否则 fail-fast。
- `factor_values.source_run_id` 必须等于本次 `research_runs.run_id`。
- 同一 `source_run_id` 下同一键已存在时，默认 fail-fast。
- 显式 `--overwrite-run` 时，先删除该 `source_run_id` 在 `factor_values` 中的既有行，再写入新结果，并在 manifest 中记录 overwrite。

`factor_values` 重复键定义：

```text
(source_run_id, stock_code, trade_date, as_of_date, factor_name)
```

Phase 5 不一定要立刻增加 DuckDB primary key，但写入路径必须在应用层 fail-fast，错误信息打印至多 5 个重复样例。

### 消费因子的命令

以下命令使用已有 `source_run_id` 作为输入，不重写 `factor_values`：

```text
validate-factors
report --kind factor-validation
scan
score
backtest
```

规则：

- 这些命令的 `research_runs.run_id` 是本次报告 / 回测 / 评分运行 ID。
- 它们消费的 `source_run_id` 必须写入 `params`、`run_inputs` 和 `run_manifest.json`。
- 不允许把消费型命令的 `run_id` 混同为因子来源 ID。

## Schema 变更

保留既有 `research_runs` 表，并新增最小 artifact / input 索引表。

### `research_runs`

沿用现有字段：

```text
research_runs
  run_id
  as_of_date
  status
  params
  config_hash
  data_snapshot_id
  git_sha
  worktree_clean
  started_at
  finished_at
  error
```

规则：

- `status` 至少取：

```text
running
succeeded
failed
aborted
```

- `params` 写入 JSON，包含：
  - `command`
  - `argv`
  - `run_mode`
  - `db_path`
  - `source_run_id`
  - `as_of_date` / `from` / `to`
  - `output_dir`
  - 其他命令参数
- `config_hash` 是本次使用的配置文件内容 hash 的组合 hash。
- `data_snapshot_id` 在本 phase 表示输入数据指纹 ID，不代表物理快照副本。
- `git_sha` 无 git 仓库时允许为空，但必须记录 warning。
- `worktree_clean` 无 git 仓库时允许为空或 false，但必须记录 warning。
- `finished_at` 在失败路径也必须写入。
- `error` 保存紧凑错误摘要，不能保存超长 traceback。

### `research_artifacts`

新增表：

```text
research_artifacts
  artifact_id VARCHAR
  run_id VARCHAR
  artifact_kind VARCHAR
  role VARCHAR
  path VARCHAR
  media_type VARCHAR
  sha256 VARCHAR
  row_count BIGINT
  size_bytes BIGINT
  created_at TIMESTAMP
  metadata_json JSON
```

字段规则：

- `artifact_id` 使用稳定 hash：

```text
sha1(run_id + "|" + role + "|" + normalized_path)
```

- `artifact_kind` 至少支持：

```text
factor_values
factor_validation
scan
scoring
backtest
announcement_parse
workflow
manifest
```

- `role` 表示文件在该 run 中的用途，例如：

```text
manifest
markdown_report
coverage_csv
rank_ic_csv
candidates_csv
scored_candidates_csv
metrics_csv
equity_curve_csv
trade_ledger_csv
metadata_json
```

- `path` 保存 repo-relative path。
- `sha256` 对文件内容计算；目录不登记为 artifact。
- `row_count` 只对 CSV / table-like artifact 尽量统计，无法统计时为空。
- `metadata_json` 保存轻量结构化补充信息，例如列名、horizon、factor_name、top_n。

### `research_run_inputs`

新增表：

```text
research_run_inputs
  input_id VARCHAR
  run_id VARCHAR
  input_kind VARCHAR
  input_ref VARCHAR
  source_run_id VARCHAR
  sha256 VARCHAR
  row_count BIGINT
  metadata_json JSON
  created_at TIMESTAMP
```

字段规则：

- `input_kind` 至少支持：

```text
duckdb_table
duckdb_query
config_file
artifact_file
cli_param
git_state
```

- `input_ref` 示例：

```text
factor_values
configs/scoring.yaml
data/reports/generated/.../ic_summary.csv
source_run_id:phase1a-fixture
```

- `source_run_id` 用于关联被消费的因子来源 run。
- DuckDB 表输入可以先记录 row count、日期范围、source_tag、最大 / 最小日期等 metadata；MVP 不要求对大表做全量内容 hash。
- 文件输入必须记录 sha256。

### Schema version

规则：

- 将 `CURRENT_SCHEMA_VERSION` 推进到 3。
- `init_db` 后必须自动创建新表。
- 旧库缺表时通过兼容 migration 补表，不丢数据。
- 不实现完整 migration framework。
- 不新增外键。
- 不新增复杂索引，除非测试证明查询太慢。

## Run manifest

每个有审计的 run 必须输出：

```text
run_manifest.json
```

默认位置：

```text
{output_dir}/run_manifest.json
```

如果命令没有显式 `--output-dir`，Phase 5 应为产物型命令提供默认目录：

```text
data/reports/generated/{artifact_kind}/{run_id}/
```

`run_manifest.json` 至少包含：

```json
{
  "schema_version": "phase5.run_manifest.v1",
  "run_id": "...",
  "run_mode": "exploratory",
  "command": "score",
  "argv": ["ashare", "score", "..."],
  "db_path": "data/processed/ashare.duckdb",
  "as_of_date": "2026-05-13",
  "source_run_id": "...",
  "status": "succeeded",
  "started_at": "...",
  "finished_at": "...",
  "config_hash": "...",
  "data_snapshot_id": "...",
  "git": {
    "sha": "...",
    "worktree_clean": true,
    "dirty_files": []
  },
  "inputs": [],
  "artifacts": [],
  "warnings": [],
  "error": null
}
```

规则：

- JSON key 顺序必须稳定，便于 diff。
- 时间使用带 timezone 的 ISO 8601 字符串。
- repo-relative path 必须统一使用 `/`。
- `dirty_files` 最多记录前 50 个路径，避免 manifest 过大。
- 失败 run 也必须尽量写出 manifest。
- 失败 run 的 artifact index 只记录实际已经写出的文件。

## 配置

新增 `configs/audit.yaml`：

```yaml
version: phase5.v1

run_tracking:
  enabled: true
  default_run_mode: exploratory
  formal_requires_clean_worktree: true
  fail_on_duplicate_run_id: true
  manifest_filename: run_manifest.json

artifacts:
  default_root: data/reports/generated
  write_manifest: true
  index_files: true
  hash_files: true
  csv_row_count: true

data_fingerprint:
  full_file_hash: true
  duckdb_table_mode: metadata
  max_dirty_files: 50

factor_values:
  duplicate_policy: fail
  overwrite_requires_flag: true
```

规则：

- `version` 必须为 `phase5.v1`。
- 配置中的相对路径按 repo root 解析。
- 不允许配置 secret。
- 如果 `run_tracking.enabled = false`，命令可以退回 Phase 4 以前的行为，但必须在 CLI 输出 warning。

## 文件变更

建议新增或修改：

```text
configs/audit.yaml
src/ashare/audit/__init__.py
src/ashare/audit/config.py
src/ashare/audit/git.py
src/ashare/audit/hashing.py
src/ashare/audit/manifest.py
src/ashare/audit/run_store.py
src/ashare/audit/artifacts.py
src/ashare/audit/fingerprint.py
src/ashare/storage/schema.sql
src/ashare/storage/db.py
src/ashare/storage/snapshots.py
src/ashare/factors/store.py
src/ashare/cli.py
src/ashare/service/artifacts.py
src/ashare/service/queries.py
src/ashare/service/app.py
docs/planning/followups.md
tests/test_audit_config.py
tests/test_audit_git.py
tests/test_audit_hashing.py
tests/test_audit_manifest.py
tests/test_audit_run_store.py
tests/test_audit_artifacts.py
tests/test_audit_fingerprint.py
tests/test_factor_store_audit.py
tests/test_run_audit_cli.py
tests/test_service_artifact_index.py
```

可选修改：

```text
.gitignore
```

仅当当前仓库未忽略打包或运行产物时，允许补充：

```gitignore
dist/
data/reports/generated/
data/service/
data/processed/*.duckdb
data/raw/cache/
data/raw/announcements/
```

不得提交：

```text
dist/
data/reports/generated/
data/service/
data/processed/*.duckdb
data/raw/cache/
data/raw/announcements/
tests/fixtures/generated/
```

## CLI 覆盖范围

Phase 5 必须优先接入这些命令：

```text
calculate-factors
validate-factors
report
scan
score
backtest
parse-announcements
```

说明：

- `calculate-factors` 写 `factor_values`，是因子来源 run。
- `validate-factors` 生成验证统计和可选报告输入。
- `report` 生成 factor validation 报告 artifact。
- `scan` 生成候选清单 artifact。
- `score` 生成综合评分 artifact。
- `backtest` 生成组合回测 artifact。
- `parse-announcements` 生成公告 LLM 解析 run 记录和解析结果索引。

可以后续接入：

```text
ingest
ingest-local
ingest-announcements
service-workflow
```

如果本 phase 时间有限，`ingest` 系列可以先只记录 workflow / manifest，不强制补全所有数据表输入指纹。

## 命令行为要求

### 成功路径

每个被 Phase 5 接入的 CLI 命令成功后必须：

1. 写入或更新 `research_runs`：
   - `status = succeeded`
   - `finished_at` 非空
   - `error = NULL`
2. 写入 `research_run_inputs`。
3. 写入 `research_artifacts`。
4. 写出 `run_manifest.json`。
5. CLI 输出 `run_id` 和 manifest path。

### 失败路径

如果命令执行失败：

1. 如果已经创建 run，必须更新 `research_runs.status = failed`。
2. 必须写入 `finished_at`。
3. 必须写入紧凑 `error`。
4. 尽量写出失败版 `run_manifest.json`。
5. 不得把失败 run 标记为 succeeded。

### 中断或提前 fail-fast

如果在创建 run 之前就因为参数错误 fail-fast，可以不写 `research_runs`，但错误信息必须明确。

如果 run 已经创建再失败，必须进入失败路径。

## Artifact path 约定

Phase 5 不强制重写所有既有 output path，但新增默认路径约定。

默认目录：

```text
data/reports/generated/{artifact_kind}/{run_id}/
```

建议映射：

```text
factor_validation -> data/reports/generated/factor_validation/{run_id}/
scan              -> data/reports/generated/scan/{run_id}/
scoring           -> data/reports/generated/scoring/{run_id}/
backtest          -> data/reports/generated/backtest/{run_id}/
announcement_parse -> data/reports/generated/announcement_parse/{run_id}/
```

如果用户显式传入 `--output-dir`：

- 使用用户路径。
- manifest 和 artifact index 仍必须记录 repo-relative path。
- 如果路径在 repo 外，必须记录 absolute path，但 CLI 输出 warning，说明跨 repo artifact 复现性较弱。

## 服务层要求

Phase 4 的服务层目前通过文件扫描构造 artifact registry。Phase 5 改为：

1. 优先读取 DuckDB 中的 `research_runs` 和 `research_artifacts`。
2. 如果 DuckDB 不存在或新表不存在，fallback 到 Phase 4 文件扫描。
3. `/api/v1/artifacts` 返回 artifact index 中的记录。
4. `/api/v1/artifacts/{artifact_id}` 返回 artifact metadata、run metadata 和文件信息。
5. `/api/v1/status` 增加：
   - `audit_schema_available`
   - `latest_run_id`
   - `latest_formal_run_id`
   - `artifact_index_available`
6. 既有 endpoint 不得因为没有 Phase 5 表而崩溃。

新增建议 endpoint：

```text
GET /api/v1/runs
GET /api/v1/runs/{run_id}
GET /api/v1/runs/{run_id}/artifacts
GET /api/v1/runs/{run_id}/manifest
```

规则：

- 服务接口仍只读。
- 不通过服务创建或修改 run。
- 不把任何结果描述为买入、卖出或交易指令。

## 数据指纹

Phase 5 不要求实现完整物理数据快照，但必须实现输入指纹，避免误称不可复现。

### 文件输入

文件输入必须记录：

- repo-relative path。
- sha256。
- size_bytes。
- modified time 可选。

### 配置输入

配置文件必须记录：

- path。
- sha256。
- 参与组合 `config_hash`。

至少覆盖：

```text
configs/factors.yaml
configs/validation.yaml
configs/backtest.yaml
configs/scoring.yaml
configs/llm.yaml
configs/service.yaml
configs/audit.yaml
configs/data_dictionary.yaml
```

只记录实际被该命令使用的配置文件。

### DuckDB 输入

DuckDB 输入 MVP 记录 metadata fingerprint：

- table name。
- row count。
- relevant date range。
- `source_run_id`。
- `source` / `source_tag` distinct values，如果表有这些字段。
- query predicate 摘要。

规则：

- 不把 metadata fingerprint 描述为完整数据快照。
- `data_snapshot_id` 可以使用以下格式：

```text
fingerprint:{sha256}
```

- 后续如实现物理快照，再升级为真正 snapshot ID。

## Git 状态

新增 git helper：

```text
get_git_sha()
get_worktree_status()
is_worktree_clean()
```

规则：

- 使用非交互式 git 命令。
- 不修改 git 状态。
- 不自动 add / commit。
- dirty 文件列表必须包含 untracked 文件。
- `dist/` 如果未忽略，会导致 formal run fail-fast。
- 无 git 仓库时，exploratory 允许继续，formal 默认 fail-fast。

## 与 followups 的关系

Phase 5 主要解决或部分解决：

- D2：`factor_values` 无唯一键。
- D16：`factor_values` 缺少显式验证 universe 快照。
- D18：单因子验证结果未持久化。
- D32：backtest 不写 `research_runs`。
- D38：综合评分产物暂不写入数据库或 run 索引。
- D43：scoring 尚未接入正式 run 快照和数据版本审计。
- D44：服务层暂用文件 artifact registry，未接入正式 `research_runs`。

Phase 5 不解决：

- D1：timestamp 级 PIT。
- D19：单因子分年度、分行业和换手率。
- D22：完整每日研究报告。
- D24：历史沪深 300 PIT 成分库。
- D33：真实公告源接入。
- D39：LLM event_score。
- D45-D55：生产级服务、安全、调度和发布能力。

完成 Phase 5 时必须更新 `docs/planning/followups.md`，把已解决、部分解决和仍保留的债务说清楚。

## 测试要求

新增测试必须覆盖：

1. `configs/audit.yaml` 加载和默认值。
2. git sha、dirty worktree、untracked 文件检测。
3. 文件 sha256 和 CSV row count。
4. `run_manifest.json` key 顺序、必填字段和失败路径。
5. `research_runs` 创建、成功更新、失败更新。
6. duplicate `run_id` 默认 fail-fast。
7. `--overwrite-run` 显式覆盖路径。
8. `research_artifacts` 写入、查询和 hash 校验。
9. `research_run_inputs` 写入配置文件、DuckDB 表和 source_run_id。
10. `calculate-factors` 中 `run_id == source_run_id` 规则。
11. `factor_values` 重复键 fail-fast。
12. `formal` 模式 dirty worktree fail-fast。
13. `exploratory` 模式 dirty worktree 允许继续但 manifest 标记 dirty。
14. `scan` / `score` / `backtest` 成功生成 manifest 和 artifact index。
15. 服务层优先读取 artifact index。
16. 服务层在无 Phase 5 表时仍能 fallback 到文件扫描。
17. 失败 CLI 不把 run 标记为 succeeded。

测试不得依赖：

- 真实网络。
- 真实 AkShare 可用性。
- 真实 OpenAI 或其他 LLM API。
- 用户本地未提交状态。

git dirty 相关测试必须使用临时 git repo 或 monkeypatch helper，不得依赖当前仓库真实状态。

## 验收命令

Phase 5 完成后至少运行：

```bash
conda run -n ashare-research-lab python -m pip install -e .
conda run -n ashare-research-lab pytest -q
conda run -n ashare-research-lab ashare --help
```

并使用 fixture 数据跑一条最小审计链路：

```bash
conda run -n ashare-research-lab python scripts/build_fixtures.py

conda run -n ashare-research-lab ashare ingest-local \
  --input-dir tests/fixtures/generated \
  --db-path data/processed/phase5_fixture.duckdb

conda run -n ashare-research-lab ashare calculate-factors \
  --from 2026-03-30 \
  --to 2026-06-26 \
  --db-path data/processed/phase5_fixture.duckdb \
  --index-code LOCAL_FIXTURE \
  --source-run-id phase5-fixture-factors \
  --run-mode exploratory

conda run -n ashare-research-lab ashare report \
  --kind factor-validation \
  --from 2026-03-30 \
  --to 2026-06-26 \
  --db-path data/processed/phase5_fixture.duckdb \
  --source-run-id phase5-fixture-factors \
  --run-id phase5-fixture-factor-report \
  --run-mode exploratory

conda run -n ashare-research-lab ashare scan \
  --as-of 2026-06-26 \
  --db-path data/processed/phase5_fixture.duckdb \
  --source-run-id phase5-fixture-factors \
  --index-code LOCAL_FIXTURE \
  --sort-factor return_20d \
  --run-id phase5-fixture-scan \
  --run-mode exploratory
```

验收时必须确认：

- `research_runs` 至少包含上述 factor、report、scan 三个 run。
- 每个 succeeded run 都有 `finished_at`。
- 每个 artifact-generating run 都有 `run_manifest.json`。
- `research_artifacts` 能查到对应 Markdown / CSV / manifest。
- `run_manifest.json` 中的 artifact sha256 与实际文件一致。
- 服务 API 能查到 indexed artifact。

本验收命令会生成本地运行产物，完成后不得提交这些产物。

## MVP 完成标准

Phase 5 完成后，任意一个正式研究产物都必须能回答：

```text
这个产物来自哪个 run？
这个 run 是 exploratory 还是 formal？
这个 run 使用了哪个 git sha？
当时工作区是否干净？
用了哪些 CLI 参数？
用了哪些配置文件和配置哈希？
消费了哪个 source_run_id？
输入数据指纹是什么？
输出了哪些 Markdown / CSV / JSON 文件？
这些文件的 sha256 是什么？
运行成功还是失败？
失败时错误是什么？
服务层能否按 run_id 找回这些产物？
```

如果这些问题不能稳定回答，Phase 5 不算完成。

## 不做内容

- 不实现事件研究。
- 不实现完整日报。
- 不实现单股深度报告。
- 不实现真实公告源。
- 不实现真实历史沪深 300 PIT 成分库。
- 不实现物理数据快照复制。
- 不实现完整 migration framework。
- 不实现生产级 Web 前端。
- 不实现多用户鉴权。
- 不实现远程部署。
- 不实现自动交易。
