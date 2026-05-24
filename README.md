# ashare-research-lab

A 股离线研究实验室。这个仓库把数据采集、Point-in-Time 口径整理、因子计算、因子验证、候选扫描、综合评分、回测和 Markdown/CSV 报告串成一条可复现的本地研究链路。

它的目标不是自动荐股，也不是给买卖指令。它更像一个研究工作台：用代码负责事实、计算、验证和复盘，用报告把每一步的输入、输出、假设和风险暴露出来。

## 当前状态

当前版本已经可以作为个人本地离线研究 MVP 使用：

- 支持 DuckDB 落库。
- 支持本地 fixture 数据和 AkShare 真实数据试跑。
- 支持沪深 300 当前成分快照起步。
- 支持日频行情、估值、指数成分、公告 CSV、风险事件等数据表。
- 支持基础因子、硬过滤、单因子验证、候选清单、综合评分、Top N 等权回测、日报和单股报告。
- 支持 run manifest、artifact index、配置 hash、数据快照指纹等审计信息。

重要限制：

- AkShare 当前试跑链路使用指数当前成分快照，不等同于严格历史 PIT 成分股库。
- 用 `--universe-as-of` 回填当前成分做历史实验会有幸存者偏差，只适合 MVP 链路验证。
- 报告里的候选、评分和回测都是研究输出，不是交易指令。
- LLM 公告解析已有 CLI 骨架和配置，但真实 LLM 调用需要单独配置，不应默认触发。

完整规划见 [docs/planning/a-share-research-plan.md](docs/planning/a-share-research-plan.md)。

## 安装

```bash
conda env create -f environment.yml
conda run -n ashare-research-lab python -m pip install -e .
```

日常命令建议都通过 Conda 环境执行：

```bash
conda run -n ashare-research-lab ashare --help
conda run -n ashare-research-lab pytest -q
```

如果你已经进入环境，也可以直接运行：

```bash
conda activate ashare-research-lab
ashare --help
pytest -q
```

## 一分钟离线自检

这条链路不访问外网，适合先确认开发环境和核心流程正常：

```bash
conda run -n ashare-research-lab python scripts/build_fixtures.py \
  --output-dir tests/fixtures/generated

conda run -n ashare-research-lab ashare ingest-local \
  --input-dir tests/fixtures/generated \
  --db-path data/processed/fixture.duckdb

conda run -n ashare-research-lab ashare calculate-factors \
  --db-path data/processed/fixture.duckdb \
  --from 2026-03-30 \
  --to 2026-06-26 \
  --index-code LOCAL_FIXTURE \
  --source-run-id fixture-factor \
  --overwrite-run

conda run -n ashare-research-lab ashare scan \
  --db-path data/processed/fixture.duckdb \
  --as-of 2026-06-26 \
  --source-run-id fixture-factor \
  --sort-factor return_20d \
  --factor return_20d \
  --factor pe_ttm_percentile \
  --top 5 \
  --output-dir data/reports/generated/fixture/scan \
  --overwrite
```

输出会写到 `data/processed/` 和 `data/reports/generated/`。这些目录默认被 `.gitignore` 忽略。

## 用比亚迪验证真实 AkShare 链路

下面这组命令复现一个最小但完整的真实数据研究包。示例使用 `002594.SZ` 比亚迪、沪深 300、数据截止日 `2026-05-22`。

先设置变量：

```bash
DB=data/processed/byd_mvp.duckdb
SOURCE=akshare-hs300-static-20250101
ASOF=2026-05-22
FACTOR_RUN=byd-mvp-factor-short-20260522
```

采集沪深 300 当前成分快照及日线/估值数据：

```bash
conda run -n ashare-research-lab ashare ingest \
  --source akshare \
  --source-tag "$SOURCE" \
  --universe hs300 \
  --index-code 000300.SH \
  --from 2025-01-01 \
  --to "$ASOF" \
  --universe-as-of 2025-01-01 \
  --db-path "$DB" \
  --quality-report-dir data/reports/generated/byd/static-quality \
  --overwrite-report
```

检查比亚迪在库里的 as-of 快照：

```bash
conda run -n ashare-research-lab ashare as-of \
  --db-path "$DB" \
  --as-of "$ASOF" \
  --index-code 000300.SH \
  --stock-code 002594.SZ \
  --data-source "$SOURCE"
```

计算基础因子：

```bash
conda run -n ashare-research-lab ashare calculate-factors \
  --db-path "$DB" \
  --from 2026-04-01 \
  --to "$ASOF" \
  --index-code 000300.SH \
  --data-source "$SOURCE" \
  --source-run-id "$FACTOR_RUN" \
  --run-mode exploratory \
  --overwrite-run \
  --factor return_20d \
  --factor return_60d \
  --factor above_ma60 \
  --factor pe_ttm_percentile \
  --factor pb_percentile \
  --factor is_st \
  --factor is_suspended \
  --factor is_delisted \
  --factor low_liquidity
```

生成单因子验证报告：

```bash
conda run -n ashare-research-lab ashare report \
  --kind factor-validation \
  --db-path "$DB" \
  --from 2026-04-01 \
  --to 2026-04-17 \
  --source-run-id "$FACTOR_RUN" \
  --factor return_20d \
  --factor return_60d \
  --factor pe_ttm_percentile \
  --factor pb_percentile \
  --horizon 5,20 \
  --n-groups 5 \
  --output-dir data/reports/generated/byd/factor-validation \
  --run-id byd-factor-validation-20260522 \
  --run-mode exploratory \
  --overwrite \
  --overwrite-run
```

