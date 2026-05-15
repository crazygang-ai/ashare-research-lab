# Phase 1a-7 Goal: 真实数据接入试点

请在已完成 Phase 1a-6 的 `/Users/crazy/own_project/ashare-research-lab` 仓库中继续实现 Phase 1a-7：真实数据接入试点。

本 phase 只做小范围真实数据接入验证：

- 小范围接入真实行情、估值、指数成分数据。
- 优先沪深 300。
- 只接少量字段。
- 实现数据缓存、字段校验、数据质量报告。
- 保留本地 CSV fallback。
- 不扩到全 A。
- 不引入 LLM。
- 不做生产级数据平台。

## 目标

1. 将现有 `ashare ingest` 从空壳改为真实数据接入试点命令。
2. 建立真实数据 provider 抽象，优先实现 AkShare 小范围 provider。
3. 支持本地 CSV fallback，且 fallback 不得静默冒充真实源成功。
4. 接入并落库以下最小数据集：
   - `trading_calendar`
   - `securities`
   - `universe_members`
   - `daily_prices`
   - `valuation_daily`
5. 对接入数据做字段校验和数据质量检查。
6. 将原始 / 规范化数据缓存到本地 Parquet。
7. 输出数据质量 Markdown / CSV 报告。
8. 保持 Phase 1a-3.5 的 PIT 可见性语义。
9. 不调用因子计算、验证、scan、report 或回测逻辑。

## 工作约束

- 严格遵守 `docs/planning/a-share-research-plan.md`。
- 所有 Python 命令必须在 Conda 环境 `ashare-research-lab` 中执行。
- 每个 phase 必须单独 commit。
- 本 phase 不写入 `factor_values`。
- 本 phase 不写入 `research_runs`。
- 本 phase 不新增 DuckDB 表。
- 本 phase 默认不修改 `schema.sql`。
- 本 phase 选择 **不为 `daily_prices` 增加 `source` 字段**。`daily_prices`、`trading_calendar`、`securities` 仍按当前 schema 处理。
- 不允许在同一 DuckDB 中混用 fixture ingest 与真实 ingest。由于 `daily_prices`、`trading_calendar`、`securities` 缺少 `source` 字段，混用会造成不可审计覆盖；CLI 必须检测明显混源场景并 fail-fast，要求用户使用单独 DB。
- 本 phase 不接财务报表、公告、风险事件、行业真实数据。
- 本 phase 不实现全量历史沪深 300 PIT 成分库。
- 如果数据源只提供当前成分，不得把当前成分伪装成完整历史成分。
- pytest 不依赖真实网络或上游 AkShare 可用性。
- Phase 1a-7 完成后单独 commit。
- 提交信息为：`feat: phase 1a-7 real data ingest pilot`

## 数据范围

### Universe

优先支持：

```text
universe = hs300
canonical index_code = 000300.SH
```

CLI 可接受：

```text
--universe hs300
```

内部默认映射为：

```text
index_code = 000300.SH
```

不得在本 phase 增加全 A、中证 500 或多指数配置。

### 数据集

只覆盖：

```text
trading_calendar
securities
universe_members
daily_prices
valuation_daily
```

不覆盖：

```text
fundamental_reports
announcements
risk_events
industry_classifications
st_status
factor_values
research_runs
```

### effective_source 枚举

`effective_source` 只能取：

```text
akshare
csv
csv_fallback
```

含义：

- `--source akshare` 成功时：`effective_source = akshare`
- `--source csv` 成功时：`effective_source = csv`
- `--source auto` 且 AkShare 成功时：`effective_source = akshare`
- `--source auto` 且 AkShare 失败并显式允许 fallback 时：`effective_source = csv_fallback`

`--source auto` 未传 `--allow-fallback` 时，CLI 必须启动即打印 warning：

```text
--source auto without --allow-fallback is equivalent to --source akshare.
```

## 字段范围

### `daily_prices`

至少规范化：

```text
stock_code
trade_date
open
high
low
close
volume
amount
adj_factor
is_suspended
limit_up
limit_down
```

规则：

