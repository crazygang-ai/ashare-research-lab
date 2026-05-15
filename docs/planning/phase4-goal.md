# Phase 4 Goal: 服务化和 Skill 封装

请在已完成 Phase 3 的 `/Users/crazy/own_project/ashare-research-lab` 仓库中继续实现 Phase 4：服务化和 Skill 封装。

本 phase 只做服务入口、定时任务入口、轻量 Web 查询和 Codex Skill 工作流封装。服务层只能读取或调用前置 phase 已有的离线能力，不重新实现因子计算、验证、候选扫描、回测、LLM 解析或综合评分核心逻辑。

## 目标

1. 增加 FastAPI 查询服务。
2. 增加 `ashare serve` 命令。
3. 增加受配置控制的定时任务和 workflow runner。
4. 增加轻量 Web 查询页面，默认展示已有报告产物。
5. 增加 repo-local Codex Skill，封装常用研究工作流。
6. 服务 API 支持查询：
   - 健康状态。
   - 已生成报告 artifact。
   - 最新候选清单。
   - 最新综合评分。
   - 最新回测结果。
   - 单股因子值。
   - 因子验证报告。
7. 服务默认只读，不写 DuckDB。
8. 定时任务只调用已有 CLI / 离线能力。
9. Phase 4 完成后单独 commit，提交信息为：`feat: phase 4 service and skill packaging`。

## 工作约束

- 严格遵守 `docs/planning/a-share-research-plan.md`。
- 所有 Python 命令必须在 Conda 环境 `ashare-research-lab` 中执行。
- 每个 phase 必须单独 commit。
- 本 phase 可以修改 `environment.yml`，加入 FastAPI 服务所需依赖。
- 本 phase 不修改 DuckDB schema。
- 本 phase 不新增核心研究表。
- 服务默认绑定 `127.0.0.1`，不默认暴露公网。
- HTTP 查询接口默认只读。
- HTTP workflow 触发接口默认关闭。
- 定时任务默认 dry-run 或 disabled，必须显式启用才执行真实 workflow。
- 不在配置文件中写 API key、token 或任何 secret。
- 不实现用户系统、登录、权限后台或生产部署。
- 不实现完整 Web 前端；本 phase 只实现轻量 Web 查询。
- 不实现真实邮件、企业微信、钉钉、飞书或 webhook 推送；报告推送留 followup。
- 不把任何服务查询结果描述为买入、卖出或交易指令。

## 依赖变更

更新 `environment.yml`，增加：

```yaml
- fastapi
- uvicorn
- httpx
- apscheduler
```

说明：

- `fastapi` 用于查询服务。
- `uvicorn` 用于本地服务启动。
- `httpx` 用于 FastAPI `TestClient` 和后续 client-side smoke 调用。
- `apscheduler` 用于本地进程内定时任务。

如当前 `pyproject.toml` 已维护 runtime dependencies，需要同步加入对应依赖；如果当前未维护 dependency 列表，不为此重构 packaging。

## 文件变更

建议新增或修改：

```text
configs/service.yaml
src/ashare/service/__init__.py
src/ashare/service/app.py
src/ashare/service/config.py
src/ashare/service/schemas.py
src/ashare/service/artifacts.py
src/ashare/service/queries.py
src/ashare/service/workflows.py
src/ashare/service/scheduler.py
src/ashare/service/ui.py
src/ashare/cli.py
environment.yml
skills/ashare-research-lab/SKILL.md
skills/ashare-research-lab/references/commands.md
skills/ashare-research-lab/references/artifacts.md
tests/test_service_config.py
tests/test_service_artifacts.py
tests/test_service_api.py
tests/test_service_workflows.py
tests/test_service_scheduler.py
tests/test_service_cli.py
tests/test_ashare_skill.py
docs/planning/followups.md
```

可选修改：

```text
pyproject.toml
.gitignore
```

仅当当前仓库未忽略服务运行产物时，允许加入：

```gitignore
data/reports/generated/phase4/
data/service/
```

不得提交：

```text
data/reports/generated/
data/processed/*.duckdb
data/service/
tests/fixtures/generated/
data/raw/announcements/
```

## 配置要求

新增 `configs/service.yaml`：