生成候选清单：

```bash
conda run -n ashare-research-lab ashare scan \
  --db-path "$DB" \
  --as-of "$ASOF" \
  --source-run-id "$FACTOR_RUN" \
  --index-code 000300.SH \
  --sort-factor return_20d \
  --factor return_20d \
  --factor return_60d \
  --factor pe_ttm_percentile \
  --factor pb_percentile \
  --top 300 \
  --output-dir data/reports/generated/byd/scan \
  --run-id byd-scan-20260522 \
  --run-mode exploratory \
  --overwrite \
  --overwrite-run
```

生成综合评分：

```bash
conda run -n ashare-research-lab ashare score \
  --db-path "$DB" \
  --as-of "$ASOF" \
  --source-run-id "$FACTOR_RUN" \
  --index-code 000300.SH \
  --data-source "$SOURCE" \
  --validation-dir data/reports/generated/byd/factor-validation \
  --top 300 \
  --skip-diagnostics \
  --output-dir data/reports/generated/byd/score \
  --run-id byd-score-20260522 \
  --run-mode exploratory \
  --overwrite \
  --overwrite-run
```

生成比亚迪单股报告：

```bash
conda run -n ashare-research-lab ashare stock-report \
  --db-path "$DB" \
  --code 002594.SZ \
  --as-of "$ASOF" \
  --source-run-id "$FACTOR_RUN" \
  --score-run-id byd-score-20260522 \
  --scan-run-id byd-scan-20260522 \
  --output-dir data/reports/generated/byd/stock-002594 \
  --run-id byd-stock-002594-20260522 \
  --run-mode exploratory \
  --overwrite \
  --overwrite-run
```

关键输出：

- 数据质量报告：`data/reports/generated/byd/static-quality/data_quality_report.md`
- 因子验证报告：`data/reports/generated/byd/factor-validation/factor_validation_report.md`
- 候选清单：`data/reports/generated/byd/scan/candidates.csv`
- 评分结果：`data/reports/generated/byd/score/scored_candidates.csv`
- 单股报告：`data/reports/generated/byd/stock-002594/stock_report.md`

## 常用 CLI

```bash
ashare ingest              # AkShare 或 fallback CSV 数据采集
ashare ingest-local        # 本地 fixture CSV 落库
ashare ingest-index-members
ashare ingest-announcements
ashare parse-announcements
ashare calculate-factors
ashare validate-factors
ashare report              # factor-validation 等报告
ashare event-study
ashare scan
ashare score
ashare backtest
ashare daily-report
ashare stock-report
ashare as-of
ashare db-init
ashare serve
ashare service-workflow
ashare service-scheduler
```

查看某个命令的参数：

```bash
conda run -n ashare-research-lab ashare scan --help
```

## 目录结构

```text
configs/       研究配置：数据、因子、验证、评分、回测、服务、审计
data/          本地数据、DuckDB、缓存、报告输出；多数内容不入 Git
docs/          规划、数据字典、因子定义、回测假设
notebooks/     研究 notebook
scripts/       fixture 构建等辅助脚本
skills/        Codex/agent 操作入口说明
src/ashare/    Python 包和 CLI 实现
tests/         单元测试、CLI 测试、fixture 测试
```

## 数据与审计口径

- 研究运行使用 `run_id`、`source_run_id`、`as_of_date` 和 `source_tag` 做追踪。
- 报告会写入 `run_manifest.json`，记录配置、输入 artifact、输出文件和 Git 状态。
- 多数据源共用同一个 DuckDB 时，命令应显式传入 `--data-source` / `--source-tag`。
- `factor_run_universe` 存在时，验证、扫描、评分、回测优先使用因子运行时的 universe 快照。
- 严格历史结论需要 `historical_pit` universe；AkShare 当前快照只能支持探索性实验。

## 测试

完整测试：

```bash
conda run -n ashare-research-lab pytest -q
```

常用局部测试：

```bash
conda run -n ashare-research-lab pytest -q tests/test_provider_checks.py
conda run -n ashare-research-lab pytest -q tests/test_factors.py
conda run -n ashare-research-lab pytest -q tests/test_score_cli.py tests/test_scan_cli.py
```

语法编译检查：

```bash
conda run -n ashare-research-lab python -m compileall -q src/ashare tests
```

## 常见问题

`provider_capability_check FAIL missing_apis=stock_a_lg_indicator`

当前代码已兼容 AkShare 新版本：`stock_a_lg_indicator` 缺失时会使用 `stock_zh_valuation_baidu` 抓取 `pe_ttm`、`pb` 和 `total_mv`。如果仍然失败，先确认安装的是当前仓库的 editable 包：

```bash
conda run -n ashare-research-lab python -m pip install -e .
```

AkShare 网络不稳定或接口断开

日线行情已经支持多个 AkShare endpoint fallback，但外部网络仍可能失败。可以重试，或使用 `--cache-mode use` 复用已有缓存。

历史 universe 为空

如果 `--universe-as-of` 晚于 `--from`，早期日期会没有 universe。这是 PIT 语义的结果。做 MVP 链路验证时可以把 `--universe-as-of` 设置为研究起点，但要把它视为当前快照静态回填。

评分里很多因子被跳过

`score` 会读取 `factor-validation` 的 validation gate。没有通过门槛的因子不会进入综合评分。这是研究保护机制，不是 CLI 失败。

## 研究使用声明

本仓库生成的候选清单、综合评分、回测、日报和单股报告都只用于研究复盘，不是买入、卖出、目标价、仓位或自动交易指令。
