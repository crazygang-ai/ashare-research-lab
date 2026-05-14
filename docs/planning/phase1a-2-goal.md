# Phase 1a-2 Goal: Local Fixture Data Ingest

请在已完成 Phase 1a-1 的 `/Users/crazy/own_project/ashare-research-lab` 仓库中继续实现 Phase 1a-2：本地合成样例数据导入。

## 目标

1. 创建一套可控的合成样例数据。
2. 实现本地 CSV 数据导入 DuckDB。
3. 增加 `ashare ingest-local` 命令。
4. 验证导入后的数据覆盖退市、ST、停牌、涨跌停、财报生效、公告和风险事件等边界场景。
5. 不接真实 AkShare，不做因子计算。

## 工作约束

- 严格遵守 `docs/planning/a-share-research-plan.md`。
- 所有 Python 命令必须在 Conda 环境 `ashare-research-lab` 中执行。
- 不实现真实数据抓取。
- 不调用 AkShare。
- 不调用 LLM。
- 不实现因子计算。
- 不实现回测。
- Phase 1a-2 完成后单独 commit，提交信息为：`feat: phase 1a-2 local fixture ingest`。

## 核心原则

- 合成数据必须小而完整，方便测试。
- 合成数据可以是伪造价格，但必须严格符合 `schema.sql`。
- fixture 生成逻辑和 ingest 逻辑分开。
- 数据导入逻辑不能写死测试路径。
- 所有带 `publish_time` 的数据，导入时必须调用 `pit/effective_date.py` 计算 `effective_date`。
- `ingest-local` 会清空目标表后重写，仅用于本地 fixture / 开发测试。

## 1. Fixture Builder

新增：

```text
src/ashare/fixtures/
  __init__.py
  builder.py

scripts/
  build_fixtures.py
```

要求：

- 真正的生成逻辑放在 `src/ashare/fixtures/builder.py`。
- `scripts/build_fixtures.py` 只做 thin wrapper。
- CLI、tests、script 都 import `ashare.fixtures.builder.build_fixtures`。
- 不让业务代码依赖 `tests` 包。
- 不让 CLI 通过 `subprocess` 调用 `scripts/build_fixtures.py`。

建议接口：

```python
def build_fixtures(output_dir: Path) -> None:
    ...
```

`scripts/build_fixtures.py` 支持：

```bash
python scripts/build_fixtures.py --output-dir tests/fixtures/generated
```

## 2. Generated Fixture 目录

生成目录：

```text
tests/fixtures/generated/
```

要求：

- `tests/fixtures/generated/` 是生成产物，不提交到 git。
- 将 `tests/fixtures/generated/` 加入 `.gitignore`。
- `ashare ingest-local` 默认 `--build-fixtures=true`，可每次重建 fixture。

生成这些 CSV 文件：

```text
trading_calendar.csv
securities.csv
industry_classifications.csv
universe_members.csv
daily_prices.csv
st_status.csv
fundamental_reports.csv
valuation_daily.csv
announcements.csv
risk_events.csv
```

## 3. Fixture 数据设计

股票数量：5 只。

```text
000001.SZ  正常股票
000002.SZ  期间出现 ST
000003.SZ  期间退市
000004.SZ  期间有停牌日
000005.SZ  期间出现涨停/跌停边界
```

交易日历：

- 使用固定日期区间，例如从 `2026-01-05` 开始。
- 只生成工作日作为交易日。
- 生成 60 个主要样本交易日。
- 额外生成 3 个尾部 buffer 交易日，避免 T+1 生效日找不到。
- 测试主样本逻辑时可以断言前 60 个交易日；`trading_calendar` 总行数应至少为 63。

`publish_time` 规则：

- `fundamental_reports`、`announcements`、`risk_events` 的 `publish_time` 应落在前 60 个主要样本交易日内。
- 不要把 `publish_time` 放在最后一个交易日，避免没有后续交易日导致 `ValueError`。

必须覆盖的边界：

- 1 只股票有 `delist_date`。
- 1 只股票有 `st_status` 区间。
- `daily_prices` 中至少有 1 行 `is_suspended = true`。
- `daily_prices` 中至少有 1 行 `close == limit_up`，且该行 `limit_up` / `limit_down` 字段非空。
- `daily_prices` 中至少有 1 行 `close == limit_down`，且该行 `limit_up` / `limit_down` 字段非空。
- `risk_events` 中至少包含 `pledge`、`shareholder_reduce`、`inquiry_letter`、`non_standard_audit`。
- `fundamental_reports` 中至少包含 `goodwill`、`total_equity`、`accounts_receivable`、`inventory`。
- `announcements` 中至少包含 `earnings_forecast`、`buyback`、`inquiry_letter`。

## 4. 本地导入模块

新增：

```text
src/ashare/ingest/
  __init__.py
  local.py
```

建议接口：

```python
def ingest_local(input_dir: str | Path, db_path: str | Path) -> dict[str, int]:
    ...
```

要求：