- 当前 schema 没有 `source` 字段，本 phase 不新增。
- `adj_factor` 缺失允许为 `NULL`。
- 不从前复权或后复权价格反推 `adj_factor`。
- `is_suspended` 如果真实源不能可靠提供，允许为 `false` 或 `NULL`，但质量报告必须标记字段可信度不足。
- 不主动补造停牌日行情行。
- 不主动推断涨跌停价格，除非真实源直接给出明确字段来源。

### `valuation_daily`

至少规范化：

```text
stock_code
trade_date
pe_ttm
pb
ps
dividend_yield
total_mv
float_mv
source
```

规则：

- `source` 写入 `--source-tag`。
- `pe_ttm` / `pb` 是本 phase 优先字段。
- `ps`、`dividend_yield`、`total_mv`、`float_mv` 如源不可用，允许为 `NULL`，但质量报告必须统计缺失率。
- `pe_ttm <= 0` 或 `pb <= 0` 不在 ingest 阶段删除，只进入 warning / issues。

### `universe_members`

至少规范化：

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
```

规则：

- `source` 写入 `--source-tag`。
- 如果真实源提供历史进入 / 退出日期，按源字段写入。
- 如果真实源只提供当前成分快照，不得回填为历史成分。
- 当前成分快照的保守写法：
  - `in_date = universe_as_of_date`
  - `in_effective_date = universe_as_of_date`
  - `out_date = NULL`
  - `out_effective_date = NULL`
- 如果 `publish_time` 无来源，允许为 `NULL`。
- 数据质量报告必须说明指数成分是历史成分还是当前快照。
- `--universe-as-of` 默认等于 `--from`，不是 `--to`。
- 如果显式传入 `--universe-as-of > --from`，CLI 必须 warning，说明 `from <= as_of < universe_as_of` 期间 PIT universe 可能为空。

### `securities`

当前 schema 没有 `source` 字段。

规则：

- 如果 provider 提供股票名称，写入 `stock_name`。
- `exchange` 从代码后缀推导，例如 `.SH` / `.SZ`。
- 如果 provider 提供真实 `list_date`，使用真实值。
- 如果没有真实 `list_date`，使用 `universe_as_of_date` 作为试点可见起点，并在质量报告中标记为 synthetic list_date。
- 不接真实退市数据；`delist_date` / `delist_publish_time` / `delist_effective_date` 可为空。

## AkShare Provider 要求

AkShare 具体调用只允许封装在 `src/ashare/ingest/akshare_provider.py`。

初始实现优先包装以下 API；如果当前 AkShare 版本缺失或返回字段不兼容，provider 必须 fail-fast，并由 CSV fallback 或测试 mock 覆盖硬验收路径：

```text
trading_calendar: tool_trade_date_hist_sina
index members: index_stock_cons_csindex
daily prices: stock_zh_a_hist
valuation: stock_a_lg_indicator
securities fallback/name lookup: stock_info_a_code_name 或 index members 返回字段
```

核心字段映射至少覆盖：

```text
stock_zh_a_hist:
  日期 -> trade_date
  开盘 -> open
  最高 -> high
  最低 -> low
  收盘 -> close
  成交量 -> volume
  成交额 -> amount

index_stock_cons_csindex:
  成分券代码 / 品种代码 / 证券代码 -> stock_code
  成分券名称 / 证券简称 -> stock_name

stock_a_lg_indicator:
  日期 / trade_date -> trade_date
  市盈率TTM / pe_ttm -> pe_ttm
  市净率 / pb -> pb
  市销率 / ps -> ps
  股息率 / dividend_yield -> dividend_yield
  总市值 / total_mv -> total_mv
