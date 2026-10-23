# PMCC 评估口径

评估流程将当前 PMCC 模拟结果与使用**完全相同 LEAPS 实际成交记录**的对照组合、零收益现金对照及独立的标的价格参考进行比较。目前不包含逐日盯市估值、购买力约束或 PMCC 长短腿联动。

## 使用缓存数据运行

```bash
uv run --all-packages python scripts/evaluate_pmcc.py --symbol SPY --capital 100000
```

交互式使用请打开 `scripts/evaluate_pmcc.ipynb`。数据仅加载一次，PMCC 仅模拟一次。现有 `run_pmcc` 和报告 API 仍可使用。

```python
from options_strategies import PmccConfig, EvaluationConfig, evaluate_pmcc
from options_strategies.shared import load_pmcc_data
from backtest_charts import BacktestReport

config = PmccConfig(symbol="SPY", capital=100_000)
options, stock = load_pmcc_data(config.symbol)
evaluation = evaluate_pmcc(options, stock, config, EvaluationConfig())
report = BacktestReport.from_evaluation(evaluation, scope="full")
report.plot_dashboard()
report.plot_segments(kind="segment")  # 也支持 year 和 quarter
```

`build_pmcc_evaluation(result, stock, config)` 可直接评估已有结果，无须重新回测。评估区间必须包含所有已完成交易。与 `evaluate_pmcc` 不同，它无法核验期权数据覆盖范围；已知覆盖范围时，应传入 `start` 和 `end`。

## 对照基准与计量单位

- **LEAPS-only（仅持有 LEAPS）：** 合约、数量和开平仓日期均与 PMCC 的长期看涨期权腿相同。两者使用相同的账户初始资金；省下的短腿资金不会重新用于增持 LEAPS。
- **现金：** 账户资金保持不变，不代表历史短期利率收益。
- **标的股票：** 使用归一化收盘价作为参考，未核验股息再投资总回报。单独展示，不与已实现期权权益进行风险排名。
- `incremental_vs_leaps` 为同一区间、同一成本情景下 PMCC 净盈亏减去 LEAPS-only 净盈亏，表示固定成交记录下卖出 Call 的净贡献，不代表长短腿联动执行模型下的因果效应。
- 收益率以账户资金为基准，不以期权权利金或分配给单腿的资金为基准。回撤计算包含初始资金。年化收益率使用实际日历天数；无法定义的值保留为空。

## 固定成交记录下的成本

| 情景 | 每张合约每次成交手续费 | 每股每次成交的不利价格变动 |
|---|---:|---:|
| ideal（理想） | 0 美元 | 0 美元 |
| reference（参考） | 0.65 美元 | 0.01 美元 |
| stress（压力） | 1.30 美元 | 0.05 美元 |

这些是可配置的研究假设，不是券商报价。`CostScenario` 和 `EvaluationConfig` 会校验成本为有限非负数，且情景名称唯一。`primary_scenario` 默认为 `reference`。

手续费 = 合约张数 × 每张手续费。滑点成本 = 合约张数 × 合约乘数 × 每股不利价格变动。开仓与平仓分别在对应事件日期计费，毛盈亏在平仓日确认。不会假定上游费用字段已经扣费：输入必须是现有 PMCC 引擎的毛盈亏结果，不能传入外部已扣费的交易记录，以免重复扣费。

手续费和滑点**不会**改变选约、退出或购买力。权益为负时会标记异常，不隐藏或截断；这不代表交易在资金约束下可执行。引擎仅返回已完成交易，无法还原未平仓、被拒绝订单及其费用，也不能将它们视为零成本、零风险。

## 时间区间与数据覆盖

`evaluate_pmcc` 在执行前筛选标的和请求日期，使用股票与期权数据实际覆盖区间的交集。元数据同时保留请求日期和可用覆盖范围，不会延长输入历史以凑齐请求区间。

- `scope="full"`：完整评估区间，包含空仓日期和开仓成本。
- `scope="common"`：评估区间与标的价格参考覆盖范围的交集。期初权益包含此前发生的成本，诊断指标按所选区间重新计算。
- 年度和季度区间均裁剪到所选范围，因此可能包含不完整年度或季度。默认另划分三个相邻、互不重叠、日历时长相等的时间段；区间很短时，非空分段数会减少。
- 期间净盈亏为现金事件之和。交易按平仓日期归属期间；交易级统计使用其**完整开平仓周期**净盈亏，包含以前期间发生的成本。这类交易统计不能替代期间现金流总额。
- `top5_profit_share` 为净盈利最高的五笔交易利润之和，除以全部净盈利交易的利润之和。没有盈利交易时为空。已完成交易全部盈利时，最大亏损为零；没有已完成交易时为空。
- LEAPS 周期数仅作为描述性样本数量，不将多笔短 Call 视为统计上相互独立的观测。

时间分段用于描述历史表现，不构成独立样本外验证或参数选择流程。当前基于已实现权益的看板不提供夏普比率和日度风险价值（VaR）。

## 保存与离线复现

```python
from options_strategies import EvaluationResult

evaluation.save(".tmp/evaluations/my-run")  # 必须使用尚不存在的新目录
report.save_html(".tmp/evaluations/my-run/report.html")
report.export_trades(".tmp/evaluations/my-run/trades.csv")
loaded = EvaluationResult.load(".tmp/evaluations/my-run")
BacktestReport.from_evaluation(loaded).plot_dashboard()
```

带版本号的 JSON 保存配置、数据覆盖、依赖版本、Git 提交版本与工作区变更状态，以及输入和源代码哈希。Parquet 保存原始结果、交易、现金事件、权益曲线、汇总和分段数据。读取不执行 pickle，也不需要联网。原始结果恢复为属性兼容对象，而非 optopsy 专用类。原始汇总中的非有限数值转换为 JSON 的 `null`。

HTML 内嵌 Plotly 和全部诊断内容，可离线查看。看板展示最近 50 笔已完成交易；CSV 导出全部已完成交易，包含所选情景下的毛盈亏、手续费、滑点和完整开平仓净盈亏。保存的事件账本包含所有情景的成本。窄屏浏览 HTML 时可横向滚动，避免表格文字被过度缩小。