- 调用 `storage.db.init_db` 确保数据库和 schema 已初始化。
- 从 `input_dir` 读取 CSV 文件。
- 将数据插入 DuckDB 对应表。
- 支持重复运行。
- 第一版采用简单策略：导入前 `DELETE` 对应表，再 `INSERT`。
- 返回导入表名和行数摘要。
- 不实现增量 upsert。
- 不实现真实网络数据抓取。
- 在 docstring 或 CLI 输出中明确：`ingest-local` 会清空目标表后重写，仅用于 fixture / 开发测试。

导入顺序必须固定：

```text
init_db
  -> trading_calendar
  -> securities / industry_classifications / universe_members
  -> daily_prices / st_status / valuation_daily
  -> fundamental_reports / announcements / risk_events
```

带 `publish_time` 的表最后导入：

- `fundamental_reports`
- `announcements`
- `risk_events`

这些表导入时：

- 从 DuckDB 中已导入的 `trading_calendar` 读取 `is_open = true` 的 `trade_date`。
- 调用 `pit/effective_date.py` 计算 `effective_date`。
- 推荐 fixture CSV 不写 `effective_date`，由 `ingest-local` 负责计算。
- 第一版统一 T+1 交易日生效。

JSON 字段要求：

- `risk_events.payload_json` 是 DuckDB `JSON` 类型。
- 从 CSV 导入时必须显式 cast：`CAST(payload_json AS JSON)`。

## 5. CLI 命令

修改 `src/ashare/cli.py`，增加：

```text
ingest-local
```

要求：

- Python 函数名：`ingest_local`。
- CLI 声明：`@app.command(name="ingest-local")`。
- 参数：
  - `--input-dir`，默认 `tests/fixtures/generated`
  - `--db-path`，默认 `data/processed/ashare.duckdb`
  - `--build-fixtures / --no-build-fixtures`，默认 true
- Typer 写法：

```python
build_fixtures: bool = typer.Option(
    True,
    "--build-fixtures/--no-build-fixtures",
)
```

行为：

- 如果 `--build-fixtures` 为 true，先调用 `ashare.fixtures.builder.build_fixtures` 生成 fixture。
- 然后调用 `ashare.ingest.local.ingest_local` 导入。
- 成功后打印导入目录、数据库路径、导入的表名和行数摘要。

## 6. 测试要求

新增或更新：

```text
tests/test_fixtures.py
tests/test_ingest_local.py
```

至少覆盖：

1. fixture 生成后，所有预期 CSV 文件存在。
2. `trading_calendar` 至少有 63 个交易日，其中前 60 个是主要样本交易日。
3. `securities` 有 5 只股票。
4. 至少 1 只股票有 `delist_date`。
5. `st_status` 至少有 1 条 ST 区间记录。
6. `daily_prices` 包含停牌记录。
7. `daily_prices` 至少有 1 行 `close == limit_up`。
8. `daily_prices` 至少有 1 行 `close == limit_down`。
9. `risk_events` 包含 `pledge`、`shareholder_reduce`、`inquiry_letter`、`non_standard_audit`。
10. `payload_json` 成功写入 DuckDB `JSON` 列。
11. `ingest_local` 可以把 fixture 导入 `tmp_path` 下的 DuckDB。
12. 导入后各核心表行数符合预期。
13. `fundamental_reports` / `risk_events` / `announcements` 的 `effective_date` 被正确计算。
14. 连续执行 `ingest_local` 两次不失败，且不会重复膨胀数据。
15. `ashare ingest-local --input-dir ... --db-path ...` 可以成功运行。

有效日期测试示例：

```text
publish_time = 2026-01-05 18:00:00
effective_date = 2026-01-06

publish_time = 2026-01-09 18:00:00
effective_date = 2026-01-12
```

## 7. 验收命令

以下命令必须全部成功：

```bash
conda run -n ashare-research-lab python -m pip install -e .

conda run -n ashare-research-lab python scripts/build_fixtures.py \
  --output-dir tests/fixtures/generated

conda run -n ashare-research-lab ashare ingest-local \
  --input-dir tests/fixtures/generated \
  --db-path data/processed/ashare.duckdb

conda run -n ashare-research-lab pytest -q

conda run -n ashare-research-lab ashare --help
```

`ashare --help` 必须能看到：

- `db-init`
- `ingest-local`

同时 Phase 0 的 7 个命令仍然存在：

- `ingest`
- `validate-factors`
- `event-study`
- `scan`
- `backtest`
- `report`
- `stock-report`

## 8. 完成后

1. 运行 `git status`，确认只包含 Phase 1a-2 相关改动。
2. 执行 `git add .`。
3. 执行 `git commit -m "feat: phase 1a-2 local fixture ingest"`。
4. 最终回复说明：
   - 新增了哪些文件。
   - fixture 覆盖了哪些边界场景。
   - `ingest-local` 的默认 `input-dir` 和 `db-path`。
   - `effective_date` 是否在导入时计算。
   - 验收命令是否全部通过。
   - commit hash。
   - 是否发现 plan / Phase 1a-1 的缺口。

## 不要实现

- AkShare 抓取。
- 真实沪深 300 数据。
- 因子计算。
- `scan` 真实逻辑。
- `validate-factors` 真实逻辑。
- `backtest` 真实逻辑。
- LLM 调用。
- 复杂 upsert。
- 分区 Parquet 存储。
