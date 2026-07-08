# Project Log

按日期倒序记录每次较大改动的大概内容。每条保持简短，便于之后回看项目演进。

## 2026-07-08

### 调整执行台默认日期

- 改动概要：执行台日期输入不再写死历史日期，页面加载时默认结束日期为当天、开始日期为一年前，并同步命令预览。
- 验证：运行 `node --check ui/app.js`、`python -m pytest tests/test_output_summary.py tests/test_web_history.py tests/test_weights.py`、`./scripts/check.ps1`，并用 Web UI 确认默认区间为 `2025-07-08` 至 `2026-07-08`。
- 提交：本次提交。


### 修复执行台曲线展示区间

- 改动概要：执行台权益曲线改为按 AKQuant 权益金额自动缩放，仓位曲线改为返回本次回测全区间数据；补充摘要回归测试。
- 验证：运行 `python -m pytest tests/test_output_summary.py tests/test_web_history.py`、`node --check ui/app.js`、`./scripts/check.ps1`，并用 Web UI 跑 `H/A 溢价年线过滤` 的 `2024-07-02` 至 `2026-07-02` 缓存回测确认两条曲线显示正常。
- 提交：本次提交。


### 将启动脚本切换到默认 Python 3.11

- 改动概要：Web UI 启动脚本和统一校验脚本默认使用系统 `python`，启动前校验必须为 Python 3.11；README 和前端命令示例同步去掉 `.venv` 强依赖。
- 验证：运行 `python --version`、`py -3.11 --version`、`python -X utf8 -m pip install -e . pytest` 和 `./scripts/check.ps1`。
- 提交：本次提交。

## 2026-07-07

### 删除行业资金流比价龙头 MVP 策略

- 改动概要：移除 `sector-flow-relative-strength` 策略注册、策略实现目录、专用数据 helper、结果文件白名单和相关测试；项目恢复为仅保留两套 H/A 溢价策略。
- 验证：运行 `./scripts/check.ps1`。
- 提交：本次提交。


### 新增数据源预检查保护

- 改动概要：新增策略级 `preflight` 钩子，CLI 和 Web 在创建输出目录前执行预检查；行业资金流策略会先检查行业列表、行业资金流、行业行情和成分股接口，失败时不创建新的回测输出目录。
- 验证：运行 `./scripts/check.ps1`，并用 `data/preflight_probe` 验证数据源失败时目录未创建。
- 提交：本次提交。

### 加固行业资金流策略中文列名测试

- 改动概要：将新策略中 AKShare 中文列名匹配改为 Unicode 转义，补充真实中文列名归一化测试，并让策略显示名、报告标题和说明文档在不同终端编码下更稳定。
- 验证：运行 `./scripts/check.ps1`。
- 提交：本次提交。

### 新增行业资金流比价龙头 MVP 策略

- 改动概要：新增 `sector-flow-relative-strength` 策略，按行业资金流改善和行业相对强弱选板块，再按个股相对板块强弱和量能选龙头；补充通用 A 股行情拉取、结果文件清单和相关单元测试。
- 验证：运行 `./scripts/check.ps1`。
- 提交：本次提交。

## 2026-07-06

### 固定执行台概览曲线纵轴范围

- 改动概要：执行台概览中的权益曲线和仓位曲线都固定使用 `0.00` 到 `1.00` 的纵轴范围，显式上下界不再被自动留白扩展。
- 验证：运行 `node --check ui/app.js` 和 `./scripts/check.ps1`。
- 提交：本次提交。

### 新增项目记录文档

- 改动概要：新增 `PROJECT_LOG.md`，作为项目级变更记录；更新协作约定，要求后续大改提交前同步记录本次改动。
- 验证：检查文档内容和 git diff。
- 提交：本次提交。

### 调整交付格式

- 改动概要：从固定交付格式中移除 `服务地址` 字段，只在本地服务地址对用户有用时单独说明。
- 验证：检查 README 和 AGENTS 中的交付字段说明。
- 提交：`7989914 docs: remove service address from delivery note`

### 新增交付流程约定

- 改动概要：新增仓库协作指南，固定大改按“实现 -> 验证 -> 提交 -> 简短记录”收尾，并在 README 中加入入口。
- 验证：检查 README 和 AGENTS 的文档内容。
- 提交：`273e70b docs: add delivery workflow`
