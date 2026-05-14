# Phase 1a-3 Goal: Point-in-Time 查询层

请在已完成 Phase 1a-2 的 `/Users/crazy/own_project/ashare-research-lab` 仓库中继续实现 Phase 1a-3：Point-in-Time 查询层。

## 目标

1. 基于 Phase 1a-1 的 `effective_date` 规则和 Phase 1a-2 的本地 fixture 数据，实现 `as_of_date` 查询工具。
2. 确保任何 `publish_time` 或 `effective_date` 晚于 `as_of_date` 的数据都不可见。
3. 覆盖以下 PIT 查询对象：
   - `daily_prices`
   - `valuation_daily`
   - `universe_members`
   - `st_status`
   - `securities.delist_date`
   - `industry_classifications`
   - `fundamental_reports`
   - `announcements`
   - `risk_events`
4. 增加 `ashare as-of` CLI 命令，用于检查某个 `as_of_date` 下可见数据的行数和股票范围。
5. 不实现因子计算、scan、回测、LLM 或真实数据抓取。

## 工作约束

- 严格遵守 `docs/planning/a-share-research-plan.md`。
- 所有 Python 命令必须在 Conda 环境 `ashare-research-lab` 中执行。
- 只做查询层，不改写业务数据。
- 查询函数必须是只读逻辑，不执行 ingest，不生成 fixture，不修改 DuckDB 表内容。
- `load_as_of_snapshot(db_path=...)` 必须默认使用 DuckDB `read_only=True` 打开连接，并确保异常时也关闭连接。
- `query_*_as_of(connection=...)` 由调用方传入连接，docstring 中明确建议传入只读连接。
- PIT 查询必须显式传入 `as_of_date`，不能默认使用当前日期。
- 所有日期过滤必须使用参数化查询，避免把日期直接拼进 SQL 字符串。
- 所有查询必须写明确的 `ORDER BY`，保证测试和 CLI 输出确定性。
- `trading_calendar` 不作为本阶段 `AsOfSnapshot` 输出对象；未来交易日历可见不构成研究数据泄漏。
- Phase 1a-3 完成后单独 commit。
- 提交信息为：`feat: phase 1a-3 point-in-time as-of queries`

## 文件变更

建议新增或修改：

```text
src/ashare/pit/asof.py
src/ashare/pit/__init__.py
src/ashare/cli.py
tests/test_asof.py
tests/test_ingest_local.py 或 tests/test_phase0.py
```

说明：

- `src/ashare/pit/asof.py` 是本阶段核心文件。
- `src/ashare/cli.py` 只增加 `as-of` 命令，不实现 `scan` 真实逻辑。
- 测试文件可按现有风格拆分；如果现有 CLI help 测试维护命令列表，需要加入 `as-of`。
- 不需要修改 `schema.sql`，除非发现现有 schema 无法支持本阶段最小查询需求。

## 接口建议

在 `src/ashare/pit/asof.py` 中实现查询接口，建议以 DuckDB connection 为核心，避免函数内部重复打开数据库。

建议类型和接口：

```python
DateLike = str | date | datetime | pd.Timestamp

@dataclass(frozen=True)
class AsOfSnapshot:
    as_of_date: date
    daily_prices: pd.DataFrame
    valuation_daily: pd.DataFrame
    universe_members: pd.DataFrame
    securities: pd.DataFrame
    st_status: pd.DataFrame
    industry_classifications: pd.DataFrame
    fundamental_reports: pd.DataFrame
    announcements: pd.DataFrame
    risk_events: pd.DataFrame
```

建议函数：

