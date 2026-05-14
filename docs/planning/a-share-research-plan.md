# A 股研究辅助系统 Plan

## 1. 目标定位

本系统面向个人研究使用，目标是建立一个可验证、可复盘的股票研究辅助流程。

它不是自动荐股系统，也不是用来预测某只股票一定上涨。它要解决的是：

- 用统一的数据口径整理行情、财务、估值、公告和风险信息。
- 用可复现的代码计算因子、筛选候选股票、生成研究报告。
- 用历史数据验证信号是否曾经有效，而不是只讲故事。
- 用 LLM 辅助阅读公告、财报、问询函等文本，但不让 LLM 直接决定买卖。
- 每一次输出都能追溯到当时可见的数据、配置、代码版本和原始证据。

核心原则：

```text
代码负责事实、计算、验证和复盘。
LLM 负责阅读、提取、摘要和解释。
任何信号必须能用历史 Point-in-Time 数据验证。
任何结论必须能追溯到数据来源或公告证据。
候选股票只是研究清单，不是交易指令。
```

本系统追求的是研究流程质量：

- **可验证**：每个因子、事件、评分逻辑都能做历史检验。
- **可复盘**：每次运行保留 `run_id`、`as_of_date`、配置、数据快照和输出。
- **可解释**：每只股票进入候选池的原因、风险和证据都能展开查看。
- **可迭代**：先验证单因子，再验证组合，再引入 LLM 和综合打分。

## 2. 第一版 MVP 范围

第一版先做离线研究系统，不急于服务化，不做自动交易，不做实时行情。

第一版目标不是把所有能力一次做完，而是先把“数据时点正确、因子可验证、报告可复盘”这条主线跑通。

建议范围：

- 项目 / 仓库名：`ashare-research-lab`。
- Conda 环境名：`ashare-research-lab`，必须和项目名一致。
- 股票池：沪深 300 的历史成分股起步，后续扩展到中证 500、全 A。
- 时间范围：最近 3-5 年。
- 数据频率：日频。
- 数据库：DuckDB。
- 运行方式：CLI 命令行。
- 输出形式：Markdown 报告 + CSV 明细。
- 第一版输出：候选研究清单，而不是买入/卖出建议。

第一版闭环：

```text
采集 Point-in-Time 数据
  -> 计算基础因子
  -> 单因子有效性检验
  -> 事件研究 / 信号验证
  -> 输出候选清单和验证报告
```

第一版暂不强制包含：

- LLM 事件分。
- FastAPI 服务。
- Web 前端。
- 多策略平台。
- 自动交易。
- 复杂风格归因。

## 3. 阶段路线

### 阶段 1a：数据与单因子验证

目标：先证明基础研究流程可靠。

要完成：

- 建项目骨架。
- 接入行情、估值、财务、指数成分数据。
- 建立 DuckDB 表结构。
- 保存原始数据和处理后数据。
- 建立 Point-in-Time 生效时间规则。
- 计算基础因子。
- 输出因子覆盖率、缺失率和异常值检查。
- 对每个因子做 IC、Rank IC、分组收益、衰减曲线。
- 生成 Markdown 和 CSV 因子验证报告。

阶段 1a 的产物：

- 可复现的数据落库流程。
- 基础因子表。
- 单因子验证报告。
- 初版候选股票研究清单。

### 阶段 1b：简单组合回测

目标：把已经验证过的信号放进组合框架里测试。

要完成：

- 定义调仓频率。
- 定义买入、卖出、停牌、涨跌停处理规则。
- 定义手续费、印花税、滑点等成本配置。
- Top N 等权组合回测。
- 和基准指数对比。
- 输出收益、超额收益、回撤、波动率、换手率、成本后表现。

阶段 1b 的产物：

- 简单但可复现的组合回测引擎。
- 回测假设清单。
- 策略回测报告。

### 阶段 2：LLM 公告解析

目标：让 LLM 辅助阅读文本，而不是替代量化验证。

要完成：

- 拉取公告标题、发布时间、公告类型、原文链接和正文。
- 先用规则筛选重要公告类型。
- 只把关键公告送入 LLM。
- LLM 输出结构化 JSON。
- 保存证据片段、公告原文位置和解析结果。
- 由系统规则计算解析置信度。