```

要求：

- 字段重命名和类型转换不得散落在 CLI。
- AkShare API 返回中文列名或英文列名都应通过 normalization 层统一。
- AkShare provider 的单元测试必须 mock AkShare 返回 DataFrame，不依赖网络。

## 文件变更

建议新增或修改：

```text
src/ashare/ingest/providers.py
src/ashare/ingest/akshare_provider.py
src/ashare/ingest/csv_fallback.py
src/ashare/ingest/cache.py
src/ashare/ingest/contracts.py
src/ashare/ingest/quality.py
src/ashare/ingest/real_pilot.py
src/ashare/cli.py
configs/data.yaml
configs/universe.yaml
docs/planning/followups.md
tests/test_ingest_providers.py
tests/test_ingest_cache.py
tests/test_ingest_contracts.py
tests/test_ingest_quality.py
tests/test_ingest_real_pilot.py
tests/test_ingest_cli.py
```

可选修改：

```text
.gitignore
```

仅当当前仓库未忽略生成缓存或报告目录时，允许加入：

```gitignore
data/raw/cache/
data/reports/generated/
```

不应提交真实行情数据、缓存 Parquet、DuckDB 文件或生成的数据质量报告。

## Provider 接口建议

在 `src/ashare/ingest/providers.py` 中定义：

```python
class MarketDataProvider(Protocol):
    name: str

    def fetch_trading_calendar(
        self,
        start_date: date,
        end_date: date,
    ) -> pd.DataFrame:
        ...

    def fetch_index_members(
        self,
        index_code: str,
        as_of_date: date,
    ) -> pd.DataFrame:
        ...

    def fetch_daily_prices(
        self,
        stock_codes: Sequence[str],
        start_date: date,
        end_date: date,
    ) -> pd.DataFrame:
        ...

    def fetch_valuation_daily(
        self,
        stock_codes: Sequence[str],
        start_date: date,
        end_date: date,
    ) -> pd.DataFrame:
        ...
```

要求：

- provider 返回原始 DataFrame。
- normalization 层负责字段重命名、类型转换、股票代码规范化。
- provider 失败时抛出明确异常，不静默返回空表。

## CSV fallback

在 `src/ashare/ingest/csv_fallback.py` 中实现：

```python
class CsvFallbackProvider:
    ...
```

要求：

- 从 `--fallback-csv-dir` 读取本地 CSV。
- 只读取以下 5 个目标 CSV：
  - `trading_calendar.csv`
  - `securities.csv`
  - `universe_members.csv`
  - `daily_prices.csv`
  - `valuation_daily.csv`
- 多余 CSV 文件必须忽略，例如 `announcements.csv`、`risk_events.csv`。
- 目标 CSV 中超出 contract 的列允许出现，但 normalization 后忽略。
- CSV 字段优先采用 DuckDB schema 的规范字段名。
- CSV fallback 不调用 `fixtures.builder.build_fixtures`。
- CSV fallback 不调用 `ingest_local`。
- CSV fallback 不清空全库。
- 如果缺少必要 CSV 文件，必须 fail-fast。
- fallback 生效时，CLI 和质量报告必须打印 warning。

### CSV effective_date 兼容

由于 CSV fallback 不调用 `ingest_local`，必须自行填补 PIT 可见性字段。

规则：

- `universe_members.in_effective_date`：
  - CSV 已提供则使用 CSV 值。
  - 否则如果 `in_publish_time` 非空，使用 `pit.effective_date.calculate_effective_date` 计算。
  - 否则 fallback 到 `in_date`。
- `universe_members.out_effective_date`：
  - CSV 已提供则使用 CSV 值。
  - 否则如果 `out_publish_time` 非空，使用 `calculate_effective_date` 计算。
  - 否则 fallback 到 `out_date`。
- `securities.delist_effective_date`：
  - CSV 已提供则使用 CSV 值。
  - 否则如果 `delist_publish_time` 非空，使用 `calculate_effective_date` 计算。
  - 否则 fallback 到 `delist_date`。
- 计算 effective date 时使用 CSV / provider 提供的 `trading_calendar.is_open = true` 日期。
- 如果找不到后续交易日，必须 fail-fast，不得静默写空值。

## 缓存

在 `src/ashare/ingest/cache.py` 中实现：

```python
@dataclass(frozen=True)
class CacheKey:
    source: str
    dataset: str
    params_hash: str

def build_params_hash(
    source: str,
    dataset: str,
    params: Mapping[str, object],
) -> str:
    ...

def read_cached_frame(cache_dir: str | Path, key: CacheKey) -> pd.DataFrame | None:
    ...