```python
parse_as_of_date(value: DateLike) -> date

query_daily_prices_as_of(
    connection: duckdb.DuckDBPyConnection,
    as_of_date: DateLike,
    stock_code: str | None = None,
) -> pd.DataFrame

query_valuation_daily_as_of(
    connection: duckdb.DuckDBPyConnection,
    as_of_date: DateLike,
    stock_code: str | None = None,
) -> pd.DataFrame

query_universe_members_as_of(
    connection: duckdb.DuckDBPyConnection,
    as_of_date: DateLike,
    index_code: str | None = None,
) -> pd.DataFrame

query_securities_as_of(
    connection: duckdb.DuckDBPyConnection,
    as_of_date: DateLike,
    include_delisted: bool = False,
    stock_code: str | None = None,
) -> pd.DataFrame

query_st_status_as_of(
    connection: duckdb.DuckDBPyConnection,
    as_of_date: DateLike,
    stock_code: str | None = None,
) -> pd.DataFrame

query_industry_classifications_as_of(
    connection: duckdb.DuckDBPyConnection,
    as_of_date: DateLike,
    industry_standard: str | None = None,
    version: str | None = None,
    stock_code: str | None = None,
) -> pd.DataFrame

query_fundamental_reports_as_of(
    connection: duckdb.DuckDBPyConnection,
    as_of_date: DateLike,
    stock_code: str | None = None,
) -> pd.DataFrame

query_announcements_as_of(
    connection: duckdb.DuckDBPyConnection,
    as_of_date: DateLike,
    stock_code: str | None = None,
    announcement_type: str | None = None,
) -> pd.DataFrame

query_risk_events_as_of(
    connection: duckdb.DuckDBPyConnection,
    as_of_date: DateLike,
    stock_code: str | None = None,
    event_type: str | None = None,
) -> pd.DataFrame

build_as_of_snapshot(
    connection: duckdb.DuckDBPyConnection,
    as_of_date: DateLike,
    index_code: str | None = None,
    industry_standard: str | None = None,
    industry_version: str | None = None,
    include_delisted: bool = False,
    stock_code: str | None = None,
) -> AsOfSnapshot

load_as_of_snapshot(
    db_path: str | Path,
    as_of_date: DateLike,
    index_code: str | None = None,
    industry_standard: str | None = None,
    industry_version: str | None = None,
    include_delisted: bool = False,
    stock_code: str | None = None,
) -> AsOfSnapshot
```

`load_as_of_snapshot` 内部打开 `read_only=True` 连接，函数结束或抛异常时必须关闭连接。

## `as_of_date` 解析规则

`parse_as_of_date` 规则：

- `str` 必须是 ISO 日期格式，例如 `2026-01-12`。
- `date` 原样返回。
- `datetime` 一律取 `.date()`，不报错也不警告。
- `pandas.Timestamp` 一律取 `.date()`。
- 不要求 `as_of_date` 必须是交易日。
- `as_of_date` 早于 fixture 起点时，各 PIT 数据查询应自然返回空结果。
- `as_of_date` 晚于 fixture 末尾时，应返回截至该日期所有已经可见的数据。

## 查询规则

### `daily_prices`

使用：

```text
trade_date <= as_of_date
```

支持按 `stock_code` 可选过滤。

排序：

```text
ORDER BY stock_code, trade_date
```

### `valuation_daily`

使用：

```text
trade_date <= as_of_date
```

支持按 `stock_code` 可选过滤。

排序：

```text
ORDER BY stock_code, trade_date
```

### `universe_members`

使用半开区间：

```text
in_date <= as_of_date
AND (out_date IS NULL OR as_of_date < out_date)
```

如果传入 `index_code`，必须额外过滤 `index_code`。

不要把未来 `out_date` 暴露给下游结果。返回结果中使用 mask：

```sql
CASE WHEN out_date IS NOT NULL AND out_date <= ?
     THEN out_date ELSE NULL END AS out_date
```

排序：

```text
ORDER BY index_code, stock_code, in_date
```

### `st_status`

使用半开区间：

```text
in_date <= as_of_date
AND (out_date IS NULL OR as_of_date < out_date)
```

返回的是 `as_of_date` 当天有效的 ST 状态。

不要用当前股票名称推导历史 ST。

返回结果中对未来 `out_date` 做 mask。

排序：

```text
ORDER BY stock_code, in_date, st_type
```

### `securities`

至少支持：

```text
list_date <= as_of_date
```

并派生：

```text
is_delisted_as_of = delist_date IS NOT NULL AND delist_date <= as_of_date
```

默认 `include_delisted = False` 时，过滤掉 `is_delisted_as_of = true` 的股票。

当 `delist_date > as_of_date` 时，查询结果中不要暴露该未来退市日期。

建议 SQL 结构：

```sql
SELECT
  stock_code,
  stock_name,
  exchange,
  list_date,
  CASE
    WHEN delist_date IS NOT NULL AND delist_date <= ?
    THEN delist_date
    ELSE NULL
  END AS delist_date,
  (delist_date IS NOT NULL AND delist_date <= ?) AS is_delisted_as_of
FROM securities
WHERE list_date <= ?
```

如 `include_delisted = false`，再过滤：

```text
AND (delist_date IS NULL OR delist_date > as_of_date)
```

排序：

```text
ORDER BY stock_code
```

### `industry_classifications`

使用半开区间：

