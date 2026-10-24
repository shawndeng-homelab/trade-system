# 蒙特卡洛合成行情数据源

此数据源为后续策略压力测试生成可复现的股票日线、期权报价和到期结算数据。SPY、QQQ 是默认示例标的，金融参数均由配置显式提供；示例中的初始价格 100 是标准化实验价格，不是历史行情或当前市价。

## 安装与快速使用

在仓库根目录执行：

```bash
uv sync --all-packages --group dev
just sim-help
just sim-generate
just sim-validate
just sim-inspect
```

CLI 使用 Click 解析参数，由 rich-click 提供青色选项、中文面板及格式化错误，支持 `-h` / `--help`。成功结果仍为无样式的 JSON，帮助和错误显示不会混入业务结果；用法错误退出码为 2，数据源执行错误退出码为 1。

常用命令已固化到仓库根目录的 `justfile`，`just --list` 可查看中文说明：

| 命令 | 默认行为 |
|---|---|
| `just sim-help` | 显示主 CLI 帮助 |
| `just sim-generate [config] [output]` | 使用 `baseline.json` 生成到 `.tmp/simulations/baseline` |
| `just sim-resume [config] [output]` | 使用相同配置恢复同一数据集 |
| `just sim-validate [input]` | 校验默认基线数据集 |
| `just sim-inspect [input]` | 查看默认基线数据集清单 |
| `just sim-benchmark [config] [output] [paths]` | 基线配置、输出到 `.tmp/simulations/benchmark`、1 条路径 |
| `just sim-test` | 运行数据源及 CLI 回归测试 |

可按位置覆盖参数，含空格的路径需作为一个参数传入：

```bash
just sim-generate examples/simulation/combined.json '.tmp/simulations/combined run'
just sim-validate '.tmp/simulations/combined run'
just sim-inspect '.tmp/simulations/combined run'
```

just 命令在内部调用 `uv run`。直接使用 CLI 的等价示例：

```bash
uv run --package options-strategies simulate-market generate \
  --config examples/simulation/baseline.json --output .tmp/simulations/baseline
```

现有包依赖 `psycopg2`，从源码安装时需要 PostgreSQL 开发工具提供 `pg_config`。如果本机仅验证合成数据功能，可以用 `uv sync --all-packages --group dev --no-install-package psycopg2` 安装，再通过 `.venv/bin/simulate-market` 和 `.venv/bin/python` 执行；或使用 `UV_NO_SYNC=1 just sim-help` 等命令复用已安装环境，此方式不验证数据库功能。

生成命令默认拒绝覆盖已有目录。中断后使用同一配置恢复：

```bash
just sim-resume
```

生成与恢复会逐路径提交。已完成路径先验证后跳过，未完成路径从头重建。配置、生成器实现或相关软件版本发生变化时，必须创建新数据集。操作系统写入锁防止同一个数据集被同时写入，进程退出后自动释放。

CLI 迁移也会改变当前按全部数据源模块计算的源码摘要。旧版本数据仍可读取、查看和校验；恢复生成需要匹配原生成器版本，否则使用新输出目录。

## Python 接口

```python
from pathlib import Path

from options_strategies.simulation import MonteCarloSource
from options_strategies.simulation import SimulationConfig
from options_strategies.simulation import SimulationDataset

config = SimulationConfig.model_validate_json(
    Path("examples/simulation/baseline.json").read_text(encoding="utf-8")
)
source = MonteCarloSource(config)

# 小数据：整条路径载入内存。
market = source.generate_path(path_id=0)
options_df, stock_df = market.for_symbol("SPY")

# 多路径：逐交易日块写入，不在内存累计期权历史。
dataset = source.generate_to(".tmp/simulations/python-run", path_ids=range(3))

# 离线打开；load_path 会校验文件和业务覆盖。
dataset = SimulationDataset.open(".tmp/simulations/python-run")
market = dataset.load_path(path_id=1)

# 大数据：逐片读取，消费后释放。
for options in dataset.iter_table(path_id=1, table="options"):
    print(len(options))
```

`market` 提供 `stock`、`options`、`contracts`、`settlements` 四张表和 `metadata`。`for_symbol()` 返回独立副本，删除内部 `path_id`、`contract_id`，保留现有策略需要的列。修改返回表不会影响原数据。

`generate_path()`、`load_path()` 会把整条路径放入内存。生产批量生成使用 `generate_to()`；消费大规模期权链使用 `iter_table()`。该迭代接口检查分片结构和摘要，完整的跨表覆盖检查使用 `validate()`。

QuantLib 使用全局估值日期，因此定价上下文禁止并发或交错使用。消费完或显式 `close()` 当前 `iter_batches()` 生成器后，再开始下一次生成；上下文结束或报错都会恢复原估值日期。