```yaml
version: phase4.v1

server:
  host: 127.0.0.1
  port: 8008
  reload: false

database:
  db_path: data/processed/ashare_phase4.duckdb
  read_only: true

artifacts:
  roots:
    - data/reports/generated
  known_kinds:
    - scan
    - scoring
    - backtest
    - factor_validation

security:
  allow_http_workflow_run: false
  require_token_for_workflows: true
  token_env_var: ASHARE_SERVICE_TOKEN
  token_header: X-Ashare-Token

scheduler:
  enabled: false
  timezone: Asia/Shanghai

workflows:
  phase4-fixture-research:
    enabled: false
    description: Local fixture workflow for service smoke tests. Uses an isolated workflow DB to avoid DuckDB read/write conflicts with the service query DB.
    schedule:
      trigger: cron
      hour: 18
      minute: 30
    defaults:
      timeout_seconds: 1800
    steps:
      - name: ingest-local
        timeout_seconds: 1800
        command:
          - ashare
          - ingest-local
          - --input-dir
          - tests/fixtures/generated
          - --db-path
          - data/processed/ashare_phase4_workflow.duckdb
      - name: calculate-factors
        timeout_seconds: 1800
        command:
          - ashare
          - calculate-factors
          - --from
          - "2026-03-30"
          - --to
          - "2026-06-26"
          - --db-path
          - data/processed/ashare_phase4_workflow.duckdb
          - --index-code
          - LOCAL_FIXTURE
          - --source-run-id
          - phase4-service-workflow
```

规则：

- `version` 必须为 `phase4.v1`。
- `database.db_path` 是服务查询 DB，只用于只读 API。
- workflow step 中的 `--db-path` 是 workflow 写入 DB，默认必须与 `database.db_path` 不同。
- workflow runner 在 `--execute` 或 HTTP workflow run 前必须解析 step command 中的 `--db-path`；如果解析到的路径等于 `database.db_path`，必须 fail-fast。
- `--dry-run` 遇到同路径时可以成功返回执行计划，但必须包含 warning。
- `/api/v1/status` 必须同时返回：
  - `database.db_path`
  - `database.available`
  - workflow 中解析到的 `target_db_paths`
- 配置中的相对路径按仓库根目录解析。
- workflow steps 只允许执行显式配置的命令。
- workflow runner 必须使用 `subprocess.run(..., shell=False)`。
- workflow runner 必须记录 stdout、stderr、return code、started_at、finished_at、duration_seconds。
- workflow runner 的日志写入 `data/service/workflow-runs/`，不得写 DuckDB。
- `dry_run=True` 时只返回执行计划，不执行命令。
- 不允许通过 API 传入任意 shell 字符串执行。
- 不允许配置文件包含 secret 明文。

## FastAPI 接口建议

新增 `src/ashare/service/app.py`：

```python
def create_app(
    config_path: str | Path = "configs/service.yaml",
    overrides: Mapping[str, object] | None = None,
) -> FastAPI:
    ...
```

建议 endpoints：

```text
GET  /
GET  /health
GET  /api/v1/status
GET  /api/v1/artifacts
GET  /api/v1/artifacts/{artifact_id}
GET  /api/v1/scans/latest
GET  /api/v1/scans/{artifact_id}
GET  /api/v1/scoring/latest
GET  /api/v1/scoring/{artifact_id}
GET  /api/v1/backtests/latest
GET  /api/v1/backtests/{artifact_id}
GET  /api/v1/factors/{factor_name}/validation
GET  /api/v1/stocks/{stock_code}/factors
GET  /api/v1/reports/{artifact_id}/markdown
GET  /api/v1/workflows
POST /api/v1/workflows/{workflow_name}/run
```

接口规则：

- `/` 返回轻量 HTML 查询页面。
- `/health` 不要求 DuckDB 存在，只返回服务进程可用状态。
- `/api/v1/status` 即使 DuckDB 文件不存在也返回 200。
- DB 不存在时 `/api/v1/status` 返回：

```json
{
  "database": {
    "available": false
  }
}
```

- `/api/v1/status` 返回配置版本、db path、artifact roots、scheduler 状态和 workflow target db paths。
- `GET /api/v1/artifacts` 支持 query params：
  - `kind`：可选，只返回指定 artifact kind。
  - `limit`：可选，默认 20，最大 100。
- artifact 列表按 metadata 时间倒序；metadata 缺失时按文件 mtime 倒序兜底。
- 所有 artifact 查询只能读取 `configs/service.yaml.artifacts.roots` 下的已知文件。
- 禁止通过 path 参数读取任意文件。
- `artifact_id` 使用稳定 hash 生成，例如：