阶段 2 初期不让 LLM 直接参与总分，只把它作为研究证据和风险提示来源。

### 阶段 3：综合评分

目标：在单因子和组合回测都可验证之后，再做综合打分。

要完成：

- 因子标准化。
- 权重配置。
- 风险硬过滤和软扣分分离。
- 加入 LLM 事件信息，但必须先验证其历史效果。
- 做权重敏感性测试和分年度稳定性测试。

### 阶段 4：服务化和 Skill 封装

目标：在离线流程稳定后，再提升使用体验。

可选内容：

- FastAPI 查询接口。
- 定时任务。
- Web 前端。
- 每日报告推送。
- Codex Skill 操作入口。

## 4. 系统架构

```text
数据源
  行情 / 财务 / 估值 / 指数成分 / 公告 / 风险事件
    ↓
数据层
  拉取、清洗、去重、原始数据归档、Point-in-Time 落库
    ↓
因子层
  财务因子 / 估值因子 / 动量因子 / 风险相关字段
    ↓
验证层
  单因子 IC / 分组收益 / 衰减曲线 / 事件研究
    ↓
组合回测层
  调仓、撮合、持仓、成本、基准、风险指标
    ↓
打分层
  标准化、权重、硬过滤、软扣分、候选排序
    ↓
报告层
  Markdown / CSV / HTML

LLM 层
  公告解析 / 风险抽取 / 催化剂识别 / 财报摘要 / 证据引用
  只作为研究证据输入，不直接替代验证层
```

## 5. 推荐目录结构

```text
ashare-research-lab/
  configs/
    universe.yaml
    data.yaml
    data_dictionary.yaml
    factors.yaml
    validation.yaml
    backtest.yaml
    scoring.yaml
    llm.yaml

  data/
    raw/
    processed/
    reports/
    snapshots/

  docs/
    build_data_dictionary.py
    data_dictionary.md
    backtest_assumptions.md
    factor_definitions.md

  src/
    ashare/
      ingest/
        prices.py
        fundamentals.py
        valuations.py
        universe.py
        announcements.py

      storage/
        db.py
        schema.sql
        snapshots.py

      pit/
        effective_date.py
        asof.py

      factors/
        financial.py
        valuation.py
        momentum.py
        risk.py
        normalize.py

      validation/
        ic.py
        quantile_returns.py
        event_study.py
        decay.py

      backtest/
        engine.py
        broker.py
        metrics.py
        costs.py

      llm/
        client.py
        prompts.py
        schemas.py
        validators.py

      scoring/
        scorer.py
        filters.py
        universe.py

      reports/
        factor_report.py
        daily.py
        stock_report.py
        backtest_report.py

      cli.py

  notebooks/
    factor_exploration.ipynb

  tests/
    test_pit.py
    test_factors.py
    test_validation.py
    test_backtest.py
    test_llm_parser.py

  environment.yml
  pyproject.toml
  README.md
```

命名规则：

- Git 仓库名使用 `ashare-research-lab`。
- Conda 环境名使用 `ashare-research-lab`，和仓库名保持一致。
- Python 包名使用 `ashare`，避免包名中出现连字符。
- CLI 命令使用 `ashare`。

Python 环境规则：

- 必须用 Conda 管理虚拟环境。
- 所有 Python 脚本、CLI、测试和 notebook 都必须在 `ashare-research-lab` 环境中运行。
- 不使用系统 Python 直接运行项目脚本。
- 不在全局环境安装项目依赖。
- 自动化脚本优先使用 `conda run -n ashare-research-lab ...`，交互式开发使用 `conda activate ashare-research-lab`。
- `environment.yml` 是环境依赖的主入口；`pyproject.toml` 负责 Python 包元数据、CLI entrypoint 和开发工具配置。

## 6. 数据层设计

第一版可以用 AkShare 起步，但不能默认免费数据源天然满足回测要求。财务、指数成分、退市、ST、公告等数据如果没有历史快照或 Point-in-Time 口径，需要额外补源或做本地快照。

后续可评估补充：

- Tushare Pro。
- baostock。
- 交易所公告。
- 巨潮资讯公告。
- 自建定期快照。

核心数据表：

