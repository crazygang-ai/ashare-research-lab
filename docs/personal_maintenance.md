# 个人本地维护手册

本手册把日常研究运行、复核、备份和失败定位固定成可重复流程。所有候选、评分、验证、回测、日报和单股报告都只用于研究复盘，不是交易指令：

- candidate list is not a trading instruction
- composite score is not a trading instruction
- backtest is a historical simulation, not a performance promise
- stock report is for research review only

## 每日运行

每日入口使用显式日期，不使用 today 默认值：

```bash
scripts/run_hs300_daily_research.sh --as-of 2026-05-22
```

常用变体：

```bash
scripts/run_hs300_daily_research.sh --as-of 2026-05-22 --dry-run
scripts/run_hs300_daily_research.sh --as-of 2026-05-22 --max-symbols 20
scripts/run_hs300_daily_research.sh --as-of 2026-05-22 --stock-code 600519.SH
scripts/run_hs300_daily_research.sh --as-of 2026-05-22 --watchlist-file configs/watchlist.example.csv
```

运行前先确认环境和工作区：

```bash
pwd
test -f pyproject.toml && test -d src/ashare
git status --short
conda run -n ashare-research-lab ashare --help
```

每日打开这些输出：

- 日报：`data/reports/generated/hs300-daily/<YYYYMMDD>/daily-report/daily_report.md`
- 数据质量：`data/reports/generated/hs300-daily/<YYYYMMDD>/data-quality/data_quality_gate.csv`
- 验证门槛：`data/reports/generated/hs300-daily/<YYYYMMDD>/factor-validation/validation_gate.csv`
- 候选清单：`data/reports/generated/hs300-daily/<YYYYMMDD>/scan/candidates.csv`
- 综合评分：`data/reports/generated/hs300-daily/<YYYYMMDD>/score/scored_candidates.csv`
- 单股报告：`data/reports/generated/hs300-daily/<YYYYMMDD>/stock-<CODE>/stock_report.md`

如果 `daily_report.md`、`data_quality_gate.csv`、`validation_gate.csv` 或 `daily_metadata.json` 显示 blocking `FAIL`、输入 run id 不符合预期、watchlist 缺少因子值，停止解释候选和评分，只做数据问题排查。

## 每周复核

每周固定做一次本地工程复核：

```bash
conda run -n ashare-research-lab python -m pip install -e .
conda run -n ashare-research-lab python docs/build_data_dictionary.py
git diff --exit-code docs/data_dictionary.md docs/factor_definitions.md
conda run -n ashare-research-lab python -m compileall -q src/ashare tests
conda run -n ashare-research-lab ruff check .
conda run -n ashare-research-lab pytest -q
git status --short
```

报告复核顺序：

1. 先看 data quality gate，确认 AkShare 能力、字段映射、行数和日期范围。
2. 再看 factor validation 的 coverage、IC 样本数和 `validation_gate.csv`。
3. 比较本周日报中的排名变化、入选 / 移出股票和 watchlist 摘要。
4. 抽查 `run_manifest.json`、`daily_metadata.json`、`stock_metadata.json`，确认 `as_of_date`、`source_run_id`、`config_hash` 和 `data_snapshot_id` 可以追溯。
5. 对照 `docs/planning/followups.md`，只保留仍真实存在且与个人本地研究有关的工程债。

## 每月备份

每月备份 DuckDB、AkShare cache 和关键本地产物索引。备份目录在 `data/backups/`，默认不提交：

```bash
STAMP="$(date +%Y%m%d)"
BACKUP_DIR="data/backups/${STAMP}"
mkdir -p "$BACKUP_DIR"
cp -p data/processed/*.duckdb "$BACKUP_DIR"/ 2>/dev/null || true
tar -czf "$BACKUP_DIR/raw-cache.tgz" data/raw/cache 2>/dev/null || true
tar -czf "$BACKUP_DIR/service-workflow-runs.tgz" data/service/workflow-runs 2>/dev/null || true
shasum -a 256 "$BACKUP_DIR"/* > "$BACKUP_DIR/SHA256SUMS" 2>/dev/null || true
```

备份后做一次只读抽查：

