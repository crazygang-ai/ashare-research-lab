# AGENTS.md

本文件给维护这个仓库的 agent 使用。默认用简体中文回复用户；代码、命令、路径、文件名、配置项、日志、错误信息、API/CLI/SDK/PR/CI/CD、Git、Docker、Kubernetes、DuckDB、AkShare 等专有名词保持英文原文。

## 项目定位

`ashare-research-lab` 是 A 股离线研究实验室，不是自动交易系统。代码负责数据、计算、验证、审计和报告；LLM 只负责阅读、提取、摘要和解释，不直接决定买卖。

所有候选、评分、回测、日报、单股报告都必须按研究输出表述：

- candidate list is not a trading instruction
- composite score is not a trading instruction
- backtest is a historical simulation, not a performance promise
- stock report is for research review only

不要生成买入、卖出、目标价、仓位建议或自动交易动作。

## 当前可用边界

当前仓库可以作为个人本地离线 MVP 使用。真实 AkShare 链路已能跑通沪深 300 当前成分快照、日线、估值、因子、验证、扫描、评分和单股报告。仓库还包含本地 FastAPI 查询服务和 React/Vite 研究工作台，用于查看报告、artifact、UI run history，并通过受控表单创建本地研究运行。

必须记住的限制：

- AkShare 指数成分是当前快照，不是严格历史 PIT 成分库。
- `--universe-as-of` 早于真实快照日期时，本质是当前成分快照静态回填，有幸存者偏差。
- 严格历史研究、formal validation 和 formal backtest 需要 `historical_pit` universe。
- formal run 受审计策略约束，默认要求 clean Git worktree；formal daily report 还会被 data quality gate 的 blocking failure 阻断。
- 多数据源共用一个 DuckDB 时，必须显式核对并传递 `--source-tag` / `--data-source`，避免把 fixture、AkShare、fallback CSV 数据混在一起。
- LLM 公告解析已有 CLI、schema 和 fixture 模式；真实 LLM 调用需要显式配置，不应默认触发。
- `--max-symbols` 只用于 smoke / 调试；候选和评分排名只在样本内可比，不能解释为全量 HS300 研究结果。
- Web UI 默认只读；`configs/service.yaml` 的 `ui_runner.enabled` 默认是 `false`，网页触发运行只限本机研究 workflow，不是交易入口。
- 生成在 `data/` 下的 DuckDB、cache、report、snapshot 默认不入 Git。

## 开始工作前

确认目录和工作区：

```bash
pwd
test -f pyproject.toml && test -d src/ashare
git status --short
```

不要还原用户已有改动。只改和任务直接相关的文件。

所有 Python/CLI 命令优先走 Conda 环境：

```bash
conda run -n ashare-research-lab python -m pip install -e .
conda run -n ashare-research-lab ashare --help
conda run -n ashare-research-lab pytest -q
```

搜索文件优先用 `rg` / `rg --files`。

## 常用验证命令

完整测试：

```bash
conda run -n ashare-research-lab pytest -q
```

常用局部测试：

```bash
conda run -n ashare-research-lab pytest -q tests/test_provider_checks.py
conda run -n ashare-research-lab pytest -q tests/test_factors.py
conda run -n ashare-research-lab pytest -q tests/test_scan_cli.py tests/test_score_cli.py
conda run -n ashare-research-lab pytest -q tests/test_backtest_cli.py tests/test_daily_report_cli.py tests/test_stock_report_cli.py
conda run -n ashare-research-lab pytest -q tests/test_audit_context.py tests/test_audit_run_store.py tests/test_service_api.py
```

编译检查：

```bash
conda run -n ashare-research-lab python -m compileall -q src/ashare tests
```

前端测试 / 构建：

```bash
cd frontend
npm run test
npm run build
```

AkShare capability smoke：

```bash
conda run -n ashare-research-lab python -c "from ashare.ingest.akshare_provider import AkShareProvider; p=AkShareProvider(retries=0, rate_limit_seconds=0); c=p.capability_check(); print(c.status); print(c.available_apis); print(c.missing_apis); raise SystemExit(0 if c.status == 'PASS' else 1)"
```

比亚迪真实数据 smoke：

