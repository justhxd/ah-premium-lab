# H/A 溢价回测框架

这个项目把 `C:\Users\huxiaodong\Desktop\claude\HA` 里的策略逻辑改造成可回测版本：

- 回测框架：`akfamily/akquant`
- 数据源：AKShare
- 本地缓存：SQLite，默认文件为 data/cache/market_cache.sqlite；缺失区间会自动从 AKShare 拉取并写回缓存
- 股票池：默认使用 `config/ah_pairs_full.csv` 的完整 AH 配对池
- 历史 H/A 溢价：用 A 股历史价、H 股历史价、HKD/CNY 历史汇率逐日重算
- 策略：提供原始 `ha-premium` 和年线过滤版 `ha-premium-annual-line`；年线过滤版会先按 H/A溢价率 排序取前10只，并按其相对 Top30均值 的偏移量计算目标仓位，再仅对 A 股收盘价高于 250 日均线的标的执行目标仓位

重要：一年或多年回测不要使用 `strategy_weights.csv` 作为股票池，因为它只是某个当前时点的正溢价快照。默认命令会使用完整 AH 配对池，让历史上其他曾经正溢价的股票也有机会进入组合。

## Python 版本要求

本项目强制使用 Python 3.11 x64。不要使用系统里旧的 Python 3.9.2rc1；该版本导入 `akquant` 会因为 `python3.dll` 缺少 ABI 符号而 DLL 加载失败。

涉及 `py` 启动器的命令统一写成 `py -3.11 -X utf8 ...`；项目脚本默认使用 `.venv\Scripts\python.exe -X utf8 ...`，避免 Windows 中文路径、PowerShell 输出编码和默认 `python` 指向不同版本导致的乱码或 ABI 问题。PowerShell 写文本文件时统一显式使用 `-Encoding utf8`。

推荐始终使用项目虚拟环境里的解释器：

```powershell
.\.venv\Scripts\python.exe -X utf8 --version
```

应显示：

```text
Python 3.11.9
```

如需重新创建环境：

```powershell
py -3.11 -X utf8 -m venv .venv
.\.venv\Scripts\python.exe -X utf8 -m pip install -U pip setuptools wheel
.\.venv\Scripts\python.exe -X utf8 -m pip install -e . pytest
```

## 安装

当前项目已经创建好 `.venv`。后续安装/更新依赖时使用：

```powershell
.\.venv\Scripts\python.exe -X utf8 -m pip install -e . pytest
```

## 开发启动

启动本地 Web UI：

```powershell
.\start_web_ui.ps1
```

默认服务地址为 `http://127.0.0.1:8765/`。停止服务：

```powershell
.\stop_web_ui.ps1
```

也可以直接使用 Python 入口指定监听地址：

```powershell
.\.venv\Scripts\python.exe -X utf8 -m ha_backtest.web --host 127.0.0.1 --port 8765
```

## 验证命令

统一验证入口：

```powershell
.\scripts\check.ps1
```

该脚本会依次执行：

- Python 编译检查：`.\.venv\Scripts\python.exe -X utf8 -m compileall -q src tests diagnose_backtest_run.py`
- 单元测试：`.\.venv\Scripts\python.exe -X utf8 -m pytest`
- 前端语法检查：`node --check ui\*.js`
- 关键 API smoke test：临时启动 `ha_backtest.web`，检查 `/api/strategies` 和 `/api/status`

如只想跑静态和单元测试、跳过 API smoke test：

```powershell
.\scripts\check.ps1 -SkipSmoke
```

## 端到端检查

完整本地端到端检查使用：

```powershell
.\scripts\check.ps1
```

脚本默认会在 `http://127.0.0.1:18765/` 临时启动后端做只读 API 检查，完成后自动停止。若端口被占用，可指定其他端口：

```powershell
.\scripts\check.ps1 -SmokePort 18766
```

需要人工检查界面时，先运行 `.\start_web_ui.ps1`，再打开 `http://127.0.0.1:8765/`。

## 常见失败

- `Cannot find Python interpreter`：先按“Python 版本要求”和“安装”章节创建 `.venv` 并安装依赖。
- `Cannot find node`：安装 Node.js 后重跑验证。
- `pytest` 导入 `akquant` 失败：确认正在使用 Python 3.11 x64，不要使用系统旧版 Python 3.9.2rc1。
- API smoke test 超时：确认指定端口未被占用，或改用 `.\scripts\check.ps1 -SmokePort 其他端口`。

## 构建历史溢价和每日权重

```powershell
.\.venv\Scripts\python.exe -X utf8 -m ha_backtest.cli build-premium --start 20250101 --end 20260702
```

