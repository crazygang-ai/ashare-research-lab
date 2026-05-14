# Phase 1a-3.5 Goal: PIT 区间数据披露时间建模

请在已完成 Phase 1a-3 的 `/Users/crazy/own_project/ashare-research-lab` 仓库中继续实现 Phase 1a-3.5：PIT 区间数据披露时间建模。

## 目标

1. 修复区间型数据无法表达“什么时候被市场知道”的 PIT 缺口。
2. 为以下表补充区间进入 / 退出的披露时间和生效日期字段：
   - `universe_members`
   - `st_status`
   - `industry_classifications`
3. 为 `securities.delist_date` 补充退市披露时间和退市生效日期字段。
4. 更新 fixture、ingest、本地 DuckDB schema 初始化和 as-of 查询层。
5. 确保 `ashare as-of` 的行数统计和股票列表遵守新的可见性规则。
6. 不做因子计算、不写 `factor_values`、不做报告、不做回测。

## 背景问题

Phase 1a-3 已经实现了 as-of 查询，并对未来 `out_date` / `delist_date` 做了 mask。

但当前 schema 仍只能表达业务状态区间：

```text
in_date / out_date
delist_date
```

无法表达这些信息的披露时间：

```text
某股票 2026-03-06 退市，系统在 2026-01-10 是否已经知道？
某股票 2026-02-18 摘帽，系统在 2026-02-01 是否已经知道？
某股票未来会被剔除指数，公告前是否应该暴露 out_date？
```

本 phase 要补上“可见性时间”，使 as-of 查询能区分：

```text
事件实际发生日期
事件披露时间
事件对研究系统可见的生效日期
```

## 工作约束

- 严格遵守 `docs/planning/a-share-research-plan.md`。
- 所有 Python 命令必须在 Conda 环境 `ashare-research-lab` 中执行。
- 本 phase 只修 PIT 区间数据建模和查询语义。
- 不实现因子计算。
- 不写入 `factor_values`。
- 不写入 `research_runs`。
- 不生成 Markdown / CSV 报告。
- 不做 IC、Rank IC、分组收益、衰减曲线。
- 不做组合回测。
- 不实现 `scan` 真实逻辑。
- 不调用 AkShare。
- 不调用 LLM。
- 不接真实数据源。
- Phase 1a-3.5 完成后单独 commit。
- 提交信息为：`feat: phase 1a-3.5 pit interval visibility`

## 命名说明

已有表 `fundamental_reports`、`announcements`、`risk_events` 使用：

```text
publish_time
effective_date
```

区间表需要同时表达进入和退出两侧的信息，因此本 phase 使用带前缀字段：

```text
in_publish_time
in_effective_date
out_publish_time
out_effective_date
```

含义：

- `in_*`：进入该状态 / 成分 / 行业分类的披露与可见性。
- `out_*`：退出该状态 / 成分 / 行业分类的披露与可见性。
- `publish_time`：事件披露时间，类型为 `TIMESTAMP NULL`。
- `effective_date`：该信息对研究系统可见的日期，类型为 `DATE NULL`。

## NULL 兼容语义

本 phase 必须兼容旧 DuckDB 文件和旧 CSV fixture。

新增字段允许为 `NULL`，但查询层必须有明确兜底规则：

```text
in_effective_date IS NULL  -> 视为 in_date 已可见
out_effective_date IS NULL -> 视为 out_date 已可见
delist_effective_date IS NULL -> 视为 delist_date 已可见
```

也就是说，MVP 兼容策略是：

```text
COALESCE(in_effective_date, in_date)
COALESCE(out_effective_date, out_date)
COALESCE(delist_effective_date, delist_date)
```

理由：

- 兼容旧库和旧 fixture，不让已有数据全部不可见。
- 保持 Phase 1a-3 已有行为基本稳定。
- 后续真实数据源接入时，应由 ingest 阶段填充明确的披露时间和生效日期。

`ingest_local` 也要做兼容：

- 如果 CSV 缺少新增字段，允许导入。
- 如果新增字段为空：
  - 有对应 `publish_time` 时，优先用 `calculate_effective_date(publish_time, trading_days)` 回填。
  - 没有对应 `publish_time` 时，fallback 到业务日期：
    - `in_effective_date` fallback 到 `in_date`
    - `out_effective_date` fallback 到 `out_date`
    - `delist_effective_date` fallback 到 `delist_date`
- `*_publish_time` 没有来源时允许保持 `NULL`。

## Schema 变更

### `universe_members`

从：

```text
index_code
stock_code
in_date
out_date
source
```

扩展为：

```text
index_code VARCHAR
stock_code VARCHAR
in_date DATE
out_date DATE
in_publish_time TIMESTAMP
in_effective_date DATE
out_publish_time TIMESTAMP
out_effective_date DATE
source VARCHAR
```