```bash
conda run -n ashare-research-lab python -c "from datetime import date; from ashare.ingest.akshare_provider import AkShareProvider; p=AkShareProvider(retries=0, rate_limit_seconds=0); d=p.fetch_daily_prices(['002594.SZ'], date(2025,1,1), date(2026,5,22)); v=p.fetch_valuation_daily(['002594.SZ'], date(2025,1,1), date(2026,5,22)); print(len(d), len(v)); print(d.iloc[-1].to_dict()); print(v.iloc[-1].to_dict())"
```

## 真实 AkShare 链路注意事项

`src/ashare/ingest/akshare_provider.py` 的兼容逻辑很重要：

- 日线 API 候选：`stock_zh_a_hist`、`stock_zh_a_daily`、`stock_zh_a_hist_tx`
- 估值 API 候选：`stock_a_lg_indicator`、`stock_zh_valuation_baidu`
- AkShare `1.18.60` 环境里可能没有 `stock_a_lg_indicator`
- `stock_zh_valuation_baidu` 返回 `date/value`，需要分别取 `市盈率(TTM)`、`市净率`、`总市值`
- `--cache-mode use|refresh|offline` 会影响是否复用 `data/raw/cache`
- `--source auto` 未加 `--allow-fallback` 等价于 `--source akshare`
- `--allow-fallback` 必须配合 `--fallback-csv-dir`

如果用户报 `provider_capability_check FAIL missing_apis=stock_a_lg_indicator`，优先确认当前代码和 editable install 是否生效。

## 推荐调试路径

用户说真实数据 ingest 失败时：

1. 跑 AkShare capability smoke。
2. 单股票抓 `002594.SZ` 日线和估值。
3. 检查 `--source`、`--source-tag`、`--cache-mode`、`--allow-fallback`、`--fallback-csv-dir` 是否符合预期。
4. 用小范围或 `--max-symbols` 跑 `ashare ingest`。
5. 查看数据质量报告和 cache 事件。
6. 跑用户原始命令。
7. 查 `ashare as-of`、DuckDB 表行数、目标股票是否在指定 `source_tag` 下。
8. 再跑因子、报告、scan、score、stock-report。
9. 最后跑相关测试或全量 `pytest -q`。

用户说因子/评分结果不对时：

1. 查 `factor_values` 是否有目标股票、目标日期、目标 `source_run_id`。
2. 查 `factor_run_universe` 的 universe size 和 `universe_kind`。
3. 查 `data_source` / `source_tag` 是否和 ingest 一致。
4. 查 `validation_gate.csv`，确认哪些因子被跳过。
5. 查 `score_breakdown.csv` 和单股 `stock_score_breakdown.csv`。
6. 若是 formal 模式，确认 `factor_run_universe.universe_kind` 全部是 `historical_pit`。

解释 smoke run 时要明确样本边界：`--max-symbols 20` 生成的 `candidates.csv` / `scored_candidates.csv` 只有 20 行是正常结果；它证明链路跑通，不证明全量排名。

## 常见命令配方

本地 fixture：

```bash
DB=data/processed/fixture.duckdb
SOURCE_RUN=fixture-factor
ASOF=2026-06-26

conda run -n ashare-research-lab python scripts/build_fixtures.py --output-dir tests/fixtures/generated
conda run -n ashare-research-lab ashare ingest-local --input-dir tests/fixtures/generated --db-path "$DB"
conda run -n ashare-research-lab ashare calculate-factors --db-path "$DB" --from 2026-03-30 --to "$ASOF" --index-code LOCAL_FIXTURE --source-run-id "$SOURCE_RUN" --overwrite-run
conda run -n ashare-research-lab ashare report --kind factor-validation --db-path "$DB" --from 2026-03-30 --to 2026-06-05 --source-run-id "$SOURCE_RUN" --factor return_20d --factor return_60d --factor pe_ttm_percentile --factor pb_percentile --horizon 5,20 --output-dir data/reports/generated/fixture/factor-validation --overwrite --overwrite-run
conda run -n ashare-research-lab ashare scan --db-path "$DB" --as-of "$ASOF" --source-run-id "$SOURCE_RUN" --index-code LOCAL_FIXTURE --sort-factor return_20d --factor return_20d --factor pe_ttm_percentile --top 5 --output-dir data/reports/generated/fixture/scan --overwrite --overwrite-run
conda run -n ashare-research-lab ashare score --db-path "$DB" --as-of "$ASOF" --source-run-id "$SOURCE_RUN" --index-code LOCAL_FIXTURE --validation-dir data/reports/generated/fixture/factor-validation --top 5 --output-dir data/reports/generated/fixture/score --overwrite --overwrite-run
conda run -n ashare-research-lab ashare backtest --strategy topn-equal --db-path "$DB" --from 2026-03-30 --to "$ASOF" --source-run-id "$SOURCE_RUN" --index-code LOCAL_FIXTURE --sort-factor return_20d --top 3 --output-dir data/reports/generated/fixture/backtest --overwrite --overwrite-run
conda run -n ashare-research-lab ashare service-workflow --name phase4-fixture-research --service-config configs/service.yaml --dry-run
```