def write_cached_frame(
    cache_dir: str | Path,
    key: CacheKey,
    frame: pd.DataFrame,
    metadata: Mapping[str, object],
) -> Path:
    ...
```

`params_hash` 必须稳定可复现，算法固定为：

```python
payload = {
    "source": source,
    "dataset": dataset,
    "params": params,
}
params_hash = sha1(
    json.dumps(payload, sort_keys=True, default=str, separators=(",", ":")).encode("utf-8")
).hexdigest()
```

缓存目录：

```text
data/raw/cache/{source}/{dataset}/{params_hash}.parquet
data/raw/cache/{source}/{dataset}/{params_hash}.json
```

metadata 至少包含：

```text
source
dataset
request_params
params_hash
fetched_at
row_count
columns
provider_version_or_unknown
```

CLI 支持：

```text
--cache-mode use
--cache-mode refresh
--cache-mode offline
--cache-dir data/raw/cache
```

规则：

- `use`：有缓存用缓存，无缓存调用真实源。
- `refresh`：忽略旧缓存，重新调用真实源并覆盖缓存。
- `offline`：只读缓存或 CSV fallback，不允许网络调用。
- cache hit / miss 必须进入质量报告。
- 第二次同参数运行必须能命中缓存。

## 字段合约

在 `src/ashare/ingest/contracts.py` 中定义 dataset contract。

建议接口：

```python
@dataclass(frozen=True)
class FieldValidationIssue:
    dataset: str
    severity: str
    code: str
    message: str
    row_count: int | None = None

def normalize_dataset(dataset: str, frame: pd.DataFrame) -> pd.DataFrame:
    ...

def validate_dataset(dataset: str, frame: pd.DataFrame) -> tuple[pd.DataFrame, tuple[FieldValidationIssue, ...]]:
    ...
```

硬失败：

- 缺少 required columns。
- 日期字段无法解析。
- 股票代码无法规范化。
- 主键重复：
  - `trading_calendar`: `(trade_date)`
  - `securities`: `(stock_code)`
  - `universe_members`: `(index_code, stock_code, in_date)`
  - `daily_prices`: `(stock_code, trade_date)`
  - `valuation_daily`: `(source, stock_code, trade_date)`
- `daily_prices.high < low`
- `daily_prices.close` 不在 `[low, high]`
- `volume < 0`
- `amount < 0`

warning：

- `adj_factor` 大面积缺失。
- `limit_up` / `limit_down` 缺失。
- `is_suspended` 来源不可靠。
- `pe_ttm <= 0`。
- `pb <= 0`。
- `valuation_daily` 覆盖率明显低于行情覆盖率。
- 指数成分是当前快照而非历史 PIT 成分。
- fallback 生效。
- `securities.list_date` 为 synthetic。

## 数据质量报告

在 `src/ashare/ingest/quality.py` 中实现：

```python
@dataclass(frozen=True)
class DataQualityReport:
    source: str
    effective_source: str
    source_tag: str
    universe: str
    index_code: str
    start_date: date
    end_date: date
    universe_as_of_date: date
    dataset_summary: pd.DataFrame
    field_summary: pd.DataFrame
    issues: pd.DataFrame
    cache_summary: pd.DataFrame
    warnings: tuple[str, ...]
```

输出文件：

```text
data_quality_report.md
dataset_summary.csv
field_summary.csv
issues.csv
cache_summary.csv
```

报告至少包含：

- source / effective_source / source_tag。
- universe / index_code。
- 日期范围。
- `universe_as_of_date`。
- 每个 dataset 的行数、股票数、起止日期。
- 每个字段的缺失率。
- duplicate key 检查结果。
- 价格字段基本一致性检查。
- 估值字段异常统计。
- 行情覆盖率。
- 估值覆盖率。
- universe 成分数量。
- `--max-symbols` 实际抽样后的 stock_code 列表。
- cache hit / miss。
- 是否使用 CSV fallback。
- PIT 限制说明，尤其是指数成分是否为当前快照。

## 落库规则

新增 `src/ashare/ingest/real_pilot.py`。

建议接口：

```python
@dataclass(frozen=True)
class RealPilotIngestResult:
    source: str
    effective_source: str
    source_tag: str
    db_path: Path
    row_counts: dict[str, int]
    quality_report_paths: dict[str, Path]
    warnings: tuple[str, ...]