### `st_status`

从：

```text
stock_code
st_type
in_date
out_date
source
```

扩展为：

```text
stock_code VARCHAR
st_type VARCHAR
in_date DATE
out_date DATE
in_publish_time TIMESTAMP
in_effective_date DATE
out_publish_time TIMESTAMP
out_effective_date DATE
source VARCHAR
```

### `industry_classifications`

从：

```text
stock_code
industry_standard
industry_l1
industry_l2
in_date
out_date
version
source
```

扩展为：

```text
stock_code VARCHAR
industry_standard VARCHAR
industry_l1 VARCHAR
industry_l2 VARCHAR
in_date DATE
out_date DATE
in_publish_time TIMESTAMP
in_effective_date DATE
out_publish_time TIMESTAMP
out_effective_date DATE
version VARCHAR
source VARCHAR
```

### `securities`

从：

```text
stock_code
stock_name
exchange
list_date
delist_date
```

扩展为：

```text
stock_code VARCHAR
stock_name VARCHAR
exchange VARCHAR
list_date DATE
delist_date DATE
delist_publish_time TIMESTAMP
delist_effective_date DATE
```

### `schema_version`

新增最小 schema 版本表：

```text
schema_version
  version INTEGER
  applied_at TIMESTAMP
  description VARCHAR
```

要求：

- 初始化新库时写入当前 schema version。
- 旧库运行 `init_db` 后应自动补表 / 补列。
- 本 phase 不需要实现完整迁移框架，只建立最小版本记录，避免后续再二次重构。

## Schema 迁移要求

修改 `src/ashare/storage/db.py`。

要求：

1. `init_db` 执行 `schema.sql` 后，调用独立函数：

```python
def ensure_schema_columns(connection: duckdb.DuckDBPyConnection) -> None:
    ...
```

2. 使用 DuckDB `information_schema.columns` 检测缺失列。
3. 不使用 `try/except ALTER TABLE` 作为正常控制流。
4. 缺失列用 `ALTER TABLE ADD COLUMN` 补齐。
5. 新增列类型必须明确：
   - `TIMESTAMP`
   - `DATE`
6. 旧库补列不得丢失原有数据。
7. `ensure_schema_columns` 要便于单测直接调用。
8. `schema_version` 表不存在时创建。
9. schema version 记录要幂等，重复运行 `init_db` 不应重复膨胀无意义记录。

## as-of 查询规则

### 通用可见性规则

对区间进入侧：

```text
in_date <= as_of_date
AND COALESCE(in_effective_date, in_date) <= as_of_date
```

对区间退出侧：

- 如果退出信息不可见，不允许暴露 `out_date`。
- 如果退出信息已可见，但实际 `out_date` 还没到，当前状态仍然有效。
- 如果退出信息已可见，且 `out_date <= as_of_date`，当前状态失效。

返回结果中的 `out_date` mask 规则：

```text
只有 COALESCE(out_effective_date, out_date) <= as_of_date 时，才返回 out_date；
否则返回 NULL。
```

### `universe_members`

有效成员规则：

```text
in_date <= as_of_date
AND COALESCE(in_effective_date, in_date) <= as_of_date
AND (
  out_date IS NULL
  OR as_of_date < out_date
  OR COALESCE(out_effective_date, out_date) > as_of_date
)
```

解释：

- 进入日期到了且进入信息已可见，才能成为成员。
- 如果 `out_date` 未到，仍是成员。
- 如果 `out_date` 已到，但退出信息在 as-of 时仍不可见，MVP 兼容语义下仍按未退出处理。
- 如果 `out_date` 已到且退出信息已可见，则不再是当前成员。

返回列中：

```text
out_date
out_publish_time
out_effective_date
```

都必须遵守可见性 mask。

### `st_status`

有效 ST 状态规则：

```text
in_date <= as_of_date
AND COALESCE(in_effective_date, in_date) <= as_of_date
AND (
  out_date IS NULL
  OR as_of_date < out_date
  OR COALESCE(out_effective_date, out_date) > as_of_date
)
```

返回列中未来不可见的 `out_date` / `out_publish_time` / `out_effective_date` 必须 mask。

### `industry_classifications`

行业分类使用与其他区间表一致的四元组：

```text
in_publish_time
in_effective_date
out_publish_time
out_effective_date
```

有效行业规则：

```text
in_date <= as_of_date
AND COALESCE(in_effective_date, in_date) <= as_of_date
AND (
  out_date IS NULL
  OR as_of_date < out_date
  OR COALESCE(out_effective_date, out_date) > as_of_date
)
```

继续支持：

```text
industry_standard
version
stock_code
```

可选过滤。

返回结果中未来不可见的 `out_date` / `out_publish_time` / `out_effective_date` 必须 mask。

### `securities.delist_date`