```text
sha1(kind + "|" + repo_relative_output_dir)[:12]
```

- `latest` 按 artifact metadata 日期优先、文件 mtime 兜底排序。
- 找不到 artifact 时返回 404。
- CSV 读取失败或列缺失时返回 500，并给出明确错误摘要。
- `/api/v1/stocks/{stock_code}/factors` 只读取 `factor_values`，必须要求：
  - `as_of`
  - `source_run_id`
- 单股因子查询使用只读 DuckDB 连接。
- 因子验证接口只读取 Phase 1a-6 已生成的验证 CSV，不重新计算验证指标。
- 综合评分接口只读取 Phase 3 已生成的 scoring artifact，不重新评分。
- 回测接口只读取 Phase 1b 已生成的 backtest artifact，不重新回测。
- workflow run API 默认返回 403，除非配置显式开启。
- workflow run API 即使开启，也只能执行已配置 workflow。
- 所有 JSON response 必须包含研究用途说明：

```text
research_only: true
not_trading_instruction: true
```

### Markdown 报告与 XSS 规则

`GET /api/v1/reports/{artifact_id}/markdown` 规则：

- 该接口只返回原始 Markdown 文本。
- Response `Content-Type` 固定为：

```text
text/markdown; charset=utf-8
```

- 不在该接口中渲染 HTML。
- `GET /` 轻量页面不得内联渲染 Markdown 报告内容。
- `GET /` 只展示 artifact 元数据、报告标题、文件类型、更新时间和 raw markdown 链接。
- 如页面需要预览报告内容，本 phase 只能使用 `html.escape` 后放入 `<pre>`，不得直接把 Markdown 转为 HTML。
- 不引入未配置 sanitizer 的 markdown-to-html 渲染。
- 不允许报告内容中的 HTML、script、事件属性或 iframe 被浏览器执行。
- 本 phase 不实现完整 Markdown HTML 预览；登记 followup。

### Workflow API 鉴权顺序

`POST /api/v1/workflows/{workflow_name}/run` 鉴权规则固定为：

1. 如果 `security.allow_http_workflow_run = false`：
   - 直接返回 403。
   - 错误码为 `workflow_http_disabled`。
   - 不读取 token，不检查环境变量。
2. 如果 `security.allow_http_workflow_run = true` 且 `security.require_token_for_workflows = true`：
   - 从 header `X-Ashare-Token` 读取 token。
   - 从 `security.token_env_var` 指定的环境变量读取服务端 token。
   - header 缺失、环境变量缺失或 token 不匹配时返回 401。
   - 错误码为 `missing_or_invalid_token`。
3. 如果 workflow 未定义或 disabled：
   - 鉴权通过后返回 404 或 409。
   - 不得在鉴权失败前暴露 workflow 是否存在。

## Artifact Registry

服务层需要实现一个轻量 artifact registry，用于扫描已有报告产物。

支持 artifact kind：

```text
scan
scoring
backtest
factor_validation
```

识别规则：

- `scan` artifact 至少包含：
  - `candidates.csv`
  - `candidate_list.md`
- `scoring` artifact 至少包含：
  - `scoring_report.md`
  - `scored_candidates.csv`
  - `score_metadata.json`
- `backtest` artifact 至少包含：
  - `backtest_report.md`
  - `metrics.csv`
  - `equity_curve.csv`
- `factor_validation` artifact 至少包含：
  - `factor_validation_report.md`
  - `coverage.csv`
  - `rank_ic.csv`
  - `ic_summary.csv`

规则：

- 只扫描配置 roots。
- 不跟随超出 root 的路径逃逸。
- 缺少必需文件时仍可返回 artifact record，但必须包含 warning。
- 不伪造缺失数据。
- 不从报告文件反向推断不存在的核心研究结果。
- artifact metadata 优先读取已有 JSON metadata；没有 JSON 时使用目录名和文件 mtime 兜底。

## 服务层调用边界

服务层允许：

- 调用已有 PIT 查询函数读取 DB。
- 读取已有 Markdown / CSV / JSON 报告产物。
- 调用已有 CLI 命令执行配置化 workflow。
- 用 FastAPI/Pydantic 包装输入输出。
- 用 APScheduler 定时触发配置化 workflow。

服务层不得：

