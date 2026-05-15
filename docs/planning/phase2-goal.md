# Phase 2 Goal: 公告与 LLM 解析

请在已完成 Phase 1b 的 `/Users/crazy/own_project/ashare-research-lab` 仓库中继续实现 Phase 2：公告与 LLM 解析。

本 phase 只做公告入库、正文保存、规则筛选、LLM 结构化解析、证据定位和系统置信度计算。LLM 输出只作为研究证据和风险提示来源，不进入总分、因子值、候选排序或回测。

## 目标

1. 实现公告元数据入库和公告正文保存。
2. 用系统规则筛选需要送入 LLM 的关键公告类型。
3. 用 `src/ashare/llm/schemas.py` 中的 Pydantic 模型作为 LLM 输出 Schema 单一来源。
4. Prompt 中的 JSON Schema 必须由 Pydantic 自动生成，禁止手写第二份 Schema。
5. LLM 只做结构化抽取、摘要、风险提取、催化剂提取和证据引用。
6. 系统校验 LLM JSON 输出并定位证据片段在公告正文中的位置。
7. 系统按确定性规则计算解析置信度，禁止使用 LLM 自评置信度。
8. 保存解析结果、原始 LLM 响应、证据片段、证据位置和置信度。
9. 解析阶段严格使用 PIT 语义：默认按 `effective_date` 过滤公告，而不是按 `publish_time` 过滤。
10. 不把 LLM 输出写入 `factor_values`，不接入 `scan`、`scoring`、`backtest` 或总分。
11. Phase 2 完成后单独 commit，提交信息为：`feat: phase 2 announcement llm parsing`

## 工作约束

- 严格遵守 `docs/planning/a-share-research-plan.md`。
- 所有 Python 命令必须在 Conda 环境 `ashare-research-lab` 中执行。
- 每个 phase 必须单独 commit。
- 本 phase 不新增基础运行时依赖，不修改 `environment.yml`。
- 本 phase 不实现真实公告源接入，不实现巨潮 / 交易所 provider，不实现 PDF 下载或解析。
- 本 phase 硬验收只使用 CSV 公告源、fixture 公告正文和 fixture LLM response。
- 真实 LLM client 只能作为可选能力；不得污染默认 Conda 环境。
- 不重复实现 Phase 1a 的 PIT 查询、因子计算、验证报告或真实行情接入。
- 不重复实现 Phase 1b 的组合回测。
- 本 phase 可以扩展公告和 LLM 解析所需的最小 DuckDB schema。
- 本 phase 不实现综合评分。
- 本 phase 不实现事件研究验证。
- 本 phase 不实现用 LLM 生成买卖建议、目标价或排名。
- pytest 不依赖真实网络、真实公告源或真实 LLM API。

## 文件变更

建议新增或修改：

```text
src/ashare/ingest/announcements.py
src/ashare/ingest/announcement_csv.py
src/ashare/announcements/__init__.py
src/ashare/announcements/rules.py
src/ashare/announcements/body_store.py
src/ashare/llm/schemas.py
src/ashare/llm/prompts.py
src/ashare/llm/client.py
src/ashare/llm/validators.py
src/ashare/llm/parser.py
src/ashare/storage/schema.sql
src/ashare/storage/db.py
src/ashare/cli.py
configs/llm.yaml
src/ashare/fixtures/builder.py
docs/planning/followups.md
tests/test_announcement_ingest.py
tests/test_announcement_rules.py
tests/test_announcement_body_store.py
tests/test_llm_schemas.py
tests/test_llm_prompts.py
tests/test_llm_validators.py
tests/test_llm_parser.py
tests/test_announcement_cli.py
```

可选修改：

```text
pyproject.toml
.gitignore
```

`pyproject.toml` 只允许在确实实现真实 LLM 可选路径时增加 optional extra，例如 `[project.optional-dependencies] llm = [...]`。不得把 `openai`、`requests`、`beautifulsoup4`、`pypdf` 等依赖加入 `environment.yml`。

不得新增：

```text
src/ashare/ingest/cninfo_announcement_provider.py
```

真实公告源接入留给后续 Phase 2.5。

## Schema 变更

在 `announcements` 增加最小来源字段：

```text
source VARCHAR
source_tag VARCHAR
```

含义：