```text
trading_calendar
  trade_date, is_open, prev_trade_date, next_trade_date

securities
  stock_code, stock_name, exchange, list_date, delist_date

industry_classifications
  stock_code, industry_standard, industry_l1, industry_l2,
  in_date, out_date, version, source

universe_members
  index_code, stock_code, in_date, out_date, source

daily_prices
  stock_code, trade_date, open, high, low, close,
  volume, amount, adj_factor, is_suspended,
  limit_up, limit_down

st_status
  stock_code, st_type, in_date, out_date, source

fundamental_reports
  stock_code, report_period, publish_time, effective_date,
  revenue, net_profit, roe, gross_margin,
  operating_cashflow, debt_ratio,
  goodwill, total_equity, accounts_receivable,
  inventory, source

valuation_daily
  stock_code, trade_date, pe_ttm, pb, ps,
  dividend_yield, total_mv, float_mv, source

announcements
  announcement_id, stock_code, title, announcement_type,
  publish_time, effective_date, url, raw_path, text_hash

risk_events
  event_id, stock_code, event_type, event_date,
  publish_time, effective_date, payload_json, source

factor_values
  stock_code, trade_date, factor_name, factor_value,
  as_of_date, source_run_id

research_runs
  run_id, as_of_date, status, params, config_hash,
  data_snapshot_id, git_sha, worktree_clean,
  started_at, finished_at, error
```

行业分类第一版建议固定一种标准，例如申万一级 / 二级行业。行业分类会调整，所以必须像指数成分一样保存 `in_date`、`out_date` 和 `version`，回测时只能使用 `as_of_date` 当时有效的行业分类。

快照方案第一版建议：

- 原始数据保存为 Parquet，按 `source`、`dataset`、`ingest_date` 分区。
- 处理后的 Point-in-Time 数据进入 DuckDB 表。
- 因子表保留 `as_of_date` 或 `source_run_id`，方便复盘和追踪。
- 正式研究运行写入 `research_runs`，记录完整 CLI 参数、配置哈希、数据快照 ID 和 `git_sha`。
- 正式 `run_id` 要求 git 工作区干净；探索性运行可以放宽，但必须标记为非正式结果。

`industry_classifications` 的一条记录表示：在分类标准 `industry_standard` 的 `version` 版本下，`stock_code` 在 `[in_date, out_date)` 期间被划入 `industry_l1` / `industry_l2`。`as_of_date` 使用哪个行业版本由配置决定，第一版默认固定一个版本，例如 `sw_2021`。

`st_status` 像指数成分一样保存时间区间状态。`st_type` 可取 `ST`、`*ST`、`退市风险警示` 等，`is_st` 在某个 `as_of_date` 的取值由这张表按区间查询得到，不能用当前股票名称或当前状态倒推历史。

`risk_events` 保存质押、减持、问询函、监管处罚、非标审计意见等风险事件流。`event_type` 可取 `pledge`、`shareholder_reduce`、`inquiry_letter`、`regulatory_penalty`、`non_standard_audit` 等。`recent_big_shareholder_reduce`、`inquiry_letter_count`、`pledge_ratio` 这类字段是基于 `risk_events` 在 `as_of_date` 的历史窗口聚合得到的因子值，不是直接手写字段。

`fundamental_reports` 第一版可以先列常用字段，但本质应按 `publish_time` 保存财报快照。实际字段集以 `configs/data_dictionary.yaml` 为准；如果因子用到商誉、净资产、应收账款、存货等字段，必须先在数据字典和表结构中定义来源、单位和生效规则。

`factor_values` 中：

- `trade_date` 表示因子值对应的交易日。
- `as_of_date` 表示生成该因子值时所用数据的截止日。
- 通常 `as_of_date == trade_date`。
- 如果后续用更晚的数据回填某个历史交易日的因子，允许 `as_of_date > trade_date`。
- 回测必须按 `as_of_date <= 当前模拟交易日` 过滤，而不能只按 `trade_date` 过滤。

## 7. Point-in-Time 规则

这是本系统最重要的约束。

所有研究输出必须带 `as_of_date`。在 `as_of_date` 当天运行系统时，只能使用当时已经公开且已经生效的数据。

统一规则：

- 行情数据以 `trade_date` 标识。
- 财务数据必须同时保存 `report_period`、`publish_time`、`effective_date`。
- 公告数据必须保存 `publish_time` 和 `effective_date`。
- 指数成分必须使用历史成分，不能用当前成分倒推过去。
- 已退市、曾经 ST、后来摘帽、后来被剔除指数的股票都要保留在历史数据中。
- 原始数据只追加，不覆盖。
- 每次研究运行记录数据快照和配置哈希。

