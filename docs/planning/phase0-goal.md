# Phase 0 Goal: ashare-research-lab Skeleton

根据 `/Users/crazy/own_project/ashare-research-lab/docs/planning/a-share-research-plan.md` 开始实现项目。

目标不是一次做完整系统，而是完成 Phase 0：初始化 `ashare-research-lab` 仓库骨架，并保证环境、CLI、schema、测试都能跑通。

## 工作目录

- 在 `/Users/crazy/own_project` 下新建目录 `ashare-research-lab`。
- 进入该目录后执行 `git init`。
- Phase 0 完成后创建一次 commit，提交信息为：`feat: phase 0 skeleton`。

## 项目命名

- Git 仓库目录名：`ashare-research-lab`
- Conda 环境名：`ashare-research-lab`
- Python 包名：`ashare`
- CLI 命令名：`ashare`

## 环境要求

1. 使用 Conda 管理环境。
2. 创建 `environment.yml`，Python 版本 3.12。
3. `environment.yml` 以 plan 第 17 节为基础，并额外加入 `ruff`、`mypy`、`hatchling`。
4. 所有 Python 命令必须在 `ashare-research-lab` 环境中执行。
5. 不使用系统 Python 直接运行项目脚本。
6. 不实现真实 AkShare 抓取、真实回测或 LLM 调用。

## pyproject.toml 要求

1. 使用 `hatchling` 作为 build backend：

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```

2. 使用 `src` layout。
3. 配置 wheel 包路径：

```toml
[tool.hatch.build.targets.wheel]
packages = ["src/ashare"]
```

4. 配置 CLI entrypoint：

```toml
[project.scripts]
ashare = "ashare.cli:app"
```

5. 配置 `ruff`：
   - `line-length = 100`
   - `target-version = "py312"`
6. 配置 `mypy`：
   - `strict = false` 起步。

## 目录结构

按 plan 第 5 节创建目录和文件，包括：

- `configs/`
- `data/raw/`
- `data/processed/`
- `data/reports/`
- `data/snapshots/`
- `docs/`
- `src/ashare/`
- `tests/`
- `environment.yml`
- `pyproject.toml`
- `README.md`

## .gitignore

创建 `.gitignore`，至少忽略：

```gitignore
data/raw/
data/processed/
data/snapshots/
*.duckdb
__pycache__/
.pytest_cache/
.mypy_cache/
.ruff_cache/
.venv/
.DS_Store
```

## 配置文件

1. 已在 plan 第 17 节给出样例的文件，尽量逐字复制：
   - `environment.yml`
   - `configs/universe.yaml`
   - `configs/data.yaml`
   - `configs/factors.yaml`
   - `configs/backtest.yaml`
   - `configs/llm.yaml`
2. plan 中没有完整样例的文件先创建骨架，并加 TODO 注释：
   - `configs/data_dictionary.yaml`
   - `configs/validation.yaml`
   - `configs/scoring.yaml`

## CLI 要求

1. 创建 `src/ashare/cli.py`，使用 `typer`。
2. 实现以下 7 个命令空壳：
   - `ingest`
   - `validate-factors`
   - `event-study`
   - `scan`
   - `backtest`
   - `report`
   - `stock-report`
3. 命令先只打印参数和 TODO，不实现真实业务。
4. Python 函数名使用下划线，例如 `validate_factors`、`event_study`、`stock_report`。
5. 必须通过 `@app.command(name="validate-factors")` 这种方式显式声明 CLI 名，确保命令名稳定，不依赖 Typer 自动转换。

## schema.sql 要求

1. 创建 `storage/schema.sql` 或 `src/ashare/storage/schema.sql`，按项目结构选择其一并保持一致。
2. `schema.sql` 必须是可在 DuckDB 中直接执行的 DDL，不是伪代码。
3. 包含 plan 第 6 节的数据表：
   - `trading_calendar`
   - `securities`
   - `industry_classifications`
   - `universe_members`
   - `daily_prices`
   - `st_status`
   - `fundamental_reports`
   - `valuation_daily`
   - `announcements`
   - `risk_events`
   - `factor_values`
   - `research_runs`
4. 使用合理 DuckDB 类型：
   - `stock_code VARCHAR`
   - `trade_date DATE`
   - `publish_time TIMESTAMP`
   - `effective_date DATE`
   - `payload_json JSON`
   - `*_at TIMESTAMP`
5. Phase 0 不要求建索引或外键。
6. `risk_events.payload_json` 使用 DuckDB `JSON` 类型。

## README 要求

`README.md` 不要重复 plan 内容，只写：

1. 项目名一句话说明。
2. Quick Start 三行：
   - `conda env create -f environment.yml`
   - `conda activate ashare-research-lab`
   - `pytest -q`
3. 指向计划文档：`docs/planning/a-share-research-plan.md`

## docs 要求

创建这些文件的初始内容：

- `docs/backtest_assumptions.md`
- `docs/factor_definitions.md`
- `docs/data_dictionary.md`
- `docs/build_data_dictionary.py`

其中 `docs/data_dictionary.md` 说明它是从 YAML 自动生成的产物，不应手写维护。

## 测试要求

创建最小 pytest 测试，至少验证：

1. `ashare` CLI 可以导入。
2. Typer app 存在。
3. 7 个 CLI 子命令可以通过 `ashare --help` 看到。
4. `configs` 目录下要求的配置文件都存在。
5. `schema.sql` 存在。
6. `schema.sql` 可以被 DuckDB 执行。

## Phase 0 硬验收标准

以下命令必须全部成功，任何一条失败都要修到通过：

```bash
conda env create -f environment.yml
conda run -n ashare-research-lab python -m pip install -e .
conda run -n ashare-research-lab ashare --help
conda run -n ashare-research-lab pytest -q
```

`ashare --help` 必须能列出全部 7 个子命令：

- `ingest`
- `validate-factors`
- `event-study`
- `scan`
- `backtest`
- `report`
- `stock-report`

## 完成后

1. 运行 `git status`，确认只包含本次 Phase 0 相关文件。
2. 执行 `git add .`。
3. 执行 `git commit -m "feat: phase 0 skeleton"`。
4. 最终回复中说明：
   - 创建了哪些关键文件。
   - 四条硬验收命令是否全部通过。
   - commit hash。
   - 下一步建议。
   - 如果发现 plan 有缺口，按最保守方式落地，并在最终说明中列出。

## 不要实现

- 真实数据抓取。
- AkShare 调用。
- 因子计算。
- 回测逻辑。
- LLM 调用。
- Web 服务。