- `source`：数据源类型，例如 `csv`。
- `source_tag`：本次 ingest 的来源标签，例如 `phase2-fixture`。
- 去重逻辑使用 `(source_tag, announcement_id)`。
- 跨 source / source_tag 的同一逻辑公告不自动合并，允许并存。

新增解析结果表：

```text
announcement_parse_runs
  parse_run_id VARCHAR
  started_at TIMESTAMP
  finished_at TIMESTAMP
  status VARCHAR
  llm_mode VARCHAR
  model_name VARCHAR
  schema_version VARCHAR
  prompt_template_hash VARCHAR
  config_hash VARCHAR
  announcement_count INTEGER
  success_count INTEGER
  failed_count INTEGER
  input_tokens INTEGER
  output_tokens INTEGER
  error VARCHAR

announcement_llm_results
  parse_id VARCHAR
  parse_run_id VARCHAR
  announcement_id VARCHAR
  source VARCHAR
  source_tag VARCHAR
  stock_code VARCHAR
  announcement_type VARCHAR
  schema_version VARCHAR
  sentiment VARCHAR
  summary VARCHAR
  parsed_json JSON
  raw_response_json JSON
  prompt_hash VARCHAR
  confidence DOUBLE
  confidence_reasons JSON
  status VARCHAR
  error VARCHAR
  created_at TIMESTAMP

announcement_llm_evidence
  evidence_id VARCHAR
  parse_id VARCHAR
  announcement_id VARCHAR
  item_type VARCHAR
  item_index INTEGER
  evidence_text VARCHAR
  page INTEGER
  char_start INTEGER
  char_end INTEGER
  locator_status VARCHAR
  created_at TIMESTAMP
```

要求：

- `init_db` 后必须自动创建新表。
- `ensure_schema_columns` 必须兼容旧 DuckDB 文件，旧库缺少 `announcements.source` 或 `announcements.source_tag` 时自动补列且不丢数据。
- 不实现完整 migration framework。
- `parse_id` 固定为：

```text
sha1(parse_run_id + "|" + source_tag + "|" + announcement_id)
```

- `evidence_id` 固定为：

```text
sha1(parse_id + "|" + item_type + "|" + item_index + "|" + evidence_text)
```

- 重复运行同一 `parse_run_id` 时：
  - 未传 `--overwrite` 必须 fail-fast。
  - 传 `--overwrite` 时先删除该 `parse_run_id` 的 parse result / evidence / run 记录再重写。
- 不新增外键或复杂约束。

## 公告入库与正文保存

新增 `ashare ingest-announcements` 命令。

建议参数：

```text
--source csv，默认 csv
--source-tag，默认等于 source
--input-csv，必填
--body-dir，可选；用于解析相对 body_path
--from，必填，按 publish_time 日期过滤
--to，必填，按 publish_time 日期过滤
--db-path，默认 data/processed/ashare.duckdb
--raw-output-dir，默认 data/raw/announcements
--overwrite / --no-overwrite，默认 false
--allow-missing-body / --no-allow-missing-body，默认 false
```

入库规则：

- 调用 `storage.db.init_db`。
- 从 `trading_calendar` 读取 `is_open = true` 的交易日。
- `effective_date` 必须由系统调用 `calculate_effective_date(publish_time, trading_days)` 计算。
- 不信任 provider 或 CSV 中已有的 `effective_date`。
- `announcement_id` 缺失时，用以下字段生成稳定 hash：

```text
source_tag
stock_code
publish_time ISO 字符串
normalized title
normalized url
normalized body text hash
```

- `announcement_type` 保存系统规则归一化后的 canonical type；无法识别时写 `other`。
- 正文保存到：

```text
raw-output-dir/{source_tag}/{stock_code}/{publish_date}/{announcement_id}.txt
```

- `raw_path` 写入正文文件路径。
- `text_hash` 使用 `normalize_announcement_text(body_text)` 后的 SHA256。
- 正文为空时默认 fail-fast；仅显式 `--allow-missing-body` 才允许入库，但后续解析必须跳过。
- 未传 `--overwrite` 时：
  - 同一 `(source_tag, announcement_id)` 已存在且 `text_hash` 一致，idempotent skip。
  - 同一 `(source_tag, announcement_id)` 已存在但 `text_hash` 不一致，fail-fast。
- 传 `--overwrite` 时，允许替换同一 `(source_tag, announcement_id)` 的公告元数据和正文。
- 不调用 LLM。

CSV source 至少支持字段：

