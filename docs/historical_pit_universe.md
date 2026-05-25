# Historical PIT Universe Import

本仓库只提供 historical PIT universe 的本地导入入口和校验规则，不内置或伪造沪深 300 商业历史成分库。严格历史验证和正式回测需要用户自行提供已授权的 CSV 或 Parquet 成分区间文件。

## Universe Kind

`universe_members.universe_kind` 和 `factor_run_universe.universe_kind` 使用以下口径：

- `historical_pit`: 有进入、退出、披露时间和生效日期的历史 PIT 成分区间。formal validation 和 formal backtest 只接受这个口径。
- `current_snapshot`: 当前成分快照，适合每日 exploratory 研究；把它回填到历史日期会有幸存者偏差，不能用于 formal 历史结论。
- `unknown_legacy`: 旧库迁移或缺少明确来源口径的历史行。只能作为探索或兼容读取，不应生成 formal 结论。

## Input Fields

CSV / Parquet 必须包含以下列：

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
source_tag
```

字段规则：

- `index_code` 会规范化为类似 `000300.SH` 的格式。
- `stock_code` 会规范化为类似 `000001.SZ` / `600000.SH` 的格式。
- `source` 是数据供应方或本地数据集名称。
- `source_tag` 是本次导入的稳定标签，例如 `licensed-hs300-pit-v202605`。
- `in_effective_date` 是该成员进入 PIT universe 的 date 级可见日期。
- `out_effective_date` 为空表示成员区间仍开放；有退出时必须同时提供 `out_date`、`out_publish_time` 和 `out_effective_date`。
- historical PIT 行要求 `in_publish_time` 不晚于 `in_effective_date`，退出披露时间不晚于 `out_effective_date`。
- 同一 `source_tag/index_code/stock_code` 下成分区间不能重叠。

Date 级 PIT 仍不能表达盘前、盘中、盘后差异；这是当前能力边界。需要日内可见性时，应先扩展 timestamp 级 PIT 规则。

## Minimal Synthetic CSV

下面是结构样例，不是真实沪深 300 历史成分数据：

```csv
index_code,stock_code,in_date,out_date,in_publish_time,in_effective_date,out_publish_time,out_effective_date,source,source_tag
000300.SH,000001.SZ,2020-01-01,2021-01-01,2019-12-30 18:00:00,2020-01-01,2020-12-30 18:00:00,2021-01-01,local_authorized_sample,licensed-hs300-pit-v1
000300.SH,000002.SZ,2020-01-01,,2019-12-30 18:00:00,2020-01-01,,,local_authorized_sample,licensed-hs300-pit-v1
000300.SH,000001.SZ,2021-06-01,,2021-05-30 18:00:00,2021-06-01,,,local_authorized_sample,licensed-hs300-pit-v1
```

导入命令：

```bash
conda run -n ashare-research-lab ashare ingest-index-members \
  --input-path data/local_authorized/hs300_members_pit.csv \
  --db-path data/processed/hs300_pit.duckdb \
  --universe-kind historical_pit \
  --overwrite
```

Parquet 使用同一字段：

```bash
conda run -n ashare-research-lab ashare ingest-index-members \
  --input-path data/local_authorized/hs300_members_pit.parquet \
  --db-path data/processed/hs300_pit.duckdb \
  --universe-kind historical_pit \
  --overwrite
```

`--overwrite` 只替换同一 `source_tag/index_code` 的 universe rows。不要把授权数据文件、DuckDB、cache 或生成报告提交到 Git。

## Exploratory To Formal Upgrade

1. 用 AkShare 当前快照链路做 exploratory 数据连通性检查，保留 `current_snapshot` 风险说明。
2. 准备授权的 historical PIT 成分 CSV / Parquet，并导入同一个或新的 DuckDB。
3. 用同一个 `source_tag` / `data_source` 写入 `trading_calendar`、`securities`、`daily_prices`、`valuation_daily` 和 `universe_members`。
4. 重新运行 `calculate-factors`，让 `factor_run_universe` 记录每个 `source_run_id/trade_date` 的 historical PIT universe。
5. formal validation 使用 `--run-mode formal --index-code 000300.SH --data-source <source_tag>`。
6. formal backtest 使用 `--run-mode formal --data-source <source_tag>`；如果 universe snapshot 缺失、不是 `historical_pit`，或 `factor_run_universe.source_tag` 与 `--data-source` 不一致，命令会 fail-fast。

候选清单、综合评分、验证报告、回测报告、日报和单股报告都只是研究输出，不是交易指令。