生效时间建议：

```text
财报 / 公告在 T 日披露：
  默认从 T+1 个交易日开盘后生效。

盘中披露：
  第一版统一从下一个交易日生效，避免日内口径复杂化。

盘后披露：
  从下一个交易日生效。

未知披露时刻：
  使用披露日期的下一个交易日生效。
```

这条规则会牺牲一点及时性，但可以显著降低回测偷看未来的风险。

## 8. 数据字典要求

每个字段和因子都必须有数据字典。没有定义清楚的数据，不进入正式研究报告。

数据字典使用机器可读的 YAML 作为单一事实源，例如 `configs/factors.yaml` 或 `configs/data_dictionary.yaml`。Markdown 文档只作为渲染产物，避免配置、代码和说明文档逐渐漂移。

`docs/data_dictionary.md` 由 `docs/build_data_dictionary.py` 从 YAML 自动生成，禁止手写维护 Markdown 版数据字典。

每个字段或因子至少定义：

- 因子名。
- 数据来源。
- 原始字段。
- 计算公式。
- 单位。
- 更新频率。
- 生效时间。
- 因子方向：越大越好、越小越好、区间最优。
- 缺失值处理。
- 极值处理。
- 标准化方式。
- 是否参与硬过滤。
- 是否参与软扣分。
- 是否参与总分。

示例：

```yaml
factor_name: revenue_yoy
type: factor
source: fundamental_reports
formula: current_period_revenue / same_period_last_year_revenue - 1
unit: ratio
effective_date: 财报 publish_time 的下一交易日
direction: higher_is_better
missing: 不参与该因子排名
outlier: 横截面 1% / 99% winsorize
normalize: 行业内横截面 percentile rank
hard_filter: false
soft_penalty: false
score_group: financial
```

## 9. 因子层设计

第一版因子不追求复杂，先保证可解释、可回测、可稳定复现。

财务质量因子：

- `revenue_yoy`
- `profit_yoy`
- `roe`
- `gross_margin_change`
- `operating_cashflow_to_profit`
- `debt_ratio`

估值因子：

- `pe_ttm_percentile`
- `pb_percentile`
- `ps_percentile`
- `dividend_yield`

暂不建议第一版使用 `peg`。如果没有可靠的一致盈利预测数据，可以后续改成：

- `pe_to_historical_profit_growth`

但它不应再叫 PEG。

动量因子：

- `return_20d`
- `return_60d`
- `above_ma60`
- `relative_strength_vs_index`
- `volume_breakout`

风险相关字段分为两类，不能混用。

硬过滤标志只做布尔判断，不作为连续因子进入打分：

- `is_st`
- `is_suspended`
- `is_delisted`
- `low_liquidity`

软扣分风险因子进入风险扣分或风险报告：

- `pledge_ratio`
- `inquiry_letter_count`
- `recent_big_shareholder_reduce`
- `non_standard_audit_count`
- `goodwill_to_equity`
- `receivable_growth_abnormal`
- `inventory_growth_abnormal`

软扣分项的数据来源：

- `pledge_ratio` 来自 `risk_events` 中 `pledge` 事件的最新有效状态或窗口聚合。
- `inquiry_letter_count` 来自 `risk_events` 中 `inquiry_letter` 事件的历史窗口计数。
- `recent_big_shareholder_reduce` 来自 `risk_events` 中 `shareholder_reduce` 事件的历史窗口聚合。
- `non_standard_audit_count` 来自 `risk_events` 中 `non_standard_audit` 事件的历史窗口计数。
- `goodwill_to_equity`、`receivable_growth_abnormal`、`inventory_growth_abnormal` 来自 `fundamental_reports` 的财报快照字段。

同一个指标只能选择一条通路。`goodwill_to_equity`、`receivable_growth_abnormal`、`inventory_growth_abnormal` 第一版作为软扣分项处理，不进入 `financial_score`。

复权规则：