```text
in_date <= as_of_date
AND (out_date IS NULL OR as_of_date < out_date)
```

支持按 `industry_standard`、`version`、`stock_code` 可选过滤。

`industry_version=None` 表示不过滤版本。本阶段不从配置文件推导默认行业版本；默认版本选择留给后续因子层或配置层处理。

返回结果中对未来 `out_date` 做 mask。

排序：

```text
ORDER BY stock_code, industry_standard, version, in_date
```

### `fundamental_reports`

必须同时满足：

```text
DATE(publish_time) <= as_of_date
AND effective_date <= as_of_date
```

不能只按 `report_period` 过滤。

这两个条件在当前 Phase 1a-1 规则下通常由 `effective_date <= as_of_date` 蕴含，但本阶段仍保留双条件，作为防御性约束，避免未来更改生效规则时发生 PIT 泄漏。

本阶段不做 `latest-revision-wins`。如果同一 `(stock_code, report_period)` 有多次披露或修订，本查询只负责 PIT 过滤，后续因子层再决定如何选择最新版本。

排序：

```text
ORDER BY stock_code, report_period, publish_time
```

### `announcements`

必须同时满足：

```text
DATE(publish_time) <= as_of_date
AND effective_date <= as_of_date
```

支持按 `stock_code` 和 `announcement_type` 可选过滤。

不解析公告正文，不调用 LLM。

排序：

```text
ORDER BY stock_code, publish_time, announcement_id
```

### `risk_events`

必须同时满足：

```text
DATE(publish_time) <= as_of_date
AND effective_date <= as_of_date
```

支持按 `stock_code` 和 `event_type` 可选过滤。

`event_date` 不应单独决定可见性；PIT 可见性以 `publish_time` 和 `effective_date` 为准。

`payload_json` 在返回 DataFrame 中按 DuckDB 读取结果原样保留，不在本阶段解析成 dict；因子层后续负责解释具体 JSON 结构。

排序：

```text
ORDER BY stock_code, publish_time, event_id
```

## CLI 要求

在 `src/ashare/cli.py` 增加命令：

```text
as-of
```

建议参数：

```text
--as-of              必填，ISO 日期，例如 2026-01-12
--db-path            默认 data/processed/ashare.duckdb
--index-code         可选，例如 LOCAL_FIXTURE
--industry-standard  可选
--industry-version   可选
--include-delisted   默认 false
--stock-code         可选
```

行为：

- 以只读方式打开 DuckDB。
- 调用 `load_as_of_snapshot` 或等价查询函数。
- 打印 `as_of_date`、各 PIT 查询对象的行数。
- 打印当前 universe 的股票代码列表。
- 如果传入 `--stock-code`，各支持股票过滤的查询只展示该股票相关数据。
- 不写文件。
- 不生成报告。
- 不执行 scan。
- 不计算因子。

## 测试要求

新增 `tests/test_asof.py`，至少覆盖：

1. `daily_prices` 只返回 `trade_date <= as_of_date` 的行情。
2. `valuation_daily` 只返回 `trade_date <= as_of_date` 的估值。
3. `fundamental_reports` 在 `publish_time=2026-01-05 18:00:00`、`effective_date=2026-01-06` 时：
   - `as_of_date=2026-01-05` 不可见。
   - `as_of_date=2026-01-06` 可见。
4. `announcements` 中 `buyback` 在 `publish_time=2026-01-09 18:00:00`、`effective_date=2026-01-12` 时：
   - `as_of_date=2026-01-09` 不可见。
   - `as_of_date=2026-01-12` 可见。
5. `risk_events` 中 `shareholder_reduce` 在 `effective_date=2026-01-12` 前不可见，生效日当天可见。
6. `universe_members` 使用 `[in_date, out_date)`：
   - 退市样例股票在 `out_date` 前仍属于历史 universe。
   - 到 `out_date` 当天不再属于当前 universe。
   - 返回结果不暴露未来 `out_date`。
7. `st_status` 使用 `[in_date, out_date)`：
   - ST 区间开始日前不可见。
   - 开始日可见。
   - `out_date` 当天不可见。
   - 返回结果不暴露未来 `out_date`。
8. `securities.delist_date`：
   - 退市日前 `is_delisted_as_of = false`。
   - 退市日前不暴露未来 `delist_date`。
   - 退市日当天或之后 `is_delisted_as_of = true`。
   - 默认查询不返回已退市股票。
   - `include_delisted=True` 可以返回已退市股票。
