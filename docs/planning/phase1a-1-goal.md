# Phase 1a-1 Goal: PIT Module + DuckDB Initialization

请在已完成 Phase 0 的 `/Users/crazy/own_project/ashare-research-lab` 仓库中继续实现 Phase 1a-1：PIT 模块 + DuckDB 初始化。

## 目标

1. 实现 Point-in-Time 生效日期纯函数。
2. 实现 DuckDB 连接和 schema 初始化。
3. 增加 `ashare db-init` 命令。
4. 增加单测，确保 PIT 规则和 schema 初始化可复现。

## 工作约束

- 严格遵守 `docs/planning/a-share-research-plan.md`。
- 所有 Python 命令必须在 Conda 环境 `ashare-research-lab` 中执行。
- 不实现真实数据抓取。
- 不实现本地数据导入。
- 不实现因子计算。
- 不实现回测。
- 不调用 AkShare。
- 不调用 LLM。
- Phase 1a-1 完成后单独 commit，提交信息为：`feat: phase 1a-1 pit and database init`。

## 1. `src/ashare/pit/effective_date.py`

实现纯函数，用于计算财报、公告、风险事件的 `effective_date`。

建议接口：

```python
next_trading_day(after_date: date, trading_days: Sequence[date]) -> date
calculate_effective_date(publish_time: date | datetime, trading_days: Sequence[date]) -> date
```

规则：

- `effective_date` 等于 `publish_date` 严格大于意义下的第一个交易日。
- 即使 `publish_date` 本身是交易日，也必须取下一个交易日。
- 第一版不区分盘中、盘后，统一下一个交易日生效。
- 如果 `publish_time` 是 `datetime`，只取其日期部分。
- 如果 `publish_time` 是非交易日，也取该日期之后的第一个交易日。
- `trading_days` 必须先排序或函数内部排序，避免输入顺序影响结果。
- 如果找不到后续交易日，抛出 `ValueError`。
- `pit/effective_date.py` 必须是纯函数模块，不 import `duckdb`，不读取数据库，不读取文件。
- 从 DB 读取交易日历再调用纯函数的逻辑属于后续 `pit/asof.py`，本阶段不实现。

## 2. `src/ashare/storage/db.py`

实现 DuckDB 基础能力。

建议接口：

```python
connect(db_path: str | Path) -> duckdb.DuckDBPyConnection
default_schema_path() -> Path
init_db(db_path: str | Path, schema_path: str | Path | None = None) -> None
```

规则：

- `db_path` 的父目录不存在时自动创建。
- `schema_path` 默认使用 Phase 0 已创建的 `schema.sql`。
- `init_db` 必须读取 `schema.sql` 并在 DuckDB 中执行。
- 多次运行 `init_db` 应该幂等，不应因为表已存在而失败。
- `schema.sql` 预期已经使用 `CREATE TABLE IF NOT EXISTS`；只有发现确实不幂等才修，避免无关 schema 变更。
- 如果 `init_db` 因 DuckDB `JSON` 类型失败，在执行 schema 前先 `INSTALL json; LOAD json;`，否则不要加。
- 不在 `db.py` 中写业务表导入逻辑。

## 3. `src/ashare/cli.py`

增加一个新命令：

- `db-init`

要求：

- Python 函数名使用 `db_init`。
- 用 `@app.command(name="db-init")` 显式声明 CLI 名。
- 参数：
  - `--db-path`，默认 `data/processed/ashare.duckdb`
  - `--schema-path`，可选，默认使用内置 `schema.sql`
- 命令执行 `init_db`。
- 成功后打印初始化的 db path 和 schema path。
- 如果 Phase 0 测试断言 CLI 命令数量恰好为 7，更新为“7 个 Phase 0 命令仍存在”，允许新增 `db-init`。

## 4. `tests/test_pit.py`

覆盖 PIT 规则：

- 普通交易日披露：`2026-01-05` 披露，生效日为严格大于该日的下一个交易日。
- 周五披露：生效日为下周一交易日。
- 周末披露：生效日为下一个交易日。
- `datetime` 输入只取日期。
- `trading_days` 输入乱序也能得到正确结果。
- 找不到后续交易日时抛出 `ValueError`。

使用测试内固定 `trading_days`，不依赖真实交易日历。

## 5. `tests/test_db.py`

覆盖数据库初始化：

- `init_db` 可以在 `tmp_path` 下创建 DuckDB 文件。
- `schema.sql` 可以被 DuckDB 直接执行。
- 初始化后至少能查询到这些表存在：
  - `trading_calendar`
  - `securities`
  - `daily_prices`
  - `st_status`
  - `risk_events`
  - `factor_values`
  - `research_runs`
- 连续执行 `init_db` 两次不失败。
- `ashare db-init --db-path <tmp_path/test.duckdb>` 可以成功运行。

## 6. 如有必要，修正 `schema.sql`

要求：

- 预期无需修改。
- 只有发现 `schema.sql` 不是幂等或不能被 DuckDB 执行时才修。
- 不新增 Phase 1a-1 不需要的业务逻辑。

## 验收命令

以下命令必须全部成功：

```bash
conda run -n ashare-research-lab python -m pip install -e .
conda run -n ashare-research-lab ashare db-init --db-path data/processed/ashare.duckdb
conda run -n ashare-research-lab pytest -q
conda run -n ashare-research-lab ashare --help
```

`ashare --help` 必须能看到 `db-init` 命令，同时 Phase 0 的 7 个命令仍然存在：

- `ingest`
- `validate-factors`
- `event-study`
- `scan`
- `backtest`
- `report`
- `stock-report`

## 完成后

1. 运行 `git status`，确认只包含 Phase 1a-1 相关改动。
2. 执行 `git add .`。
3. 执行 `git commit -m "feat: phase 1a-1 pit and database init"`。
4. 最终回复说明：
   - 改了哪些文件。
   - PIT 规则如何实现。
   - DuckDB 初始化默认路径是什么。
   - 验收命令是否全部通过。
   - commit hash。
   - 是否发现 plan 或 Phase 0 代码中的缺口。

## 不要实现

- `ingest-local`
- `tests/fixtures` 合成数据
- AkShare 抓取
- 因子计算
- 回测
- LLM