比亚迪 MVP 链路使用 README 里的完整命令，关键变量为：

```bash
DB=data/processed/byd_mvp.duckdb
SOURCE=akshare-hs300-static-20250101
ASOF=2026-05-22
FACTOR_RUN=byd-mvp-factor-short-20260522
```

## 代码地图

```text
src/ashare/cli.py                 Typer CLI
src/ashare/ingest/                数据采集、AkShare provider、字段契约
src/ashare/storage/               DuckDB schema 和 migrations
src/ashare/pit/                   as-of 查询和 PIT 语义
src/ashare/factors/               因子计算
src/ashare/validation/            IC、分组收益、衰减曲线、事件研究
src/ashare/scan/                  候选扫描
src/ashare/scoring/               综合评分、硬过滤、validation gate
src/ashare/backtest/              Top N 等权回测
src/ashare/reports/               Markdown/CSV 报告
src/ashare/audit/                 run manifest、artifact index、数据指纹
src/ashare/service/               FastAPI 查询服务、artifact registry、workflow、scheduler、UI run 管理
src/ashare/announcements/         公告规则、正文存储
src/ashare/llm/                   LLM schema、prompt、fixture/optional client、validator
src/ashare/fixtures/              deterministic fixture builder
configs/                          数据、因子、验证、评分、回测、LLM、服务、审计配置
docs/                             规划、数据字典、因子定义、回测假设
frontend/                         React/Vite 本地研究工作台
scripts/                          fixture 和文档生成辅助脚本
tests/                            单元和 CLI 测试
```

## 修改守则

- 改 CLI 行为时，同步更新 README 或相关文档。
- 改字段契约时，同步更新测试和 `docs/data_dictionary.md` 生成链路。
- 改因子公式时，同步更新 `configs/data_dictionary.yaml`、测试和因子定义文档。
- 改 scoring gate 时，同步检查 `configs/scoring.yaml` 和评分相关测试。
- 改 backtest 假设时，同步更新 `docs/backtest_assumptions.md`。
- 改 ingest provider、字段 mapping、cache 或 fallback 行为时，同步检查 `tests/test_provider_checks.py`、`tests/test_ingest_contracts.py`、`tests/test_ingest_real_pilot.py`。
- 改 PIT、universe、source isolation 或 `factor_run_universe` 行为时，同步检查 `tests/test_asof.py`、`tests/test_universe_snapshots.py`、`tests/test_backtest_signals.py`。
- 改 audit、run manifest、artifact index 或 formal run 策略时，同步检查 `configs/audit.yaml` 和 `tests/test_audit_*`。
- 改 service API、workflow 或 scheduler 时，同步检查 `configs/service.yaml` 和 `tests/test_service_*`。
- 改 service 或 frontend 行为时，同步更新 README 或相关文档，并跑对应 Python / frontend 测试。
- 改 announcement、LLM schema、prompt 或 parser 时，同步检查 `configs/llm.yaml`、`tests/test_announcement_*`、`tests/test_llm_*`。
- 改 daily report 或 stock report 时，同步检查 data quality gate、artifact bundle 和对应 CLI 测试。
- 不要把真实数据、cache、DuckDB、报告产物、UI workflow logs、LLM 原始响应提交到 Git。
- 不要把 API key、token、密码写入仓库。

## 输出解释口径

向用户总结结果时，优先给：

- 跑了哪些命令
- 写了哪些文件
- 关键行数、日期范围、目标股票结果
- 哪些测试通过
- 哪些限制仍然存在

如果总结 `daily-report`，区分 ingest 阶段的 `data-quality/data_quality_report.md` 和 `daily-report` 阶段生成的 `data_quality_gate.csv` / `data_quality_gate.json`。前者是采集质量报告，后者是日报输入一致性和阻断检查。

不要只说“已完成”。研究系统的价值在于可复盘，回答要给出可追溯证据。