- 交易撮合使用未复权价格。
- 收益率和动量因子使用后复权价格序列计算。
- 回测中的后复权价格只能使用截至该交易日已经发生的累计复权因子。
- 前复权会被未来分红、送转改写历史价格，不能用于回测信号计算。
- 展示 K 线可以使用前复权。
- 不允许未来分红、送转、拆股改写 `as_of_date` 当时的信号判断。

## 10. 因子标准化

综合打分前，所有因子必须先变成可比较的分数。

推荐流程：

```text
原始因子值
  -> 缺失值处理
  -> 极值处理
  -> 方向统一
  -> 横截面标准化
  -> 可选行业中性化
  -> 0-100 分数
```

第一版建议：

- 对每个交易日的股票池做横截面 percentile rank。
- 明确每个因子是越大越好还是越小越好。
- 所有子分统一到 0-100。
- 缺失值不默认填 0，先单独记录覆盖率。
- 财务和估值因子可先做行业内排名，避免行业结构主导结果。
- 行业内排名必须使用 `as_of_date` 当时有效的行业分类。

没有完成标准化前，不应该使用如下公式：

```text
30% financial_score + 20% valuation_score + ...
```

否则权重没有实际含义。

## 11. 验证层设计

验证层放在因子层和综合打分之间。没有通过验证的因子，不应直接进入总分。

### 单因子检验

每个因子至少输出：

- 覆盖率。
- 缺失率。
- 极值分布。
- Rank IC。
- IC 均值。
- ICIR。
- Top / Bottom 分组收益。
- 多空组合收益。
- 未来 5 / 20 / 60 / 120 个交易日衰减曲线。
- 分年度表现。
- 分行业表现。
- 换手率。

多空组合收益仅作为单因子分析口径，用于评估因子区分度。A 股个股做空受限，融券券源、成本和可得性需要单独建模，因此该指标不代表可执行策略。

### 事件研究

事件研究用于验证公告、业绩预告、回购、减持、问询函等事件。

事件研究不是组合回测。它回答的是：

```text
某类事件在发生后 5 / 20 / 60 个交易日内，
相对基准是否有统计意义上的收益或风险特征？
```

事件研究需要定义：

- 事件类型。
- 事件有效日期。
- 样本选择规则。
- 观察窗口。
- 基准收益。
- 行业调整收益。
- 胜率。
- 平均收益。
- 中位数收益。
- 分位数分布。

### 组合回测

组合回测用于验证实际调仓逻辑。它回答的是：

```text
如果按某个规则在历史上定期调仓，
组合层面是否有可接受的收益、风险、回撤和换手？
```

组合回测要晚于单因子验证和事件研究。

## 12. 回测假设清单

所有回测假设集中写入 `docs/backtest_assumptions.md` 和 `configs/backtest.yaml`。

第一版建议规则：

- 每日扫描默认在收盘后运行。
- 扫描日为 T，最早交易日为 T+1。
- 买入价默认使用 T+1 开盘价或配置化成交价。
- 卖出价默认使用 T+1 开盘价或配置化成交价。
- 停牌股票不能买入或卖出。
- 一字涨停或涨停不可买入时，跳过买入。
- 一字跌停或跌停不可卖出时，继续持有。
- 退市股票必须保留在回测样本中，并定义保守退出规则。
- 长期停牌股票不能从历史样本中静默删除。
- 使用配置化手续费、印花税、滑点。
- 加入最小成交额或流动性过滤。
- 记录每次调仓的目标权重、实际成交、未成交原因。

扫描频率和调仓频率分开定义：

- 扫描频率：每日、每周或每月生成研究清单。
- 调仓频率：组合回测实际换仓频率，例如月频或季频。
- 调仓触发日：例如每月最后一个交易日 T 收盘后生成信号。
- 成交日：默认 T+1 开盘按撮合规则成交。
- 日频扫描不等于日频调仓；日频扫描可以只用于观察候选池变化。

组合指标：

- 年化收益。
- 基准收益。
- 超额收益。
- 最大回撤。
- 波动率。
- 夏普比率。
- Calmar 比率。
- 胜率。
- 换手率。
- 成本前收益。
- 成本后收益。
- 分年度收益。

基准：

- 沪深 300 股票池优先对比沪深 300。
- 沪深 300 股票池同时增加沪深 300 等权基准，避免 Top 20 等权组合和市值加权指数不可比。
- 中证 500 股票池优先对比中证 500。
- 中证 500 股票池同时增加中证 500 等权基准。
- 全 A 股票池可对比中证全指或自定义等权基准。
- 后续再加入行业中性组合和风格归因。