- 重新实现 `calculate-factors`。
- 重新实现 `validate-factors`。
- 重新实现 `scan_candidates` 排序和硬过滤。
- 重新实现 `backtest` 撮合、成本、持仓或指标。
- 重新实现 Phase 2 LLM 解析。
- 重新实现 Phase 3 综合评分。
- 绕过前置 CLI 或模块直接拼装研究结果。
- 写入 `factor_values`、`research_runs` 或任何核心研究表。

## Workflow Runner

新增 workflow runner，供 CLI、HTTP API 和 scheduler 共用。

规则：

- workflow runner 只执行 `configs/service.yaml` 中已定义的 workflow。
- workflow runner 不接受任意 shell 字符串。
- 每个 step 的 command 必须是 list[str]。
- 每个 step 支持 `timeout_seconds`。
- step 未配置 timeout 时使用 workflow defaults。
- workflow defaults 未配置时使用内置默认 `1800` 秒。
- `subprocess.run` 必须使用：
  - `shell=False`
  - `timeout=timeout_seconds`
- 超时后终止子进程，记录：
  - `status = timeout`
  - `return_code = null`
  - `timed_out = true`
  - `timeout_seconds`
  - stdout / stderr 的已捕获内容
- 任一 step 非 0 退出或 timeout 后停止后续 step。
- workflow run JSON 日志必须记录触发来源：

```text
source: serve-embedded | service-scheduler | service-workflow-cli | http-api
```

- workflow run JSON 日志写入：

```text
data/service/workflow-runs/
```

- workflow run JSON 日志不提交到 git。
- workflow runner 执行前必须做 service query DB 与 workflow target DB 的路径冲突检查。

## Scheduler 语义

- 默认只有 `ashare service-scheduler` 作为正式调度入口。
- `ashare serve --enable-scheduler` 仅作为本地一体化便利模式。
- `serve --enable-scheduler` 启动时必须打印 warning：

```text
embedded scheduler is for local convenience only; do not run ashare service-scheduler simultaneously.
```

- 本 phase 不实现跨进程 scheduler 去重锁；登记 followup。
- scheduler 触发 workflow 时必须使用 workflow runner 的同一套 DB 冲突检查和 timeout 规则。
- scheduler disabled 时 fail-fast，除非传 `--once --dry-run`。
- 不引入 Celery、Redis、数据库队列或分布式调度。

## CLI 要求

新增命令：

```text
ashare serve
ashare service-workflow
ashare service-scheduler
```

### `ashare serve`

建议参数：

```text
--service-config       默认 configs/service.yaml
--host                 可选，覆盖配置
--port                 可选，覆盖配置
--reload / --no-reload 默认 false
--enable-scheduler     默认 false
```

行为：

- 调用 `uvicorn.run` 启动 FastAPI app。
- 默认 host 为 `127.0.0.1`。
- 启动时打印服务 URL。
- 如果传入 `--enable-scheduler`，启动内嵌 scheduler 并打印互斥 warning。
- 启动时打印：
  - `service is for research review only and is not a trading system.`
  - `服务仅用于研究查询，不是交易系统。`

### `ashare service-workflow`

建议参数：

```text
--service-config       默认 configs/service.yaml
--name                 必填
--dry-run / --execute  默认 dry-run
```

行为：

- 读取配置中的 workflow。
- dry-run 时打印将执行的 step，不执行命令。
- execute 时按顺序执行 step。
- 任一 step 非 0 退出或 timeout 时停止后续 step。
- 写入 workflow run JSON 日志到 `data/service/workflow-runs/`。
- 不写 DuckDB，除非被调用的已有 CLI 本身按前置 phase 设计写入。
- 记录 `source = service-workflow-cli`。

### `ashare service-scheduler`

建议参数：

```text
--service-config       默认 configs/service.yaml
--once                 默认 false
--name                 可选，只运行一个 workflow
--dry-run / --execute  默认 dry-run
```

行为：

- `--once` 用于测试，立即触发一次匹配 workflow 后退出。
- 非 `--once` 时启动 APScheduler 并阻塞运行。
- scheduler disabled 时 fail-fast，除非传 `--once --dry-run`。
- 记录 `source = service-scheduler`。
- 不引入 Celery、Redis、数据库队列或分布式调度。

## 轻量 Web 查询

本 phase 选择实现轻量 Web 查询，不实现真实报告推送。

`GET /` 页面要求：

- 不使用前端构建工具。
- 不引入 React/Vue/Svelte。
- 可以返回内联 HTML/CSS/少量 JS。
- 展示：
  - 服务状态。
  - artifact 列表。
  - 最新候选清单入口。
  - 最新综合评分入口。
  - 最新回测入口。
  - 单股因子查询表单。