输出：

- `data/ha_premium_history.csv`：完整 AH 池逐日重算后的 H/A 溢价
- `data/target_weights.csv`：每天按 Top30 均值偏移规则生成的目标仓位

也可以显式指定完整配对文件：

```powershell
.\.venv\Scripts\python.exe -X utf8 -m ha_backtest.cli build-premium --pairs config/ah_pairs_full.csv --start 20250101 --end 20260702
```

## 运行 AKQuant 回测

```powershell
.\.venv\Scripts\python.exe -X utf8 -m ha_backtest.cli run --start 20250101 --end 20260702 --initial-cash 1000000
```

每次运行都会在 `--output-dir` 指定的根目录下创建一个独立子目录。默认根目录是 `data`，子目录形如：

```text
data/run_20250101_20260702_20260702_170512
```

该目录会保存本次策略的所有输出：

- `akquant_ha_report.html`：本次 AKQuant 回测报告
- `strategy_description.md`：本次策略文字说明和运行参数
- `ha_premium_history.csv`：本次使用的 H/A 溢价历史
- `target_weights.csv`：本次生成的每日目标仓位
- `last_premium_snapshot.csv`：最后一个交易日的溢价快照

默认交易 A 股历史行情，symbol 形如 `SZ300750` / `SH600036`；H 股价格只用于计算 H/A 溢价信号。如需使用整数百分比权重分配，可加：

```powershell
.\.venv\Scripts\python.exe -X utf8 -m ha_backtest.cli run --start 20250101 --end 20260702 --integer-percent
```

## 策略公式

```text
H股人民币价格 = H股历史收盘价(HKD) * HKD/CNY
A股年线 = A股历史收盘价的 250 个交易日移动平均
H/A溢价率 = (H股人民币价格 / A股历史收盘价 - 1) * 100

每日按 H/A溢价率 从高到低排序：
Top30均值 = 前30只股票 H/A溢价率的平均值
候选持仓 = 前10只股票对应的 A 股
偏移量 = 候选股票 H/A溢价率 - Top30均值
`ha-premium-annual-line` 策略只对候选持仓中 A股收盘价 > 250日均线 的标的执行目标仓位；低于、等于或缺少年线的候选标的目标仓位归零，不用后续排名标的补位，也不把仓位重新分配给其他股票。

如果前10只偏移量总和 <= 总仓位上限：
A 股目标权重 = 偏移量 / 100

如果前10只偏移量总和 > 总仓位上限：
A 股目标权重 = 偏移量 / 偏移量总和 * 总仓位上限
```

默认总仓位上限为 100%。当偏移量总和不足 100% 时不强行满仓，剩余资金留现金。策略会把未提及的 A 股持仓清到 0，因此年线过滤版持仓跌破或等于 250 日均线后会在目标权重表中消失并被卖出。

## 策略开发约定

每次新增策略、信号或指标时，先检查 AKShare 官方文档和当前虚拟环境里的 AKShare 函数，优先使用 AKShare 已经提供的原始数据或现成指标；只有 AKShare 没有对应指标、覆盖范围不满足回测要求，或接口只提供当前快照而不提供历史日期时，才在本项目里手工计算，并在代码或文档里写明原因。

本策略的 250 日年线已经核查过 AKShare：官方文档中有同花顺技术选股接口 `stock_rank_xstp_ths(symbol="250日均线")` 和 `stock_rank_xxtp_ths(symbol="250日均线")`，可以返回当前“向上突破/向下突破 250 日均线”的股票列表，但接口没有历史日期参数，不能用于逐日历史回测判断。因此这里继续基于 AKShare 的 A 股历史日线收盘价手工滚动计算 250 个交易日均线。

## 协作交付约定

每次大改按“实现 -> 验证 -> 提交 -> 简短记录”收尾。简短记录固定包含：改了什么、验证命令、下一步。面向 Codex 或其他协作代理的细则见 `AGENTS.md`。

## 缓存逻辑

行情和汇率缓存现在使用 SQLite 增量缓存，不再按完整起止区间精确命中 CSV 文件。请求更长回测区间时，会先读取 data/cache/market_cache.sqlite 中已有覆盖范围，只向 AKShare 拉取缺失的前后区间，再合并写回数据库。

如果 SQLite 中没有某个标的或汇率的覆盖区间，会直接向 AKShare 拉取缺失数据并写回 SQLite。--refresh 会强制重新拉取本次请求的完整区间并写回 SQLite。

## 注意

`config/ah_pairs_full.csv` 来自当前可得 AH 配对缓存。如果要做非常长周期或严格研究，仍需要关注历史上市/退市带来的幸存者偏差。