## 配置与单位

配置使用 JSON，拒绝未知字段、NaN 和 Infinity。所有日期使用 `YYYY-MM-DD`，区间包含首尾交易日；首尾可以是休市日，但区间内必须至少有一个交易日。

| 配置 | 含义和默认值 |
|---|---|
| `schema_version` | 配置版本，当前为 1 |
| `start_date`、`end_date` | 必填模拟范围 |
| `symbols` | 按显式顺序定义标的；该顺序对应相关矩阵 |
| `initial_price` | 必填初始价格，每份标的的美元价格 |
| `mu` | 必填实际市场年化收益率，连续复利漂移参数 |
| `realized_volatility` | 必填实际年化波动率，可为 0 |
| `implied_volatility` | 必填定价年化 IV，必须大于 0 |
| `strike_step`、`multiplier` | 行权价步长默认 $5，合约乘数默认 100 |
| `correlation` | 必填相关矩阵，必须对称、半正定、对角线为 1 |
| `pricing.risk_free_rate` | 必填连续复利年化利率，与 `mu` 独立 |
| `pricing.time_grid`、`price_grid` | 默认 200 × 400 |
| `pricing.damping_steps` | 默认 2 |
| `pricing.max_refinements` | 默认最多加密 2 次，每次将两方向网格数加倍 |
| `chain.weekly_expirations` | 默认未来 8 个有效周五到期日 |
| `chain.monthly_expirations` | 默认未来 24 个有效第三周五到期日 |
| `chain.strike_lower`、`strike_upper` | 默认每天补充现价 50%—150% 内的行权价格点 |
| `quotes.minimum_spread` | 默认 $0.10，全价差下限 |
| `quotes.relative_spread` | 默认理论价格的 2%，全价差比例 |
| `quotes.tick_size` | 默认 $0.01 |
| `seed`、`n_paths` | 默认主种子 42、生成 1 条路径 |
| `chunk_sessions` | 默认每 5 个交易日写一个块 |
| `cash_dividends` | 首版只接受空列表 |

收益率和波动率均使用小数，例如 `0.2` 表示年化 20%。默认示例未做真实市场校准。`baseline.json` 为快速体验主动缩小了期权链；省略 `chain` 即使用上表的完整默认链。

## 路径和合约规则

股票路径使用相关 GBM 的精确离散子步。交易日历为 QuantLib 的美国 NYSE 日历，时间按实际日数除以 365 计算，与定价的 `Actual365Fixed` 保持一致。

第一个交易日的 OHLC 都等于初始价格。后续每个交易日以前一日收盘价为基准，先应用开盘冲击，再用固定 16 个相关随机子步生成收盘价和 OHLC。子步极值是日线生成模型的离散极值，不代表真实连续时间最高价/最低价；周末波动合并至下个交易日，不单独校准隔夜跳空。`volume=0` 是明确的占位值，不代表无交易，也不能用于真实流动性滑点模型。

期权合约包含 Call 和 Put。周五或第三周五休市时，到期日向前调整至交易日；重合到期日标记为月度。每个交易日根据当日价格补充行权价，不读取未来行情。已上市合约即使在冲击后远离现价，也持续报价到到期前最后一个交易日。到期日收盘按内在价值写入结算表；该表不混入可成交报价。

模拟结束时仍未到期的合约不会自动平仓，也不会补造未来行情。真实日内 0DTE、指派、ETF 交割和资金约束由后续执行层负责。

## 期权定价与报价

生产定价统一使用 QuantLib 的美式有限差分引擎。首版分红为零，每个标的当日采用一个横截面固定 IV。实际波动率决定市场路径，IV 决定期权报价，两者互不替代。

输出包含理论价格、Delta、Gamma、`pricing_refinement` 和 `greeks_method`。Delta/Gamma 为保持 IV 不变时对现价的一阶/二阶导数；Put Delta 为负。期权价格和 Greeks 均按每份标的计算，合约金额由消费者乘以 `multiplier`。

定价先验证价格边界、Delta 范围和 Gamma 的数值容差。原生 Greeks 越界时，以现价 ±0.25% 的同一 PDE 价格进行中心差分复核；仍越界则加密网格重算。仍失败则停止该路径，异常包含路径编号、日期、合约身份，并通过异常链保留原始原因。不会切换定价模型、静默丢行或裁剪错误 Greeks。`pricing_refinement=0` 表示原网格，1/2 表示网格各加密 2/4 倍；`greeks_method` 为 `native` 或 `central_difference`。

报价公式为：