- 页面文案必须明确：
  - `研究复盘`
  - `不是交易指令`
- 页面不得包含营销式 landing page。
- 页面不得展示买入、卖出、目标价或仓位建议。
- 页面不得内联渲染 Markdown 报告。
- 页面输出 artifact title、path、summary 等文本时必须做 HTML escape。

## Codex Skill 要求

新增 repo-local skill：

```text
skills/ashare-research-lab/SKILL.md
```

Skill frontmatter 必须包含：

```yaml
---
name: ashare-research-lab
description: Use this skill when working on the ashare-research-lab A-share research system, including running fixture workflows, factor validation, candidate scans, scoring, backtests, service queries, scheduled jobs, and explaining generated reports. Use it whenever the user asks to operate, inspect, debug, or extend this repository's research workflows.
---
```

Skill 内容必须覆盖：

- 必须先确认当前工作目录是 `ashare-research-lab`。
- 所有 Python 命令使用 `conda run -n ashare-research-lab ...`。
- 常用 workflow：
  - fixture ingest。
  - factor calculation。
  - factor validation report。
  - candidate scan。
  - composite scoring。
  - topn backtest。
  - service smoke test。
  - scheduler dry-run。
- 如何读取生成报告。
- 如何解释候选清单、评分和回测，且必须说明不是交易指令。
- 如何处理 dirty worktree。
- 不提交生成产物。
- 不调用真实 LLM 或真实网络，除非用户明确要求且前置配置已准备好。
- 不把 Skill 写成核心业务逻辑；Skill 只是操作说明书。

可选引用文件：

```text
skills/ashare-research-lab/references/commands.md
skills/ashare-research-lab/references/artifacts.md
```

Skill 不要求自动安装到 `$CODEX_HOME/skills`，只在 repo 内提供可复制 / 可安装版本。

## 测试要求

新增或更新测试，至少覆盖：

1. `configs/service.yaml` 可以加载。
2. 配置版本必须为 `phase4.v1`。
3. 默认 host 为 `127.0.0.1`。
4. 默认 `allow_http_workflow_run = false`。
5. 默认 scheduler disabled。
6. service config 不包含 secret 明文。
7. artifact registry 只扫描配置 roots。
8. artifact registry 不允许 `..` 路径逃逸。
9. scan artifact 必须识别 `candidates.csv` 和 `candidate_list.md`。
10. scoring artifact 必须识别 Phase 3 输出文件。
11. backtest artifact 必须识别 Phase 1b 输出文件。
12. factor validation artifact 必须识别 Phase 1a-6 输出文件。
13. artifact_id 稳定。
14. latest artifact 排序稳定。
15. artifact 缺少必需文件时给出 warning，而不是伪造数据。
16. `create_app` 可以用 TestClient 启动。
17. `GET /health` 返回 200。
18. `GET /api/v1/status` 返回配置版本和 db path。
19. `/api/v1/status` 在 DB 缺失时仍返回 200 且 `database.available = false`。
20. `GET /api/v1/artifacts` 返回 artifact 列表。
21. `GET /api/v1/artifacts?kind=scan&limit=20` 可以过滤和限制结果。
22. `GET /api/v1/scans/latest` 返回候选清单 JSON。
23. `GET /api/v1/scoring/latest` 返回综合评分 JSON。
24. `GET /api/v1/backtests/latest` 返回回测摘要 JSON。
25. `GET /api/v1/factors/{factor_name}/validation` 只读取验证报告 CSV。
26. `GET /api/v1/stocks/{stock_code}/factors` 要求 `as_of` 和 `source_run_id`。
27. 单股因子查询只读 DuckDB。
28. 服务查询不新增 `factor_values` 行。
29. 服务查询不写入 DuckDB。
30. `GET /api/v1/reports/{artifact_id}/markdown` 只能读取已注册 markdown 文件。
31. `/api/v1/reports/{artifact_id}/markdown` 返回 `text/markdown; charset=utf-8`。
32. `/api/v1/reports/{artifact_id}/markdown` 返回 raw markdown，不渲染 HTML。
33. `GET /` 不内联渲染 markdown。
34. `GET /` 对 artifact title / path / summary 做 HTML escape。
35. 未注册 artifact 返回 404。
36. workflow API 默认返回 403。
37. workflow HTTP disabled 时返回 403 `workflow_http_disabled`，且不读取 token。
38. workflow HTTP enabled 但 token 缺失或错误时返回 401 `missing_or_invalid_token`。
39. workflow token header 名固定为 `X-Ashare-Token`。
40. workflow dry-run 返回步骤列表且不执行命令。
41. workflow execute 使用 `shell=False`。
42. workflow step 失败时停止后续 step。
43. workflow step timeout 会停止后续 step 并写入 timeout 状态。
44. workflow run JSON 日志写入 `data/service/workflow-runs/`。
45. workflow run JSON 包含 `source`。
46. workflow execute 检测到 step `--db-path` 等于 service `database.db_path` 时 fail-fast。
47. workflow dry-run 检测到 DB 路径冲突时返回 warning 但不执行。
48. scheduler `--once --dry-run` 可以运行后退出。
49. scheduler disabled 且非 dry-run 时 fail-fast。
50. `serve --enable-scheduler` 打印不要同时运行独立 scheduler 的 warning。
51. `ashare serve --help` 可以成功运行。
52. `ashare service-workflow --help` 可以成功运行。
53. `ashare service-scheduler --help` 可以成功运行。
54. `GET /` 返回 HTML，并包含研究用途和非交易指令说明。
55. Skill `SKILL.md` frontmatter 可解析。
56. Skill description 包含触发场景。
57. Skill 文档包含 Conda 环境要求。
58. Skill 文档包含不提交生成产物要求。
59. Skill 文档不包含 secret。
60. Skill 文档不要求自动交易。
61. 服务测试允许使用 pytest session-scoped fixture 共享一次 fixture pipeline 输出，避免每个测试重复执行完整 pipeline。
62. `ashare --help` 能看到新增命令，同时前置命令仍存在：

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
serve
service-workflow
service-scheduler
```

测试数据必须通过 fixture builder、`ingest_local`、`calculate-factors`、`report factor-validation`、`scan`、`score` 和 `backtest` 在 `tmp_path` 或 phase4 专用输出目录下构造，不依赖仓库内已有 DuckDB 文件。

## 验收命令

以下命令必须全部成功：

```bash
conda run -n ashare-research-lab python -m pip install -e .
```

```bash
conda run -n ashare-research-lab python scripts/build_fixtures.py \
  --output-dir tests/fixtures/generated