```text
announcement_id
stock_code
title
announcement_type
publish_time
url
body_path
body_text
source
source_tag
```

`body_path` 和 `body_text` 二选一即可；两者都有时优先使用 `body_text`，并在测试中覆盖该优先级。

## 正文规范化

在 `src/ashare/announcements/body_store.py` 中定义唯一正文规范化函数：

```python
def normalize_announcement_text(text: str) -> str:
    ...
```

固定规则：

```text
1. 去掉开头 UTF-8 BOM。
2. Unicode NFKC 归一化。
3. 将 CRLF / CR 统一为 LF。
4. 将所有连续空白字符折叠为单个空格。
5. strip 首尾空白。
```

要求：

- `text_hash` 必须基于 `normalize_announcement_text`。
- 保存到 `raw_path` 的正文也必须是 `normalize_announcement_text` 后的文本。
- evidence 定位中的 exact match 和 normalized match 都必须使用同一规范化口径。
- `char_start` / `char_end` 指向保存后的 normalized 正文字符位置，而不是原始 CSV 或 PDF 字节位置。
- 同一输入重复运行必须得到完全相同的 `text_hash` 和 evidence 位置。

## 规则筛选

在 `src/ashare/announcements/rules.py` 中实现确定性规则。

第一版 whitelist 使用 `configs/llm.yaml`：

```text
earnings_forecast
earnings_report
buyback
shareholder_reduce
inquiry_letter
regulatory_penalty
material_contract
material_litigation
non_standard_audit
```

规则要求：

- 标题和 provider 原始类型都可以参与匹配。
- 规则输出 canonical `announcement_type`、`selected`、`rule_name`、`matched_text`、`reason`。
- 只有 `selected = true` 且 `announcement_type` 在 whitelist 内的公告才允许送入 LLM。
- LLM 输出的 `announcement_type` 不得反向修改 `announcements.announcement_type`。
- 如果 LLM 输出类型与规则类型不一致，保存结果但降低系统置信度。
- 规则必须确定性排序，避免同一标题多规则命中时结果不稳定。
- `earnings_report` 明确归一以下同义类型：
  - 业绩快报
  - 定期报告摘要
  - 年报摘要
  - 半年报摘要
  - 一季报摘要
  - 三季报摘要

## Pydantic Schema 单一来源

在 `src/ashare/llm/schemas.py` 中定义 Phase 2 输出模型。

Schema 常量：

```text
CURRENT_EXTRACTION_SCHEMA_VERSION = "phase2.v1"
```

Schema 至少表达：

```text
schema_version
announcement_type
sentiment: positive / neutral / negative / mixed / unknown
summary
key_evidence[]
catalysts[]
risks[]
extracted_metrics[]
```

每个 catalyst、risk、metric 必须包含：

```text
type / metric_name
summary 或 value
evidence_text
page 可选
raw_value_text 可选
```

要求：

- Pydantic 模型禁止包含 `score`、`total_score`、`target_price`、`buy`、`sell`、`recommendation`、`confidence`。
- 额外字段必须 forbidden 或被验证器拒绝。
- Prompt 中嵌入的 JSON Schema 必须来自 `AnnouncementExtraction.model_json_schema()`。
- 修改 Schema 时必须同步更新测试，不允许 prompt 内手写 schema 副本。
- 读取历史解析结果时，只支持 `schema_version == "phase2.v1"`；其他版本必须 fail-fast，不能静默反序列化。

## LLM Client 与解析

在 `src/ashare/llm/client.py` 中定义最小 LLM client protocol，并实现：

```text
FixtureLLMClient：从 fixture response 目录读取 JSON，供测试和硬验收使用。
OpenAICompatibleLLMClient：可选路径；未安装 optional extra 或缺少 API key / model 时 fail-fast。
```

Fixture response 解析规则：

```text
{announcement_id}.json
{announcement_id}.{variant}.json
```

新增 `ashare parse-announcements` 命令。

建议参数：

```text
--db-path，默认 data/processed/ashare.duckdb
--from，必填，按 effective_date 日期过滤
--to，必填，按 effective_date 日期过滤
--as-of，可选；传入时只解析 publish_time <= as_of 且 effective_date <= as_of 的公告
--source-tag，可选；传入时只解析该 source_tag
--parse-run-id，必填
--llm-mode fixture / openai-compatible，硬验收使用 fixture
--fixture-response-dir，llm-mode=fixture 时必填
--fixture-variant，可选
--model，真实 LLM 时必填；fixture 模式可用 fixture-llm
--limit，可选
--overwrite / --no-overwrite，默认 false
```