## 13. LLM 层设计

LLM 不直接输出买入或卖出结论，也不直接决定股票是否进入候选池。

适合 LLM 做的事情：

- 判断公告类型。
- 提取业绩变化。
- 提取正面催化剂。
- 提取风险项。
- 摘要财报和问询函。
- 对候选股票生成可读解释。
- 把原文证据结构化保存。

不适合 LLM 做的事情：

- 直接给买入、卖出、目标价。
- 直接替代财务指标计算。
- 在没有证据时推断重大结论。
- 自己决定置信度并作为系统置信度使用。
- 自己计算公告或事件的 `effective_date`。
- 在未经历史验证前直接贡献总分。

LLM 处理流程：

```text
公告入库
  -> 系统按 publish_time 计算 effective_date
  -> 标题和公告类型规则过滤
  -> 只保留关键公告
  -> 正文抽取
  -> LLM 结构化解析
  -> JSON Schema 校验
  -> 系统计算解析置信度
  -> 入库
```

LLM 输出 Schema 由 `src/ashare/llm/schemas.py` 中的 Pydantic 模型单一定义。Prompt 中嵌入的 Schema 描述必须由代码自动生成，禁止手写第二份 Schema。

第一版重点公告类型：

- 业绩预告。
- 业绩快报。
- 定期报告摘要。
- 回购。
- 减持。
- 重大合同。
- 重大诉讼。
- 问询函。
- 监管处罚。
- 非标审计意见。

LLM 内容输出示例：

```json
{
  "announcement_type": "业绩预告",
  "sentiment": "positive",
  "catalysts": [
    {
      "type": "profit_growth",
      "summary": "净利润同比增长",
      "evidence": "公告原文中的关键依据",
      "page": 1
    }
  ],
  "risks": [
    {
      "type": "cashflow_quality",
      "summary": "经营现金流弱于利润",
      "evidence": "公告原文中的关键依据",
      "page": 2
    }
  ],
  "extracted_metrics": {
    "net_profit_yoy_min": 0.3,
    "net_profit_yoy_max": 0.5
  }
}
```

`announcement_id`、`stock_code`、`publish_time`、`effective_date` 等元数据由系统从公告表附加和计算。LLM 只负责公告内容相关字段，例如分类、摘要、催化剂、风险、证据和抽取的数值。

系统置信度不由 LLM 自评，而由规则计算：

- JSON 是否通过 Schema。
- 必填字段是否完整。
- 证据片段是否非空。
- 证据是否能在原文中定位。
- 公告类型是否在白名单内。
- 数值字段是否能和原文匹配。

## 14. 打分层设计

综合打分必须晚于因子验证。

打分层分三步：

```text
硬过滤
  -> 标准化子分
  -> 软风险扣分
```

硬过滤适合处理：

- 当前 ST。
- 已退市。
- 长期停牌。
- 成交额过低。
- 数据严重缺失。
- 明确不可交易状态。

软风险扣分适合处理：

- 股权质押比例高：`pledge_ratio`。
- 近期问询函较多：`inquiry_letter_count`。
- 减持压力：`recent_big_shareholder_reduce`。
- 非标审计意见：`non_standard_audit_count`。
- 商誉占净资产比例高：`goodwill_to_equity`。
- 应收账款异常增长：`receivable_growth_abnormal`。
- 存货异常增长：`inventory_growth_abnormal`。

不要同一个风险既硬过滤又软扣分，避免双重惩罚。

综合打分示例：

```text
total_score =
  30% financial_score
+ 20% valuation_score
+ 20% momentum_score
+ 15% event_score
- 15% risk_penalty
```

但只有在以下条件满足后才能启用：

- 每个子分都已经标准化到 0-100。
- 每个子分的历史有效性已经验证。
- 权重写入配置文件。
- 输出权重敏感性测试。
- LLM 事件分经过事件研究验证。

第一版可以先不做总分，只输出因子分项和简单排序。

## 15. 报告层设计

第一版生成 Markdown 和 CSV。

### 每日研究报告

内容：

