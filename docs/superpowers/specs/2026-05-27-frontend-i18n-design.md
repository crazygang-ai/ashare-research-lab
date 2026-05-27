# Frontend I18n Design

## Summary

为 `frontend` 增加轻量中英文 UI 文案切换能力。默认语言为简体中文，English 作为可切换选项保留。实现范围只覆盖前端 UI copy 和前端测试，不翻译后端返回的研究内容、命令、日志、字段名或产物路径。

## Goals

- 默认展示简体中文 UI，降低 A 股研究流程中英文术语的理解门槛。
- 在全局 shell 中提供 `中文 / English` 切换入口。
- 语言选择保存在 `localStorage`，刷新后保持用户选择。
- 保留英文 UI 文案，便于继续对照原有界面和技术术语。
- 将 UI 文案集中管理，避免硬编码散落在页面和组件里。

## Non-Goals

- 不修改 backend API、CLI、DuckDB schema、报告生成逻辑或研究计算逻辑。
- 不翻译后端返回的 Markdown 报告正文、CSV 字段、表格原始字段名、日志、`command_preview`、`run_id`、`source_run_id`、factor name、artifact id、artifact path。
- 不引入自动翻译服务或 LLM 翻译。
- 不新增重量级 i18n 依赖，除非现有前端结构无法满足基本切换需求。

## UX Behavior

语言切换控件放在 `AppShell` header，使用紧凑 segmented control 或等价按钮组，选项为 `中文` 和 `English`。首次打开时使用中文；如果 `localStorage` 中已有有效语言，则使用保存值。

切换语言时，导航、页面标题、按钮、表单 label、空状态、加载提示、错误提示和前端自定义 status badge 立即更新。当前路由、表单输入、查询数据和报告内容不重置。

## Architecture

新增前端本地 i18n 层：

- `frontend/src/i18n/translations.ts` 定义 `zh` 和 `en` 文案字典。
- `frontend/src/i18n/I18nProvider.tsx` 提供当前语言、切换函数和 `t(key)`。
- `frontend/src/i18n/useI18n.ts` 或同文件导出 hook，供页面和组件读取文案。

`t(key)` 只服务前端 UI 文案。缺失 key 在开发期应回退到 key 字符串，避免页面崩溃；测试覆盖主要入口，降低遗漏风险。

## Translation Boundary

需要翻译的内容：

- Navigation：Today、Stocks、Reports、Runs、Artifacts、Settings。
- 页面 UI：标题、副标题、按钮、fieldset label、tab label、section title。
- 通用状态：Loading、empty state、report unavailable、no rows、no artifacts、no steps、no command。
- 前端枚举状态：`available`、`missing`、`runner enabled`、`runner disabled`、`scan available`、`scan missing`、`score available`、`score missing`。

保持原文的内容：

- Markdown report body。
- API 返回的 rows、field keys、CSV-derived columns。
- Commands、logs、IDs、paths、factor names、source tags。
- 任何研究输出中的 candidate、score、backtest 解释文本。

## Testing

采用 TDD：

1. 先更新前端测试，断言默认中文导航和 `Settings` 页面中文标题，确认测试失败。
2. 实现 i18n provider 和中文默认文案，确认测试通过。
3. 增加语言切换测试，确认切到 English 后导航或页面标题恢复英文。
4. 增加持久化测试，确认保存的 English 会在重新渲染时生效。

实现后运行：

```bash
cd frontend && npm run test
cd frontend && npm run build
```

## Acceptance Criteria

- 新用户首次打开 UI 时默认看到中文导航和主要页面文案。
- 用户可以从全局 header 切换到 English。
- 刷新后保留最近一次语言选择。
- 报告正文、日志、命令预览、数据字段和研究产物内容保持后端原样。
- 前端测试覆盖默认中文、英文切换和语言持久化。
- `frontend` 测试和 build 通过。