解析流程：

```text
读取公告
  -> 按 effective_date 做日期过滤
  -> 可选 as_of PIT 过滤
  -> 规则筛选 whitelist
  -> 读取 raw_path 正文
  -> 构造 prompt
  -> 调用 LLM client
  -> Pydantic schema 校验
  -> 证据定位
  -> 系统置信度计算
  -> 写入 parse run / result / evidence 表
```

要求：

- `ingest-announcements --from/--to` 使用 `publish_time`，因为 ingest 是按披露日期加载。
- `parse-announcements --from/--to` 使用 `effective_date`，因为 parse 结果后续作为研究证据必须遵守 PIT 可见性。
- 解析命令可以批量处理公告，但单条失败不能吞掉；必须记录失败状态和错误摘要。
- schema 校验失败时保存 raw response，`status = schema_invalid`，`confidence = 0.0`。
- LLM client 超时或返回空内容时，`status = llm_error`。
- 缺少 `raw_path` 或正文文件不存在时，默认跳过并记录 failed count。
- 不写入 `risk_events`。
- 不写入 `factor_values`。
- 不调用 `scan`、`score`、`backtest`、`event-study`。

## 系统置信度

置信度只由系统规则计算，取值范围 `[0.0, 1.0]`。

固定权重：

```text
schema_valid: 0.25
required_fields_complete: 0.15
evidence_present: 0.20
evidence_located_in_text: 0.25
announcement_type_whitelisted_and_consistent: 0.10
numeric_metrics_match_text: 0.05
```

固定 component score：

```text
schema_valid:
  schema 校验通过为 1.0，否则 0.0。

required_fields_complete:
  schema_version、announcement_type、sentiment、summary 都存在且非空为 1.0，否则按非空核心字段数 / 4 计算。
  catalysts、risks、extracted_metrics 允许为空数组，不因空数组扣分。

evidence_present:
  total_items = key_evidence + catalysts + risks + extracted_metrics 的条目数。
  items_with_evidence = evidence_text 非空的条目数。
  total_items == 0 时为 1.0。
  否则为 items_with_evidence / total_items。

evidence_located_in_text:
  total_evidence_count = evidence_text 非空的条目数。
  located_count = locator_status in ("exact", "normalized") 的证据数。
  total_evidence_count == 0 且 total_items == 0 时为 1.0。
  total_evidence_count == 0 且 total_items > 0 时为 0.0。
  否则为 located_count / total_evidence_count。

announcement_type_whitelisted_and_consistent:
  规则类型在 whitelist 内且 LLM 输出 announcement_type 等于规则类型时为 1.0，否则 0.0。

numeric_metrics_match_text:
  total_metrics = extracted_metrics 条目数。
  matched_metrics = raw_value_text 或 value 的字符串能在 evidence_text 或 normalized 正文中找到的条目数。
  total_metrics == 0 时为 1.0。
  否则为 matched_metrics / total_metrics。
```

最终公式：

```text
confidence = round(sum(component_weight * component_score), 6)
```

规则：

- JSON schema 无效时置信度强制为 `0.0`。
- LLM 输出中的任何自评置信度必须触发 schema invalid。
- `confidence_reasons` JSON keys 必须固定为：

```text
formula_version
weights
component_scores
counts
warnings
```

其中 `formula_version = "phase2.confidence.v1"`。

## 配置要求

更新 `configs/llm.yaml`，保持默认不自动调用真实 LLM：

```yaml
enabled: false
announcement_whitelist:
  - earnings_forecast
  - earnings_report
  - buyback
  - shareholder_reduce
  - inquiry_letter
  - regulatory_penalty
  - material_contract
  - material_litigation
  - non_standard_audit
schema_validation: true
store_evidence: true
default_llm_mode: fixture
max_input_chars: 20000
temperature: 0
```

不得在配置中写 API key。

## Followups 更新

修改 `docs/planning/followups.md`，从现有 D32 后追加：

```text
D33 真实公告源接入未落地
D34 跨 source 的同一逻辑公告暂不自动合并
D35 公告更正版 / 版本合并未实现
D36 candidate report 暂不注入 LLM 公告摘要
```

