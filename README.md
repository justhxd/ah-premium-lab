# H/A 溢价回测框架

这个项目把 `C:\Users\huxiaodong\Desktop\claude\HA` 里的策略逻辑改造成可回测版本：

- 回测框架：`akfamily/akquant`
- 数据源：AKShare
- 本地缓存：SQLite，默认文件为 data/cache/market_cache.sqlite；缺失区间会自动从 AKShare 拉取并写回缓存
- 股票池：默认使用 `config/ah_pairs_full.csv` 的完整 AH 配对池
- 历史 H/A 溢价：用 A 股历史价、H 股历史价、HKD/CNY 历史汇率逐日重算
- 策略：每个交易日按 H/A溢价率 排序，取前10只，并按其相对 Top30均值 的偏移量分配 A 股目标仓位

重要：一年或多年回测不要使用 `strategy_weights.csv` 作为股票池，因为它只是某个当前时点的正溢价快照。默认命令会使用完整 AH 配对池，让历史上其他曾经正溢价的股票也有机会进入组合。

## Python 版本要求

本项目强制使用 Python 3.11 x64。不要使用系统里旧的 Python 3.9.2rc1；该版本导入 `akquant` 会因为 `python3.dll` 缺少 ABI 符号而 DLL 加载失败。

推荐始终使用项目虚拟环境里的解释器：

```powershell
.\.venv\Scripts\python.exe --version
```

应显示：

```text
Python 3.11.9
```

如需重新创建环境：

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -U pip setuptools wheel
.\.venv\Scripts\python.exe -m pip install -e . pytest
```

## 安装

当前项目已经创建好 `.venv`。后续安装/更新依赖时使用：

```powershell
.\.venv\Scripts\python.exe -m pip install -e . pytest
```

## 构建历史溢价和每日权重

```powershell
.\.venv\Scripts\python.exe -m ha_backtest.cli build-premium --start 20250101 --end 20260702
```

输出：

- `data/ha_premium_history.csv`：完整 AH 池逐日重算后的 H/A 溢价
- `data/target_weights.csv`：每天按 Top30 均值偏移规则生成的目标仓位

也可以显式指定完整配对文件：

```powershell
.\.venv\Scripts\python.exe -m ha_backtest.cli build-premium --pairs config/ah_pairs_full.csv --start 20250101 --end 20260702
```

## 运行 AKQuant 回测

```powershell
.\.venv\Scripts\python.exe -m ha_backtest.cli run --start 20250101 --end 20260702 --initial-cash 1000000
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
.\.venv\Scripts\python.exe -m ha_backtest.cli run --start 20250101 --end 20260702 --integer-percent
```

## 策略公式

```text
H股人民币价格 = H股历史收盘价(HKD) * HKD/CNY
H/A溢价率 = (H股人民币价格 / A股历史收盘价 - 1) * 100

每日按 H/A溢价率 从高到低排序：
Top30均值 = 前30只股票 H/A溢价率的平均值
候选持仓 = 前10只股票对应的 A 股
偏移量 = 候选股票 H/A溢价率 - Top30均值

如果前10只偏移量总和 <= 总仓位上限：
A 股目标权重 = 偏移量 / 100

如果前10只偏移量总和 > 总仓位上限：
A 股目标权重 = 偏移量 / 偏移量总和 * 总仓位上限
```

默认总仓位上限为 100%。当偏移量总和不足 100% 时不强行满仓，剩余资金留现金。策略会把未提及的 A 股持仓清到 0。


## 缓存逻辑

行情和汇率缓存现在使用 SQLite 增量缓存，不再按完整起止区间精确命中 CSV 文件。请求更长回测区间时，会先读取 data/cache/market_cache.sqlite 中已有覆盖范围，只向 AKShare 拉取缺失的前后区间，再合并写回数据库。

如果 SQLite 中没有某个标的或汇率的覆盖区间，会直接向 AKShare 拉取缺失数据并写回 SQLite。--refresh 会强制重新拉取本次请求的完整区间并写回 SQLite。

## 注意

`config/ah_pairs_full.csv` 来自当前可得 AH 配对缓存。如果要做非常长周期或严格研究，仍需要关注历史上市/退市带来的幸存者偏差。