def ingest_real_pilot(
    db_path: str | Path,
    provider: MarketDataProvider,
    universe: str,
    index_code: str,
    start_date: DateLike,
    end_date: DateLike,
    universe_as_of_date: DateLike,
    cache_dir: str | Path,
    cache_mode: str = "use",
    fallback_provider: MarketDataProvider | None = None,
    allow_fallback: bool = False,
    max_symbols: int | None = None,
    quality_report_dir: str | Path | None = None,
    source_tag: str | None = None,
) -> RealPilotIngestResult:
    ...
```

规则：

- 调用 `storage.db.init_db`。
- 不调用 `ingest_local`。
- 不清空全库。
- `source_tag` 默认等于最终 `effective_source`，也可由 CLI `--source-tag` 覆盖。
- `source_tag` 写入 `universe_members.source`、`valuation_daily.source` 和缓存 metadata。
- `daily_prices` 没有 `source` 字段，按 `(stock_code, trade_date BETWEEN start_date AND end_date)` 做 bounded replace。
- `trading_calendar` 没有 `source` 字段，按 `trade_date BETWEEN start_date AND end_date` 做 bounded replace。
- `securities` 没有 `source` 字段，按本次涉及 `stock_code` 做 bounded replace。
- `valuation_daily` 按 `(source_tag, stock_code, trade_date BETWEEN start_date AND end_date)` 做 bounded replace。
- `universe_members` 按 `(source_tag, index_code, stock_code)` 做 bounded replace。
- 如果目标 DB 中已存在不同 `source` 的 `valuation_daily` 或 `universe_members` 与本次写入范围重叠，CLI 必须 fail-fast，提示不要在同一 DB 中混用 fixture / 真实数据。
- 重复运行同一参数不得产生重复行。
- 写入前必须通过字段校验。
- 写入后必须做 read-back row count 校验。
- 不写 `factor_values`。
- 不写 `research_runs`。

## CLI 要求

修改现有命令：

```text
ashare ingest
```

Phase 0 placeholder 参数无需保持向后兼容；本 phase 可以扩展真实参数集，但 `ashare --help` 必须仍显示 `ingest` 命令。

建议参数：

```text
--source              akshare / csv / auto，默认 akshare
--source-tag          可选；默认等于 effective_source
--universe            默认 hs300
--index-code          可选；不传时 hs300 映射为 000300.SH
--from                必填，ISO 日期
--to                  必填，ISO 日期
--universe-as-of      可选；默认等于 --from
--db-path             默认 data/processed/ashare.duckdb
--cache-dir           默认 data/raw/cache
--cache-mode          use / refresh / offline，默认 use
--fallback-csv-dir    可选
--allow-fallback / --no-allow-fallback，默认 false
--max-symbols         可选；试点建议 10 或 20
--quality-report-dir  默认 data/reports/generated/phase1a7/data-quality
--overwrite-report    默认 false
```

行为：

- `--source akshare`：只使用 AkShare；失败则失败，除非显式 `--allow-fallback` 且提供 CSV fallback。
- `--source csv`：只使用 CSV provider；必须提供 `--fallback-csv-dir`。
- `--source auto`：先尝试 AkShare；失败后只有显式 `--allow-fallback` 才允许 CSV fallback。
- `--cache-mode offline` 时不得调用 AkShare 网络。
- `--max-symbols` 按 `stock_code` 升序取前 N 只，保证测试和缓存稳定。
- `--max-symbols` 生效时，CLI 和质量报告必须列出实际 sample 的 stock_code。
- 成功后打印：
  - db path
  - source
  - effective_source
  - source_tag
  - universe / index_code
  - date range
  - universe_as_of_date
  - row counts by dataset
  - cache hit / miss
  - quality report paths
  - warnings
- 不调用 `calculate-factors`。
- 不调用 `validate-factors`。
- 不调用 `scan`。
- 不调用 `report`。

## 配置要求

可在 `configs/data.yaml` 增加最小配置：

```yaml
real_data_pilot:
  default_source: akshare
  default_universe: hs300
  default_index_code: 000300.SH
  cache_dir: data/raw/cache
  quality_report_dir: data/reports/generated/phase1a7/data-quality
  max_symbols: 20
  datasets:
    - trading_calendar
    - securities
    - universe_members
    - daily_prices
    - valuation_daily