`is_delisted_as_of` 规则从：

```text
delist_date IS NOT NULL AND delist_date <= as_of_date
```

改为：

```text
delist_date IS NOT NULL
AND delist_date <= as_of_date
AND COALESCE(delist_effective_date, delist_date) <= as_of_date
```

返回结果中：

```text
delist_date
delist_publish_time
delist_effective_date
```

只有在退市信息已可见时才暴露；否则返回 `NULL`。

默认 `include_delisted=False` 时，过滤掉 `is_delisted_as_of = true` 的股票。

`include_delisted=True` 时，可以返回已退市股票，并正确标记 `is_delisted_as_of = true`。

## CLI 要求

`ashare as-of` 不新增必需参数，但输出必须遵守新的可见性规则。

要求：

- 行数统计按新的 PIT 可见性计算。
- `universe_stock_codes` 使用新的 `query_universe_members_as_of` 结果。
- `securities_stock_codes` 使用新的 `query_securities_as_of` 结果。
- `delisted_stock_codes` 使用新的 `is_delisted_as_of`。
- 不暴露 `out_effective_date > as_of_date` 的 `out_date`。
- 不暴露 `delist_effective_date > as_of_date` 的 `delist_date`。
- 不写文件。
- 不计算因子。

## Fixture 更新

修改 `src/ashare/fixtures/builder.py`。

### `000003.SZ` 退市样例

保持：

```text
delist_date = main_days[44]
```

新增：

```text
delist_publish_time = main_days[40] 18:00:00
delist_effective_date = main_days[41]
```

对应 `universe_members` 的退出字段：

```text
out_date = main_days[44]
out_publish_time = main_days[40] 18:00:00
out_effective_date = main_days[41]
```

必须能测试三态：

```text
公告前：不暴露未来 delist_date / out_date
公告后但退市日前：知道未来退市 / 退出日期，但当前仍在证券表或 universe 中
退市日当天：状态切换，默认查询不再返回该股票
```

### `000002.SZ` ST 样例

保持：

```text
in_date = main_days[12]
out_date = main_days[32]
```

新增：

```text
in_publish_time = main_days[11] 18:00:00
in_effective_date = main_days[12]
out_publish_time = main_days[30] 18:00:00
out_effective_date = main_days[31]
```

必须能测试：

```text
ST 公告前不可见
ST 生效日当天可见
摘帽公告后但 out_date 前仍为 ST
out_date 当天不再为 ST
```

### 行业切换样例

将 `000005.SZ` 从静态单行改为至少两行：

第一段：

```text
stock_code = 000005.SZ
industry_l1 = Technology
industry_l2 = Software
in_date = main_days[0]
out_date = main_days[30]
in_publish_time = main_days[0] 18:00:00
in_effective_date = main_days[1]
out_publish_time = main_days[28] 18:00:00
out_effective_date = main_days[29]
version = 2026Q1
```

第二段：

```text
stock_code = 000005.SZ
industry_l1 = Technology
industry_l2 = Internet
in_date = main_days[30]
out_date = NULL
in_publish_time = main_days[28] 18:00:00
in_effective_date = main_days[29]
out_publish_time = NULL
out_effective_date = NULL
version = 2026Q1
```

其他股票可以保持单行业记录，但也必须填充：

```text
in_publish_time
in_effective_date
out_publish_time
out_effective_date
```

对于没有退出的记录：

```text
out_date = NULL
out_publish_time = NULL
out_effective_date = NULL
```

## ingest-local 更新

修改 `src/ashare/ingest/local.py`。

要求：

1. 更新 `TABLE_COLUMNS` 支持新增列。
2. CSV 新增列存在时正常读取。
3. CSV 缺少新增列时也能兼容导入。
4. 空字符串转为 `None`。
5. `*_publish_time` 解析为 `datetime`。
6. `*_effective_date` 解析为 `date`。
7. 缺少或为空的 `*_effective_date` 按本 phase 的 NULL 兼容语义回填。
8. 导入仍然是 fixture-only 的清表重写逻辑。
9. 不实现真实数据源 ingest。
10. 不实现增量 upsert。

## Plan 文档同步

必须同步更新：

```text
docs/planning/a-share-research-plan.md
```

至少更新第 6 节核心数据表中的相关字段定义：

```text
securities
universe_members
industry_classifications
st_status
```

要求：

- plan 中字段定义不能继续停留在旧 schema。
- 只更新本 phase 相关 schema 描述。
- 不重写整个 plan。
- 不提前写 Phase 1a-4 因子计算内容。

## 测试要求

新增或更新测试：

```text
tests/test_asof.py
tests/test_ingest_local.py
tests/test_db.py
tests/test_fixtures.py
```

至少覆盖：