```bash
conda run -n ashare-research-lab ashare as-of \
  --db-path data/processed/hs300_daily.duckdb \
  --as-of 2026-05-22 \
  --index-code 000300.SH \
  --stock-code 002594.SZ \
  --data-source akshare-hs300-daily
```

不要把备份目录、DuckDB、cache 或报告压缩包提交到 Git。

## 失败定位

真实数据 ingest 失败时按这个顺序缩小问题：

```bash
conda run -n ashare-research-lab python -c "from ashare.ingest.akshare_provider import AkShareProvider; p=AkShareProvider(retries=0, rate_limit_seconds=0); c=p.capability_check(); print(c.status); print(c.available_apis); print(c.missing_apis); raise SystemExit(0 if c.status == 'PASS' else 1)"
```

再用单股票确认日线和估值链路：

```bash
conda run -n ashare-research-lab python -c "from datetime import date; from ashare.ingest.akshare_provider import AkShareProvider; p=AkShareProvider(retries=0, rate_limit_seconds=0); d=p.fetch_daily_prices(['002594.SZ'], date(2025,1,1), date(2026,5,22)); v=p.fetch_valuation_daily(['002594.SZ'], date(2025,1,1), date(2026,5,22)); print(len(d), len(v)); print(d.iloc[-1].to_dict()); print(v.iloc[-1].to_dict())"
```

然后依次执行：

1. `scripts/run_hs300_daily_research.sh --as-of <DATE> --dry-run`
2. `scripts/run_hs300_daily_research.sh --as-of <DATE> --max-symbols 20`
3. 用户原始命令
4. `ashare as-of` 检查目标股票、日期、`data_source`
5. 查询 `factor_values`、`factor_run_universe`、`validation_gate.csv`、`score_breakdown.csv`
6. 最后跑 `pytest -q` 和 `compileall`

因子或评分看起来异常时，优先确认目标股票是否在同一 `source_run_id`、同一 `as_of_date` 和同一 `data_source` 下有完整因子值；不要把旧库残留结果当成本轮研究输出。

## 永远不提交

这些文件和目录只属于本机运行状态，永远不提交：

- `data/processed/` 下的 DuckDB，包括 `*.duckdb`、`*.duckdb.wal`、`*.duckdb.tmp`
- `data/raw/` 下的 AkShare cache、真实公告正文、原始下载文件
- `data/snapshots/` 下的数据快照
- `data/reports/generated/` 下的报告、CSV、JSON metadata、manifest
- `data/service/` 下的 workflow run JSON 日志
- `data/backups/` 下的 DuckDB / cache 备份
- 私人 watchlist：`configs/watchlist*.csv`、`configs/watchlist*.txt`，示例 `configs/watchlist.example.csv` 除外
- API key、token、密码、真实公告全文、LLM 原始响应

## 本地只读服务边界

服务只用于本机研究查询：

```bash
conda run -n ashare-research-lab ashare serve --service-config configs/service.yaml
```

默认边界必须保持：

- `server.host: 127.0.0.1`
- `database.read_only: true`
- `security.allow_http_workflow_run: false`
- `scheduler.enabled: false`

不做公网生产部署，不做 RBAC，不做交易接口，不接券商接口，不提供买入、卖出、目标价、仓位或自动交易动作。`service-workflow` 和 `service-scheduler` 只保留本地 dry-run / smoke 能力，不作为个人日常主入口。

## 真实 LLM 调用策略

真实 LLM 默认不触发。`configs/llm.yaml` 的默认状态应保持：

```yaml
enabled: false
default_llm_mode: fixture
schema_validation: true
store_evidence: true
```

只有同时满足这些条件，才允许单独启用真实 LLM：

- 配置已准备好：模型、base URL、API key 环境变量、超时、重试和限流策略明确。
- 成本预算已准备好：单次运行 token 上限、公告数量上限、失败停止规则明确。
- 证据定位已准备好：所有 `evidence_text` 都能回指保存的公告正文，无法定位时降级为失败或 warning。
- schema 校验已准备好：输出必须通过当前 extraction schema 和 validator，不把自由文本直接写入研究结论。

LLM 只能用于阅读、提取、摘要和解释公告证据；不能直接决定候选、评分、买卖、目标价、仓位或交易动作。