```

可在 `configs/universe.yaml` 增加映射：

```yaml
universe_aliases:
  hs300:
    index_code: 000300.SH
    name: 沪深300
```

不得在本 phase 增加全 A、中证 500 或多市场配置。

## followups 更新

修改 `docs/planning/followups.md`，追加本 phase 新留下的工程债。

至少新增：

```text
D23 daily_prices / securities / trading_calendar 缺少 source 字段，多源数据不可完全隔离
D24 历史沪深 300 PIT 成分库尚未落地
D25 --max-symbols 只是试点限流，后续需要明确撤除或替代路径
```

每条仍按现有 followups 格式记录：

```markdown
### Dxx. <债标题>

- 现状: ...
- 触发: ...
- 决策: ...
- 关联: ...
```

不得借本 phase 实现 D23-D25。

## 测试要求

新增或更新测试，至少覆盖：

1. fake `MarketDataProvider` 可以驱动 `ingest_real_pilot`。
2. AkShare provider 的 normalization 不依赖测试网络；真实调用在 pytest 中 mock。
3. CSV provider 只读取 5 个目标 CSV。
4. CSV provider 忽略多余 CSV 文件。
5. CSV provider 忽略目标 CSV 中 contract 外的多余列。
6. `--source csv` 未传 `--fallback-csv-dir` 时 fail-fast。
7. `--source akshare` provider 抛错且未允许 fallback 时 fail-fast。
8. `--source auto --allow-fallback` 时 AkShare 失败后使用 CSV fallback。
9. fallback 生效时 `effective_source = csv_fallback`。
10. `--source csv` 成功时 `effective_source = csv`。
11. `--source auto` 未传 `--allow-fallback` 时打印等价 AkShare 的 warning。
12. `--source-tag` 会写入 `valuation_daily.source` 与 `universe_members.source`。
13. cache `use` 模式下第二次同参数读取缓存。
14. cache `refresh` 模式下重新调用 provider。
15. cache `offline` 模式下无缓存且无 fallback 时 fail-fast。
16. `params_hash` 对 key 顺序稳定，且同参数 hash 一致。
17. cache metadata 包含 source、dataset、params_hash、row_count。
18. 字段校验发现缺少 required columns 时 fail-fast。
19. 字段校验发现 duplicate key 时 fail-fast。
20. `daily_prices.high < low` 时 fail-fast。
21. `daily_prices.close` 不在 `[low, high]` 时 fail-fast。
22. `volume < 0` 或 `amount < 0` 时 fail-fast。
23. `pe_ttm <= 0` 不删除数据，但进入 warning / issues。
24. `adj_factor` 缺失不失败，但进入 field_summary 缺失率。
25. 当前成分快照不得倒推为历史成分。
26. `universe_members.in_effective_date` 默认使用 `universe_as_of_date`。
27. CSV fallback 缺少 `in_effective_date` 时能按规则填补。
28. `--universe-as-of` 默认等于 `--from`。
29. `--universe-as-of > --from` 时 CLI 打印 PIT universe 可能为空的 warning。
30. `--max-symbols` 按 `stock_code` 升序取前 N 只。
31. 数据质量报告列出实际 sample stock_code。
32. bounded replace 重复运行不产生重复行。
33. bounded replace 不删除其他 `source_tag` 的 `valuation_daily` / `universe_members` 行。
34. 混用不同 source 的重叠 `valuation_daily` / `universe_members` 时 fail-fast。
35. 落库后 `as-of` 查询可以读到本次写入的行情、估值和 universe。
36. 数据质量报告写出 Markdown 和 4 个 CSV。
37. 数据质量报告包含 source、effective_source、source_tag、row count、missing rate、cache summary、warnings。
38. CLI `ashare ingest --source csv ...` 可以成功运行。
39. CLI 不写入 `factor_values`。
40. CLI 不生成候选清单或因子验证报告。
41. `docs/planning/followups.md` 包含 D23、D24、D25。
42. `ashare --help` 仍能看到前置命令：

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
```