1. 新 fixture CSV 包含新增披露 / 生效字段。
2. `ingest_local` 可以导入包含新增字段的 fixture。
3. `ingest_local` 可以导入缺少新增字段的旧格式 CSV，并按 NULL 兼容语义运行。
4. 旧 DuckDB 文件缺少新增列时，运行 `init_db` 后自动补列。
5. schema 补列后原有数据不丢。
6. `ensure_schema_columns` 使用 `information_schema.columns` 检测缺失列。
7. `schema_version` 表存在，且重复运行 `init_db` 不产生无意义重复。
8. `universe_members` 公告前不暴露未来 `out_date`。
9. `universe_members` 公告后但 `out_date` 前仍是当前成员，并可暴露已可见的未来 `out_date`。
10. `universe_members` `out_date` 当天不再是当前成员。
11. `st_status` `in_effective_date` 前不可见。
12. `st_status` `in_effective_date` 当天可见。
13. `st_status` `out_publish_time` 已过、`out_date` 未到时仍为 ST。
14. `st_status` `out_date` 当天不再为 ST。
15. `industry_classifications` 使用 fixture 内置行业切换样例，不再依赖临时插入。
16. `industry_classifications` 在旧行业 `out_date` 前返回 Software。
17. `industry_classifications` 在新行业 `in_date` 后返回 Internet。
18. 行业切换公告前不暴露未来 `out_date`。
19. `securities` 退市公告前不暴露未来 `delist_date`。
20. `securities` 退市公告后但退市日前可以暴露已可见的未来 `delist_date`，但 `is_delisted_as_of = false`。
21. `securities` 退市日当天 `is_delisted_as_of = true`。
22. 默认 `include_delisted=False` 时退市日当天不返回已退市股票。
23. `include_delisted=True` 时退市日当天返回已退市股票。
24. `out_effective_date == as_of_date` 的边界按“生效日当天已可见”处理。
25. `delist_effective_date == as_of_date` 的边界按“生效日当天已可见”处理。
26. `load_as_of_snapshot` 在旧格式数据兼容场景下仍能跑通。
27. `ashare as-of` 输出遵守新的 mask 规则和行数统计。
28. `ashare --help` 仍能看到前置命令：

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
```

测试数据要求：

- 常规测试通过 Phase 1a-2 fixture builder 和 `ingest_local` 在 `tmp_path` 下构造。
- 旧 schema 迁移测试可手工创建一个缺少新增列的临时 DuckDB。
- 不依赖仓库内已有 DuckDB 文件。
- 不接真实数据源。

## 验收命令

以下命令必须全部成功：

```bash
conda run -n ashare-research-lab python -m pip install -e .
```

```bash
conda run -n ashare-research-lab ashare ingest-local \
  --input-dir tests/fixtures/generated \
  --db-path data/processed/ashare.duckdb
```

```bash
conda run -n ashare-research-lab ashare as-of \
  --as-of 2026-03-02 \
  --db-path data/processed/ashare.duckdb \
  --index-code LOCAL_FIXTURE
```

```bash
conda run -n ashare-research-lab ashare as-of \
  --as-of 2026-03-06 \
  --db-path data/processed/ashare.duckdb \
  --index-code LOCAL_FIXTURE \
  --include-delisted
```

```bash
conda run -n ashare-research-lab pytest -q
```

```bash
conda run -n ashare-research-lab ashare --help
```

## 完成后

1. 运行 `git status`，确认只包含 Phase 1a-3.5 相关改动。
2. 执行 `git add .`。
3. 执行：

```bash
git commit -m "feat: phase 1a-3.5 pit interval visibility"
```

4. 最终回复说明：
   - 修改了哪些文件。
   - 新增了哪些 schema 字段。
   - 旧 DuckDB schema 如何自动补列。
   - NULL 兼容语义如何实现。
   - as-of 查询如何防止未来区间 / 退市信息泄漏。
   - fixture 覆盖了哪些公告前、公告后、生效前、生效后场景。
   - 验收命令是否全部通过。
   - commit hash。
   - 是否发现 plan 或前置 phase 的新缺口。

## 不要实现

- 不实现因子计算。
- 不写入 `factor_values`。
- 不实现 `calculate-factors`。
- 不实现 `scan` 真实逻辑。
- 不实现 `validate-factors` 真实逻辑。
- 不实现 IC、Rank IC、分组收益或衰减曲线。
- 不实现事件研究。
- 不实现组合回测。
- 不生成研究报告。
- 不写入 `research_runs`。
- 不引入独立 `security_status_events` 事件流表。
- 不改动 `in_date` / `out_date` 的业务语义。
- 不实现 `latest-revision-wins`。
- 不实现 universe 成分版本号体系。
- 不实现完整 schema migration framework。
- 不接真实数据源。
- 不调用 AkShare。
- 不调用 LLM。
- 不实现服务化 API。