每条按现有 followups 格式记录：

```markdown
### Dxx. <债标题>

- 现状: ...
- 触发: ...
- 决策: ...
- 关联: ...
```

不得借本 phase 实现 D33-D36。

## 测试要求

新增或更新测试，至少覆盖：

1. fixture builder 生成公告正文文件和 fixture LLM response。
2. `ingest-announcements` 能从 CSV 导入公告并保存正文。
3. `effective_date` 由系统计算，不使用 CSV 中的值。
4. `announcement_id` 缺失时 hash 输入包含 `source_tag` 和正文 hash。
5. `source` / `source_tag` 正确写入 `announcements`。
6. `raw_path` 文件存在，`text_hash` 与 normalized 正文一致。
7. 正文规范化函数对 BOM、Unicode NFKC、换行和连续空白稳定。
8. 重复 ingest 且 `text_hash` 一致时 idempotent skip。
9. 重复 ingest 且 `text_hash` 不一致、未传 `--overwrite` 时 fail-fast。
10. 缺少正文时默认 fail-fast。
11. 规则能识别 whitelist 中全部重点公告类型。
12. `earnings_report` 同义词归一稳定。
13. 非 whitelist 公告不会送入 LLM。
14. Pydantic schema 能生成 JSON Schema。
15. Prompt 中的 schema 来自 Pydantic，不存在手写 schema 副本。
16. Schema 拒绝 `score`、`target_price`、`recommendation`、`confidence`。
17. Schema 只接受 `schema_version == "phase2.v1"`。
18. Fixture LLM response 可以通过 schema 校验。
19. Fixture LLM response 支持 `{announcement_id}.{variant}.json`。
20. 无效 JSON / 缺字段 / 多字段时正确失败。
21. 证据 exact match 和 normalized match 都能定位。
22. 找不到证据时置信度按固定公式下降。
23. LLM 类型与规则类型不一致时置信度下降。
24. `confidence_reasons` keys 固定且与权重项一一对应。
25. `parse_id` 生成规则稳定。
26. 解析结果写入 `announcement_llm_results`。
27. 证据片段写入 `announcement_llm_evidence`，且包含 `created_at`。
28. `parse_run_id` 重复且无 `--overwrite` 时 fail-fast。
29. `--overwrite` 重跑不产生重复 parse/evidence 行。
30. `parse-announcements --from/--to` 按 `effective_date` 过滤。
31. `parse-announcements --as-of` 不解析 `effective_date` 晚于 `as_of` 的公告。
32. 解析后 `factor_values` 不新增 `llm_` 或 `announcement_llm_` 前缀因子。
33. 解析后 `scan`、`backtest` 行为不依赖 LLM 表。
34. pytest 不访问真实网络、不调用真实 LLM。
35. `ashare --help` 能看到新增命令：

```text
ingest-announcements
parse-announcements
```

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
rm -f data/processed/ashare_phase2.duckdb
```

```bash
conda run -n ashare-research-lab ashare ingest-local \
  --input-dir tests/fixtures/generated \
  --db-path data/processed/ashare_phase2.duckdb
```

```bash
conda run -n ashare-research-lab ashare ingest-announcements \
  --source csv \
  --source-tag phase2-fixture \
  --input-csv tests/fixtures/generated/announcements.csv \
  --body-dir tests/fixtures/generated/announcement_bodies \
  --from 2026-01-05 \
  --to 2026-03-31 \
  --db-path data/processed/ashare_phase2.duckdb \
  --raw-output-dir data/raw/announcements/phase2-fixture \
  --overwrite
```

```bash
conda run -n ashare-research-lab ashare parse-announcements \
  --db-path data/processed/ashare_phase2.duckdb \
  --from 2026-01-06 \
  --to 2026-03-31 \
  --as-of 2026-03-31 \
  --source-tag phase2-fixture \
  --parse-run-id phase2-fixture-parse \
  --llm-mode fixture \
  --fixture-response-dir tests/fixtures/generated/llm_responses \
  --model fixture-llm \
  --overwrite
```

```bash
conda run -n ashare-research-lab python - <<'PY'
import duckdb

con = duckdb.connect("data/processed/ashare_phase2.duckdb", read_only=True)

announcement_rows = con.execute("""
    SELECT COUNT(*) FROM announcements
    WHERE source_tag = 'phase2-fixture'
      AND raw_path IS NOT NULL
      AND text_hash IS NOT NULL
""").fetchone()[0]