pytest 测试不得依赖真实 AkShare 网络或当前交易日数据。

## 验收命令

以下硬验收命令必须全部成功：

```bash
conda run -n ashare-research-lab python -m pip install -e .
```

```bash
conda run -n ashare-research-lab python scripts/build_fixtures.py \
  --output-dir tests/fixtures/generated
```

```bash
conda run -n ashare-research-lab ashare ingest \
  --source csv \
  --source-tag phase1a7-csv \
  --universe hs300 \
  --index-code LOCAL_FIXTURE \
  --from 2026-03-30 \
  --to 2026-05-14 \
  --universe-as-of 2026-03-30 \
  --db-path data/processed/ashare_phase1a7.duckdb \
  --fallback-csv-dir tests/fixtures/generated \
  --cache-dir data/raw/cache/phase1a7 \
  --quality-report-dir data/reports/generated/phase1a7/data-quality \
  --overwrite-report
```

```bash
conda run -n ashare-research-lab ashare as-of \
  --as-of 2026-05-14 \
  --db-path data/processed/ashare_phase1a7.duckdb \
  --index-code LOCAL_FIXTURE
```

```bash
conda run -n ashare-research-lab python - <<'PY'
from pathlib import Path
import duckdb
import pandas as pd

db_path = "data/processed/ashare_phase1a7.duckdb"
con = duckdb.connect(db_path, read_only=True)

tables = {
    "trading_calendar": "SELECT COUNT(*) FROM trading_calendar",
    "securities": "SELECT COUNT(*) FROM securities",
    "universe_members": "SELECT COUNT(*) FROM universe_members",
    "daily_prices": "SELECT COUNT(*) FROM daily_prices",
    "valuation_daily": "SELECT COUNT(*) FROM valuation_daily",
}
for name, sql in tables.items():
    count = con.execute(sql).fetchone()[0]
    assert count > 0, f"{name} should not be empty"

factor_rows = con.execute("SELECT COUNT(*) FROM factor_values").fetchone()[0]
assert factor_rows == 0, "phase 1a-7 ingest must not write factor_values"

sources = {
    row[0]
    for row in con.execute("SELECT DISTINCT source FROM valuation_daily").fetchall()
}
assert "phase1a7-csv" in sources

con.close()

report_dir = Path("data/reports/generated/phase1a7/data-quality")
expected = {
    "data_quality_report.md",
    "dataset_summary.csv",
    "field_summary.csv",
    "issues.csv",
    "cache_summary.csv",
}
missing = [name for name in expected if not (report_dir / name).exists()]
assert not missing, f"missing quality report files: {missing}"

summary = pd.read_csv(report_dir / "dataset_summary.csv")
assert not summary.empty
assert {"dataset", "row_count"}.issubset(summary.columns)

text = (report_dir / "data_quality_report.md").read_text(encoding="utf-8")
assert "effective_source" in text
assert "source_tag" in text
assert "phase1a7-csv" in text
print("OK phase1a7 csv ingest and quality report")
PY
```

```bash
conda run -n ashare-research-lab python - <<'PY'
from pathlib import Path

text = Path("docs/planning/followups.md").read_text(encoding="utf-8")
required = ["D23", "D24", "D25", "source", "沪深 300", "max-symbols"]
missing = [item for item in required if item not in text]
assert not missing, f"followups.md missing: {missing}"
print("OK followups D23-D25")
PY
```

```bash
conda run -n ashare-research-lab pytest -q
```

```bash
conda run -n ashare-research-lab ashare --help
```

### AkShare smoke 命令

如果网络和 AkShare 上游可用，额外运行真实源 smoke：

