# 滚动预测：先核对当时知道什么，再比较误差

适用于规则时间轴上、明确观测和发布时间的单变量预测。最小候选为滞后线性回归或固定正则系数的 Ridge，与同一批窗口的“最后已发布值”基线比较。依赖 numpy、scikit-learn；标准化仅在该起点可用的训练样本中拟合。

## 数据与策略声明

`forecast_spec.json` 使用 [完整示例](../../templates/copilot/forecast_spec.json)。每一行明确 `time`（观测时点）、`available_at`（当时何时能知道这个值）及有限 `value`；时点必须含时区，发布时间不得早于观测。频率、起点、预测步数、滞后特征、训练窗口、最小训练量、模型、标准化、正则系数、评价截至时点及 `development/final_holdout` 均须显式填写。未知字段、缺槽或重复槽报错，不补零或悄悄跳过窗口。

历史训练样本的标签须在本次起点之前已发布，特征须在该历史决策时点已发布。当前预测特征也必须已发布。未来真值只用于指定截至时点的评价；留出窗口的声明不能证明人没有反复用它选参数，仍须保留团队的选择记录。

## 本地调用与接回项目

```text
python scripts/copilot.py --workspace <项目目录> forecast run --spec forecast_spec.json --output results/backtest.json
python scripts/copilot.py --workspace <项目目录> forecast replay --spec forecast_spec.json --output results/backtest.json
```

报告保留全部起点×步数实例、标签和特征的发布时间、训练样本、训练内均值、基线、逐步数及总体 MAE/RMSE。重叠目标时间仍按每个预测实例计算，不能冒充互不重叠的独立样本。同实现重放只查复算与漂移，不自动生成 verified Result；正式使用须纳入 CodeManifest、真实 Run 和预先登记的独立 checker。

原创 [合成链路](../../examples/forecast_paper/README.md) 用已知直线和独立标准库核算检验发布时间、窗口、误差与训练均值，不代表真实预测精度。当前版本没有自动调参、任意外生特征、概率区间或通用鲁棒优化算子。

设计参考：[TimeSeriesSplit](https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.TimeSeriesSplit.html)、[scikit-learn 数据泄漏与预处理说明](https://scikit-learn.org/stable/common_pitfalls.html)，核对日期 2026-10-09。此实现额外检查发布时点；仅按行号切分不能代替发布时间检查。