9. `industry_classifications` 能按 `as_of_date` 返回当时有效行业。
10. 在 `tmp_path` DuckDB 中手动插入行业切换样例，覆盖：
    - `as_of_date < out_date` 时旧行业有效。
    - `as_of_date >= out_date` 时旧行业失效，新行业生效或旧行业查不到。
    - 未来未发生切换时返回结果不暴露未来 `out_date`。
11. 查询结果不包含 `publish_time` 或 `effective_date` 晚于 `as_of_date` 的财报、公告、风险事件。
12. `build_as_of_snapshot` 返回 9 类对象，且每类对象都是确定性排序结果。
13. `parse_as_of_date` 对 `str`、`date`、`datetime`、`pandas.Timestamp` 行为正确。
14. `as_of_date` 早于 fixture 起点时，PIT 数据查询自然返回空结果。
15. `as_of_date` 晚于 fixture 末尾时，所有已生效 fixture 数据自然可见。
16. `load_as_of_snapshot` 使用只读连接；可以在测试中尝试通过只读连接写入并确认失败。
17. `ashare as-of --as-of ... --db-path ... --index-code LOCAL_FIXTURE` 可以成功运行。
18. `ashare as-of --include-delisted` 可以成功运行并展示退市样例。
19. `ashare --help` 可以看到 `as-of`，同时 Phase 0、Phase 1a-1、Phase 1a-2 命令仍存在。

测试数据应通过 Phase 1a-2 的 fixture builder 和 `ingest_local` 在 `tmp_path` 下构造，不依赖仓库内已有 DuckDB 文件。

## 验收命令

以下命令必须全部成功：

```bash
conda run -n ashare-research-lab python -m pip install -e .

conda run -n ashare-research-lab ashare ingest-local \
  --input-dir tests/fixtures/generated \
  --db-path data/processed/ashare.duckdb

conda run -n ashare-research-lab ashare as-of \
  --as-of 2026-01-05 \
  --db-path data/processed/ashare.duckdb \
  --index-code LOCAL_FIXTURE

conda run -n ashare-research-lab ashare as-of \
  --as-of 2026-01-12 \
  --db-path data/processed/ashare.duckdb \
  --index-code LOCAL_FIXTURE

conda run -n ashare-research-lab ashare as-of \
  --as-of 2026-03-06 \
  --db-path data/processed/ashare.duckdb \
  --index-code LOCAL_FIXTURE \
  --include-delisted

conda run -n ashare-research-lab pytest -q

conda run -n ashare-research-lab ashare --help
```

`ashare --help` 必须能看到：

- `as-of`
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

## 完成后

1. 运行 `git status`，确认只包含 Phase 1a-3 相关改动。
2. 执行 `git add .`。
3. 执行：

```bash
git commit -m "feat: phase 1a-3 point-in-time as-of queries"
```

4. 最终回复说明：
   - 修改了哪些文件。
   - `as_of_date` 查询覆盖了哪些表。
   - 如何防止未来 `publish_time` / `effective_date` / `out_date` / `delist_date` 可见。
   - fixture 边界测试是否覆盖 ST、退市、公告、财报、风险事件、行情、估值、行业切换。
   - 验收命令是否全部通过。
   - commit hash。
   - 是否发现 plan 或前置 phase 的缺口。

## 不要实现

- 不实现因子计算。
- 不实现 `scan` 真实逻辑。
- 不实现 `validate-factors` 真实逻辑。
- 不实现事件研究。
- 不实现回测。
- 不实现 LLM。
- 不调用 AkShare。
- 不接真实沪深 300 数据。
- 不生成 Markdown / CSV 研究报告。
- 不写 `factor_values`。
- 不实现服务化 API。
- 不改造数据源抓取流程。
- 不引入复杂快照系统或 `research_runs` 正式运行逻辑。
- 不实现财报修订选择逻辑，例如 `latest-revision-wins`。

## 发现的缺口

- 现有 plan/schema 中，`universe_members`、`st_status`、`industry_classifications`、`securities.delist_date` 没有 `publish_time` / `effective_date` 字段。严格 PIT 下，未来的 `out_date` 或 `delist_date` 何时被市场知道无法完全表达。本 phase 应在查询结果中 mask 未来 `out_date` / `delist_date`，但真正解决需要后续 schema 设计补充。
- Phase 1a-2 fixture 的行业分类目前偏静态。行业切换测试可在 `tests/test_asof.py` 的临时 DuckDB 中插入最小补充行，不需要改 fixture builder。