```

```bash
rm -f data/processed/ashare_phase4.duckdb
```

```bash
conda run -n ashare-research-lab ashare ingest-local \
  --input-dir tests/fixtures/generated \
  --db-path data/processed/ashare_phase4.duckdb
```

```bash
conda run -n ashare-research-lab ashare calculate-factors \
  --from 2026-03-30 \
  --to 2026-06-26 \
  --db-path data/processed/ashare_phase4.duckdb \
  --index-code LOCAL_FIXTURE \
  --source-run-id phase4-service
```

```bash
conda run -n ashare-research-lab ashare report \
  --kind factor-validation \
  --from 2026-03-30 \
  --to 2026-06-26 \
  --db-path data/processed/ashare_phase4.duckdb \
  --source-run-id phase4-service \
  --factor return_20d \
  --factor return_60d \
  --factor above_ma60 \
  --factor pe_ttm_percentile \
  --factor pb_percentile \
  --factor revenue_yoy \
  --factor profit_yoy \
  --horizon 5,20 \
  --output-dir data/reports/generated/phase4/factor-validation \
  --overwrite
```

```bash
conda run -n ashare-research-lab ashare scan \
  --as-of 2026-06-26 \
  --db-path data/processed/ashare_phase4.duckdb \
  --source-run-id phase4-service \
  --sort-factor return_20d \
  --factor return_20d \
  --factor pe_ttm_percentile \
  --factor revenue_yoy \
  --top 3 \
  --output-dir data/reports/generated/phase4/scan \
  --overwrite
```

```bash
conda run -n ashare-research-lab ashare score \
  --as-of 2026-06-26 \
  --db-path data/processed/ashare_phase4.duckdb \
  --source-run-id phase4-service \
  --index-code LOCAL_FIXTURE \
  --validation-dir data/reports/generated/phase4/factor-validation \
  --diagnostics-from 2026-03-30 \
  --diagnostics-to 2026-06-26 \
  --horizon 5,20 \
  --top 3 \
  --output-dir data/reports/generated/phase4/scoring \
  --overwrite