```text
全价差 = max(minimum_spread, theoretical_price × relative_spread) × spread_multiplier
bid = max(0, theoretical_price − 全价差 / 2)，按 tick 向下取整
ask = theoretical_price + 全价差 / 2，按 tick 向上取整
```

接近零的价格可能被零 bid 截断，所以报价中点不一定等于理论价格。期权 `volume` 和 `open_interest` 不做虚构，首版不生成这两列。

## 注入压力事件

仓库提供 `crash.json`、`iv-spike.json`、`wide-spread.json` 和 `combined.json`，它们与基线保持相同种子。参数仅用于演示，不对应实际事件概率。

一次性价格冲击：

```json
{"kind": "price_shock", "date": "2024-01-16", "symbols": ["SPY", "QQQ"], "factor": 0.7}
```

在指定日开盘将价格乘以 0.7，此后从新价格继续演化。首日是价格锚点，不允许首日价格冲击。

区间参数覆盖：

```json
{
  "kind": "parameter_override",
  "start_date": "2024-01-16",
  "end_date": "2024-01-19",
  "symbols": ["SPY", "QQQ"],
  "implied_volatility": 0.5,
  "spread_multiplier": 3.0
}
```

还可以覆盖 `realized_volatility`。覆盖区间包含首尾日期，结束后恢复基线。事件日期必须是模拟范围内的交易日；不自动移动无效日期。同一标的同一参数的覆盖不得重叠；不同参数可以同步覆盖。处理顺序是开盘价格冲击、当日参数、随机路径、期权定价及报价。

基线和冲击情景使用相同的底层随机创新。路径采用 `PCG64/SeedSequence([seed, path_id, 0])`，不会影响 NumPy 全局随机状态。路径编号、批量生成顺序和分片大小不改变同一路径的数值。

## 文件结构与验证

```text
manifest.json
path-00000000/
    stock-000000.parquet
    options-000000.parquet
    contracts-000000.parquet
    settlements-000000.parquet
    ...
```

四张表都带有 `path_id`；合约相关表使用稳定的 `contract_id`。日期列为无时区的 `datetime64[ns]` 交易日标签，非真实撮合时间戳。字符串统一为 object，价格和 Greeks 为 float64，编号、乘数、网格级别和成交量占位值为 int64。空表同样保留完整类型。

| 表 | 主要内容 |
|---|---|
| `stock` | 标的、日期、OHLC、成交量占位值、当日实际波动率/IV/价差倍数/价格冲击倍数 |
| `options` | 合约身份、日期、现价、IV、理论价格、Delta、Gamma、bid/ask、网格加密级别 |
| `contracts` | 上市日期、到期日、行权价、Call/Put、月度/周度标记、合约乘数 |
| `settlements` | 到期日收盘现价及每份标的的内在价值 |

清单记录完整配置及其摘要、软件版本、生成器源码摘要、随机算法、逐片 SHA-256、行数和路径状态。生成完成前执行结构、数值及跨表检查，包括交易日覆盖、期权现价与股票收盘价一致、IV 与事件配置一致、存续合约连续报价及到期结算完整性。

同一软件环境内保证数值复现；文件分片方式改变时不保证 Parquet 字节摘要相同。跨平台或依赖版本变化时不承诺逐位相同，需要按数值容差验证。

## 性能与扩展

已完成的三版本测试、全年完整链及随机市场实测见[首版验收记录](simulation-validation.md)。

```bash
just sim-benchmark examples/simulation/annual-flat.json .tmp/simulations/annual-benchmark 3
```

性能脚本同样使用 Click 和 rich-click，可通过 `uv run --package options-strategies python scripts/benchmark_simulation.py --help` 查看参数。脚本记录生成与完整校验的耗时、峰值 RSS、报价行数、实际 PDE 求解次数、精确缓存命中数及落盘大小。每条路径完成时输出检查点，结束后保存 `benchmark.json`。

`annual-flat.json` 使用一个完整交易年、SPY/QQQ、默认完整合约链和默认定价网格，但实际波动率与漂移为零、两标的 IV 相同，用于检验全年生命周期、存储和多路径内存。这是缓存友好的固定市场基准，不能用其耗时推断随机市场吞吐量。另使用 `baseline.json` 测量非零波动率场景。

定价器缓存最多 65,536 组完全相同的输入。零分红、固定利率、固定 IV 及 Actual365Fixed 下，相同剩余天数和其他相同输入可复用结果；缓存不量化现价或 IV，不插值，也不会改变理论价格。随机行情通常缓存命中率较低，完整链计算量较大。

后续扩展按需要增加 IV 偏斜和期限结构、随机波动率、相关性冲击、离散分红、分钟时钟及执行层。扩展时必须更新生成器或数据版本，避免与既有数据集混合。