parse_rows = con.execute("""
    SELECT COUNT(*) FROM announcement_llm_results
    WHERE parse_run_id = 'phase2-fixture-parse'
      AND source_tag = 'phase2-fixture'
      AND status = 'success'
      AND schema_version = 'phase2.v1'
      AND confidence BETWEEN 0.0 AND 1.0
""").fetchone()[0]

evidence_rows = con.execute("""
    SELECT COUNT(*) FROM announcement_llm_evidence
    WHERE locator_status IN ('exact', 'normalized')
""").fetchone()[0]

llm_factor_rows = con.execute("""
    SELECT COUNT(*) FROM factor_values
    WHERE factor_name LIKE 'llm_%'
       OR factor_name LIKE 'announcement_llm_%'
""").fetchone()[0]

assert announcement_rows > 0
assert parse_rows > 0
assert evidence_rows > 0
assert llm_factor_rows == 0
print("OK", announcement_rows, parse_rows, evidence_rows)
PY
```

```bash
conda run -n ashare-research-lab pytest -q
```

```bash
conda run -n ashare-research-lab ashare --help
```

## 完成后

1. 运行 `git status`，确认只包含 Phase 2 相关代码、测试、配置和必要文档改动。
2. 确认未提交：
   - `data/raw/announcements/`
   - `data/processed/*.duckdb`
   - `tests/fixtures/generated/`
   - 真实公告正文、缓存、LLM 响应或生成报告
3. 执行 `git add .`。
4. 执行：

```bash
git commit -m "feat: phase 2 announcement llm parsing"
```

5. 最终回复说明：
   - 修改了哪些文件。
   - 为什么 ingest 按 `publish_time`，parse 按 `effective_date`。
   - 公告正文保存路径和 `text_hash` 规则。
   - `source` / `source_tag` 与 `announcement_id` 去重规则。
   - 规则筛选支持哪些公告类型。
   - Pydantic schema 如何作为单一来源。
   - LLM 解析结果和证据写入哪些表。
   - 系统置信度如何计算。
   - 如何保证 LLM 输出没有进入总分、因子值、候选排序或回测。
   - 验收命令是否全部通过。
   - commit hash。
   - 是否发现 plan 或前置 phase 的新缺口。

## 不要实现

- 不实现真实公告源接入。
- 不实现巨潮 / 交易所 provider。
- 不实现 PDF 下载、PDF 文本抽取、OCR 或复杂版面分析。
- 不修改 `environment.yml`。
- 不新增基础运行时依赖。
- 不实现公告版本合并或更正版合并。
- 不实现 cross-source 公告合并。
- 不实现综合评分。
- 不实现 Phase 3 权重配置。
- 不把 LLM 输出写入 `factor_values`。
- 不把 LLM 输出写入 `risk_events`。
- 不让 LLM 结果影响 `scan` 排名。
- 不向 candidate report 注入 LLM 摘要。
- 不让 LLM 结果影响 `backtest`。
- 不实现事件研究验证。
- 不实现 LLM 事件分。
- 不实现买入、卖出、目标价、仓位建议。
- 不实现 Web / FastAPI / 前端。
- 不实现定时任务、队列、重试平台或监控。
- 不实现向量库、RAG、长文多轮 agent 阅读。
- 不提交真实公告正文或真实 LLM 响应。

## 发现的缺口

- 当前 plan / schema 的 `announcements` 只有元数据字段，没有解析结果表和证据表；Phase 2 需要最小新增 `announcement_parse_runs`、`announcement_llm_results`、`announcement_llm_evidence`。
- 当前 `announcements` 缺少 `source` 和 `source_tag` 字段，不利于 fixture、CSV 和后续真实公告源隔离；Phase 2 建议最小补列。
- 跨 source 的同一逻辑公告可能重复存在；本 phase 不自动合并，后续需要单独设计公告身份归并规则。
- 公告更正版 / 版本关系未建模；本 phase 不处理版本合并。
- `configs/llm.yaml` whitelist 中的 `earnings_report` 需要明确覆盖业绩快报和定期报告摘要，避免新增多个近义 canonical type。
- 真实公告源存在分页、反爬、PDF 格式和字段变化风险；真实源接入应放到 Phase 2.5，不能混入本 phase 的硬验收路径。