```

```bash
conda run -n ashare-research-lab ashare backtest \
  --strategy topn-equal \
  --from 2026-03-30 \
  --to 2026-06-26 \
  --db-path data/processed/ashare_phase4.duckdb \
  --index-code LOCAL_FIXTURE \
  --source-run-id phase4-service \
  --sort-factor return_20d \
  --top 3 \
  --output-dir data/reports/generated/phase4/backtest \
  --overwrite
```

```bash
conda run -n ashare-research-lab python - <<'PY'
from ashare.service.app import create_app
from fastapi.testclient import TestClient

app = create_app(
    config_path="configs/service.yaml",
    overrides={
        "database": {"db_path": "data/processed/ashare_phase4.duckdb", "read_only": True},
        "artifacts": {"roots": ["data/reports/generated/phase4"]},
    },
)
client = TestClient(app)

for path in ["/health", "/api/v1/status", "/api/v1/artifacts", "/"]:
    response = client.get(path)
    assert response.status_code == 200, (path, response.status_code, response.text[:300])

artifacts = client.get("/api/v1/artifacts", params={"kind": "scan", "limit": 20})
assert artifacts.status_code == 200, artifacts.text

assert client.get("/api/v1/scans/latest").status_code == 200
assert client.get("/api/v1/scoring/latest").status_code == 200
assert client.get("/api/v1/backtests/latest").status_code == 200

factors = client.get(
    "/api/v1/stocks/000001.SZ/factors",
    params={"as_of": "2026-06-26", "source_run_id": "phase4-service"},
)
assert factors.status_code == 200, factors.text
payload = factors.json()
assert payload["research_only"] is True
assert payload["not_trading_instruction"] is True
assert "rows" in payload

blocked = client.post("/api/v1/workflows/phase4-fixture-research/run")
assert blocked.status_code == 403
assert blocked.json()["error_code"] == "workflow_http_disabled"

html = client.get("/").text
assert "研究" in html
assert "不是交易" in html or "not a trading" in html
assert "<script" not in html.lower()

scan_latest = client.get("/api/v1/scans/latest").json()
artifact_id = scan_latest["artifact_id"]
markdown = client.get(f"/api/v1/reports/{artifact_id}/markdown")
assert markdown.status_code == 200
assert markdown.headers["content-type"].startswith("text/markdown")
assert "candidate" in markdown.text.lower() or "候选" in markdown.text

print("OK phase4 service API")
PY
```

```bash
conda run -n ashare-research-lab ashare service-workflow \
  --name phase4-fixture-research \
  --service-config configs/service.yaml \
  --dry-run
```

```bash
conda run -n ashare-research-lab ashare service-scheduler \
  --service-config configs/service.yaml \
  --once \
  --name phase4-fixture-research \
  --dry-run
```

```bash
conda run -n ashare-research-lab python - <<'PY'
from pathlib import Path
import yaml

skill = Path("skills/ashare-research-lab/SKILL.md")
assert skill.exists(), "missing Skill"
text = skill.read_text(encoding="utf-8")
assert text.startswith("---")
frontmatter = text.split("---", 2)[1]
meta = yaml.safe_load(frontmatter)
assert meta["name"] == "ashare-research-lab"
assert "ashare-research-lab" in meta["description"]
required = [
    "conda run -n ashare-research-lab",
    "fixture",
    "factor validation",
    "candidate",
    "scoring",
    "backtest",
    "serve",
    "not a trading instruction",
]
missing = [item for item in required if item not in text]
assert not missing, f"Skill missing: {missing}"
print("OK phase4 skill")
PY
```

```bash
conda run -n ashare-research-lab python - <<'PY'
from pathlib import Path