- `as_of_date`。
- `run_id`。
- 股票池。
- 数据快照 ID。
- 配置哈希。
- 今日候选 Top N。
- 每只股票的因子分项。
- 入选逻辑。
- 主要风险。
- 近期公告摘要。
- 因子历史验证摘要。
- 和基准指数的相对强弱。
- 和上一交易日相比的新增、移出、排序变化。

### 单股研究报告

内容：

- 基本信息。
- 所属行业。
- 最近财务表现。
- 当前估值位置。
- 动量和相对强弱。
- 风险标志和软扣分项。
- 最近公告和证据片段。
- 是否进入候选池。
- 因子历史分位和近期变化。
- 数据来源和更新时间。

### 因子验证报告

内容：

- 因子覆盖率。
- 因子分布。
- IC / Rank IC。
- ICIR。
- 分组收益。
- 衰减曲线。
- 分年度表现。
- 分行业表现。
- 结论：保留、观察、剔除。

### 回测报告

内容：

- 策略规则。
- 回测区间。
- 调仓频率。
- 交易假设。
- 基准。
- 收益和风险指标。
- 年度表现。
- 最大回撤区间。
- 持仓和换手。
- 成本影响。
- 失败案例。

## 16. CLI 设计

第一阶段用命令行驱动。

示例日期使用已完成交易和结算的数据日期。若当天数据尚未完整，默认使用最近一个完整交易日。

首次初始化：

```bash
conda env create -f environment.yml
conda activate ashare-research-lab
python -m pip install -e .
```

日常运行：

```bash
conda activate ashare-research-lab

ashare ingest --universe hs300 --from 2021-01-01 --to 2026-05-13

ashare validate-factors \
  --universe hs300 \
  --from 2021-01-01 \
  --to 2026-05-13 \
  --horizon 20,60,120

ashare event-study \
  --event earnings_forecast \
  --from 2021-01-01 \
  --to 2026-05-13 \
  --horizon 5,20,60

ashare scan \
  --as-of 2026-05-13 \
  --universe hs300 \
  --top 20

ashare backtest \
  --strategy base_score \
  --from 2021-01-01 \
  --to 2026-05-13

ashare report \
  --as-of 2026-05-13

ashare stock-report \
  --code 000001 \
  --as-of 2026-05-13
```

## 17. 配置文件设计

所有研究口径尽量配置化，避免散落在代码里。

`environment.yml`：

```yaml
name: ashare-research-lab
channels:
  - conda-forge
dependencies:
  - python=3.12
  - pip
  - duckdb
  - pandas
  - numpy
  - pyarrow
  - pydantic
  - typer
  - pytest
  - jupyterlab
  - pip:
      - akshare
```

`configs/universe.yaml`：

```yaml
universe: hs300
use_historical_members: true
include_delisted: true
include_past_st: true
```

`configs/data.yaml`：

```yaml
industry:
  standard: sw
  version: sw_2021
  levels:
    - industry_l1
    - industry_l2
```

`configs/factors.yaml`：

```yaml
normalization:
  method: percentile
  winsorize:
    lower: 0.01
    upper: 0.99
  industry_neutral: true

factors:
  revenue_yoy:
    direction: higher_is_better
    group: financial
    hard_filter: false
    soft_penalty: false
  pe_ttm_percentile:
    direction: lower_is_better
    group: valuation
    hard_filter: false
    soft_penalty: false

hard_filters:
  is_st:
    enabled: true
  is_suspended:
    enabled: true
  is_delisted:
    enabled: true
  low_liquidity:
    enabled: true

soft_penalties:
  pledge_ratio:
    enabled: true
  inquiry_letter_count:
    enabled: true
  recent_big_shareholder_reduce:
    enabled: true
  non_standard_audit_count:
    enabled: true
  goodwill_to_equity:
    enabled: true
  receivable_growth_abnormal:
    enabled: true
  inventory_growth_abnormal:
    enabled: true
```

`configs/backtest.yaml`：

```yaml
scan:
  frequency: daily

rebalance:
  frequency: monthly
  trigger: month_end
  execution: next_open

portfolio:
  top_n: 20
  weighting: equal_weight

benchmark:
  primary: hs300
  secondary: hs300_equal_weight

trading_rules:
  skip_buy_if_limit_up: true
  block_sell_if_limit_down: true
  hold_if_suspended: true

costs:
  commission_bps: 2.5       # 单边佣金，买入和卖出各收
  stamp_tax_bps: 10         # 印花税，仅卖出收
  slippage_bps: 5           # 单边滑点
  min_commission_yuan: 5    # 单笔最低佣金，按实际券商配置替换
```