```bash
conda run -n ashare-research-lab ashare ingest \
  --source akshare \
  --source-tag phase1a7-akshare \
  --universe hs300 \
  --from 2026-05-06 \
  --to 2026-05-14 \
  --universe-as-of 2026-05-06 \
  --db-path data/processed/ashare_phase1a7_akshare.duckdb \
  --cache-dir data/raw/cache/phase1a7-akshare \
  --cache-mode refresh \
  --max-symbols 10 \
  --quality-report-dir data/reports/generated/phase1a7-akshare/data-quality \
  --overwrite-report
```

AkShare smoke 失败不阻断 Phase 1a-7 完成，前提是：

- CSV fallback 硬验收路径全部通过。
- 最终回复明确说明 smoke 失败阶段、错误信息和是否由网络 / 上游字段变化导致。
- 不使用 CSV fallback 冒充 AkShare smoke 成功。

## 完成后

1. 运行 `git status`，确认只包含 Phase 1a-7 相关代码、测试、配置和必要文档改动。
2. 确认未提交：
   - `data/raw/cache/`
   - `data/processed/*.duckdb`
   - `data/reports/generated/`
   - 真实行情 CSV / Parquet 数据
3. 执行 `git add .`。
4. 执行：

```bash
git commit -m "feat: phase 1a-7 real data ingest pilot"
```

5. 最终回复说明：
   - 修改了哪些文件。
   - 支持了哪些数据集和字段。
   - AkShare provider 与 CSV fallback 如何切换。
   - `source_tag` 如何写入 source 字段。
   - 因 `daily_prices` 无 source 字段，如何避免混用 fixture / 真实数据。
   - 缓存目录、cache policy 和 `params_hash` 如何工作。
   - 数据质量报告输出了哪些文件。
   - 是否运行了 AkShare smoke，结果如何。
   - 硬验收命令是否全部通过。
   - commit hash。
   - 是否发现 plan 或前置 phase 的缺口。

## 不要实现

- 不为 `daily_prices` 增加 `source` 字段。
- 不为 `trading_calendar` 或 `securities` 增加 `source` 字段。
- 不扩展到全 A。
- 不接中证 500。
- 不接全部指数。
- 不做完整历史沪深 300 成分 PIT 数据平台。
- 不把当前沪深 300 成分倒推为历史成分。
- 不接财务报表真实源。
- 不接公告真实源。
- 不接风险事件真实源。
- 不接真实行业分类。
- 不实现 LLM。
- 不调用 OpenAI 或任何 LLM API。
- 不实现综合评分。
- 不实现因子标准化到 0-100。
- 不实现组合回测。
- 不实现交易撮合、手续费、滑点、调仓或持仓逻辑。
- 不实现生产级调度、任务队列、重试系统或监控系统。
- 不实现复杂 schema migration framework。
- 不写入 `factor_values`。
- 不写入 `research_runs`。
- 不调用 `calculate-factors`、`validate-factors`、`scan`、`report` 或 `backtest`。
- 不提交真实数据缓存或生成报告。
- 不让 CSV fallback 静默掩盖真实源失败。

## 发现的缺口

- `daily_prices` 没有 `source` 字段，多源真实数据无法完全隔离。本 phase 选择不改 schema，退化为 `(stock_code, trade_date)` bounded replace，并禁止 fixture / 真实数据混用同一 DB。
- `trading_calendar` 和 `securities` 也没有 `source` 字段，只能做 bounded replace；正式多源数据平台需要后续 schema 设计。
- Plan 只说明第一版可以用 AkShare 起步，但没有定义 provider 抽象、缓存策略、字段合约或数据质量报告格式。本 phase 在小范围内补齐。
- Plan 要求沪深 300 历史成分起步，但免费数据源未必能提供严格 Point-in-Time 的历史成分披露时间。本 phase 不伪造历史 PIT 成分；若只有当前成分快照，必须在 `universe_members` 和质量报告中明确标记。
- `ingest_local` 仍是清表重写路径，不能用于真实数据。本 phase 新增独立真实数据试点 ingest，不复用 `ingest_local` 的清表语义。
- 真实源字段名和可用性可能变化，本 phase 必须通过 provider 隔离、字段校验和质量报告暴露问题，而不是让下游因子层静默使用异常数据。