text = Path("docs/planning/followups.md").read_text(encoding="utf-8")
required = [
    "D44", "D45", "D46", "D47", "D48", "D49", "D50",
    "D51", "D52", "D53", "D54", "D55",
    "research_runs",
    "本地服务",
    "定时任务",
    "报告推送",
    "Web",
    "Skill",
    "生产部署",
    "XSS",
    "限速",
    "token",
    "scheduler",
    "只读查询 DB",
    "workflow 写入 DB",
]
missing = [item for item in required if item not in text]
assert not missing, f"followups.md missing: {missing}"
print("OK followups D44-D55")
PY
```

```bash
conda run -n ashare-research-lab pytest -q
```

```bash
conda run -n ashare-research-lab ashare --help
```

## Followups 更新

修改 `docs/planning/followups.md`，从现有 D43 后追加：

```text
D44 服务层暂用文件 artifact registry，未接入正式 research_runs
D45 服务默认仅本地使用，未实现多用户鉴权
D46 定时任务为进程内调度，未实现 durable queue
D47 本 phase 选择轻量 Web 查询，未实现真实报告推送
D48 Web 查询不是完整前端产品
D49 Codex Skill 仅提供 repo-local 版本，未自动安装到 CODEX_HOME
D50 服务未覆盖生产部署、监控、日志聚合和告警
D51 服务 Markdown HTML 预览未实现 XSS sanitization / 渲染白名单
D52 服务无请求限速 / IP 白名单
D53 token 鉴权仅使用单值环境变量，未实现轮换或细粒度权限
D54 嵌入式 scheduler 与独立 scheduler 进程未实现跨进程互斥 / 去重
D55 service 只读查询 DB 与 workflow 写入 DB 仅做路径隔离，未实现 durable lock 或原子发布
```

每条按现有 followups 格式记录：

```markdown
### Dxx. <债标题>

- 现状: ...
- 触发: ...
- 决策: ...
- 关联: ...
```

不得借本 phase 实现 D44-D55。

## 完成后

1. 运行 `git status`，确认只包含 Phase 4 相关代码、测试、配置、Skill 和必要文档改动。
2. 确认未提交生成报告、DuckDB、workflow run 日志、fixture 生成产物或缓存。
3. 执行 `git add .`。
4. 执行：

```bash
git commit -m "feat: phase 4 service and skill packaging"
```

5. 最终回复说明：
   - 修改了哪些文件。
   - FastAPI 提供了哪些查询接口。
   - 服务如何保证只读和不重新实现核心研究逻辑。
   - Markdown 报告如何避免 XSS / HTML 注入。
   - Workflow API 鉴权顺序如何实现。
   - DuckDB 服务查询 DB 与 workflow 写入 DB 如何隔离。
   - 定时任务如何配置和 dry-run。
   - 轻量 Web 查询如何访问。
   - Codex Skill 放在哪里，覆盖哪些工作流。
   - followups 是否追加 D44-D55。
   - 验收命令是否全部通过。
   - commit hash。
   - 是否发现 plan 或前置 phase 的新缺口。

## 不要实现

- 不实现新因子。
- 不重新实现因子计算。
- 不重新实现单因子验证。
- 不重新实现候选扫描排序和硬过滤。
- 不重新实现组合回测。
- 不重新实现综合评分。
- 不重新实现 LLM 公告解析。
- 不实现事件研究。
- 不实现 LLM 事件分。
- 不把服务查询结果写回 `factor_values`。
- 不写入 `research_runs`。
- 不修改 DuckDB schema。
- 不实现真实邮件、短信、企业微信、钉钉、飞书或 webhook 推送。
- 不实现完整 Web 前端、前端构建链路或登录后台。
- 不实现 Markdown HTML 预览和 sanitizer。
- 不实现用户权限、RBAC、审计后台。
- 不实现 Celery、Redis、数据库队列或分布式调度。
- 不实现跨进程 scheduler 去重锁。
- 不实现生产部署、Docker、Kubernetes、Nginx、TLS 或公网发布。
- 不实现实时行情、自动交易、下单、仓位建议或目标价。
- 不调用真实 LLM。
- 不调用 AkShare。
- 不提交任何生成产物、真实公告正文、真实 LLM 响应、DuckDB 文件或服务日志。

## 发现的缺口

- Plan 第 18 节示例接口使用 `run_id`，但前置 phase 仍未写入 `research_runs`；本 phase 应使用稳定 `artifact_id` 查询文件产物，并在 followups 登记。
- 前置 phase 尚未实现真实 `stock-report` 业务报告；本 phase 不应新增单股报告生成逻辑，只能查询已有因子值或已有报告文件。
- 当前环境依赖未包含 FastAPI / Uvicorn / httpx / APScheduler；本 phase 需要更新 `environment.yml`。
- Plan 提到“每日报告推送”，但本 phase 选择轻量 Web 查询，不实现真实推送。
- 进程内 scheduler 适合本地研究工作流，不是可靠生产任务平台。
- Markdown 报告未来如果要 HTML 预览，必须先设计 sanitizer / 白名单渲染口径。
- DuckDB 不适合一边服务进程只读持有连接、一边 workflow 对同一文件写入；本 phase 用查询 DB 与 workflow 写入 DB 路径隔离规避，不实现 durable lock 或原子发布。