`configs/llm.yaml`：

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
```

## 18. 服务化设计

服务化放到离线流程稳定之后。

接口示例：

```text
GET /scan/latest
GET /scans/{run_id}
GET /stocks/{code}/report
GET /stocks/{code}/factors
GET /factors/{factor_name}/validation
POST /backtest
GET /backtest/{run_id}
```

服务化之后可以再加：

- 定时任务。
- Web 前端。
- 每日邮件或消息推送。
- 多策略配置。
- 因子对比面板。

## 19. Skill 设计

Skill 不承载核心逻辑，只作为 Codex/LLM 操作这个系统的说明书。

Skill 可以定义：

- 如何运行今日扫描。
- 如何生成单股报告。
- 如何解释因子验证报告。
- 如何解释回测结果。
- 如何新增因子。
- 如何调整评分权重。
- 如何排查数据异常。

推荐关系：

```text
Python 项目 / 服务 = 真正干活的系统。
Skill = 操作系统的工作流入口。
```

## 20. 测试要求

必须优先测试会影响研究可信度的逻辑。

核心测试：

- Point-in-Time 测试：`as_of_date` 之后的数据不能被读取。
- 财报生效测试：财报只能在 `effective_date` 后进入因子。
- 公告生效测试：公告只能在 `effective_date` 后进入事件。
- 历史成分测试：过去日期只能使用当时的指数成分。
- 行业分类测试：过去日期只能使用当时有效的行业分类版本。
- 退市样本测试：退市股票不能从历史样本中消失。
- 因子标准化测试：所有子分输出范围一致。
- 单因子验证测试：IC、分组收益计算口径稳定。
- 回测撮合测试：停牌、涨跌停、成本处理正确。
- LLM JSON 测试：输出必须通过 Schema。
- 报告复现测试：同一数据快照和配置重复运行，结果一致。
- 正式运行测试：正式 `run_id` 必须记录 `git_sha`、完整参数和工作区状态。

## 21. 关键风险

- 免费数据源字段变更。
- 免费数据源缺少真实 Point-in-Time 数据。
- 财报披露时间处理错误。
- 当前指数成分倒推历史导致存活者偏差。
- 已退市股票缺失导致收益虚高。
- 复权处理不当导致动量信号失真。
- LLM 产生幻觉。
- LLM 成本和速率不可控。
- 综合打分过早引入导致过拟合。
- 交易成本、停牌、涨跌停处理过于乐观。
- 市场风格切换导致因子失效。

## 22. MVP 验收标准

阶段 1a 完成标准：

- 可以一键拉取沪深 300 历史成分和基础行情数据。
- 可以保存原始数据和处理后数据。
- 可以按 `as_of_date` 构造当时可见的数据集。
- 可以计算基础财务、估值、动量因子和风险相关字段。
- 每个因子都有数据字典和计算公式。
- 可以输出单因子 IC、分组收益、衰减曲线。
- 可以生成 Markdown 和 CSV 因子验证报告。
- 可以输出某一天的候选研究清单。
- 每只候选股票都有入选原因和风险提示。
- 同一数据快照和配置重复运行，结果一致。

阶段 1b 完成标准：

- 可以运行 Top N 等权组合回测。
- 可以处理停牌、涨跌停、退市和交易成本。
- 可以输出收益、超额收益、回撤、波动率、换手率。
- 可以生成回测报告。
- 所有回测假设集中记录。

阶段 2 完成标准：

- 可以拉取并保存公告原文。
- 可以按规则筛选关键公告。
- 可以调用 LLM 输出结构化 JSON。
- 每个 LLM 结论都有原文证据。
- 系统能校验 JSON Schema。
- 系统能计算解析置信度。
- LLM 输出暂不直接进入总分，除非通过事件研究验证。

最终验收原则：

```text
任何候选股票，都能回答：
  为什么进入候选池？
  用了哪些数据？
  数据在当时是否已经可见？
  哪些因子贡献最大？
  有哪些风险？
  相关因子的历史验证表现如何？
  本次报告能否复现？
```
