# 方法卡：回归与最小基线

**适用：** 用已有观测描述或估计数值目标，先选线性回归作为可解释基线，再按证据比较 Ridge/随机森林。回归拟合本身不证明因果关系，也不自动解决时间序列的未来信息问题。

**入口：** `templates/shared/code_starter/prediction.py` 的 `fit_regression(X_train,y_train,X_test,y_test,model_type,scale=False,random_state=42)`。必须先声明实际 DataSplitPlan；模板接收调用者的训练/测试数组，不猜分组，也不认证它们独立。代码、参数和数据沿用现有 `run/validate` 锁定。

```python
result = fit_regression(
    [[0], [1], [2], [3]], [1, 3, 5, 7],
    [[4], [5]], [9, 11], model_type="linear", scale=True,
)
# 合成解析例 y=1+2*x；测试预测应为 9、11。
# 只用训练目标均值 4 作基线，测试 MAE 为 6。
```

**数据前提：** 同宽二维特征、对应一维目标、至少两行训练和一行测试；缺失或非有限值直接报错。缺值处理须在数据解释与切分中另行说明，不在模板里悄悄补值。

**输出：** 训练/测试 MAE、RMSE、R²，逐行预测，训练目标均值基线及相同测试集下的误差，`mae_improvement_over_baseline`。改善可为负数，工具不会把模型差于基线包装成成功。单条/常量目标的 R² 返回 null 并说明未定义条件，便于 JSON 输出。

`scale=True` 使用 Pipeline，标准化只在训练数据拟合，测试值不改变均值与尺度。交叉验证时必须把 Pipeline 放在每个折内，不能先对全体数据标准化；本轮没有新增自动交叉验证或滚动回测。

**独立 checker：** 按测试行重新计算误差，核对预测与真实值的键/顺序，独立计算训练集均值；有解析合成例时与解析线比较。不要让 checker 重新调用同一拟合函数后把相同错误当作通过。训练得分、测试得分、真实预测和泛化声明分别记录。

**依赖与后续：** 回归依赖 `analysis` extra；ARIMA 按需加载 statsmodels（`advanced` extra），不是回归的强制依赖。时序/重复主体数据须按实际可用信息切分；滚动窗口、预测发布时间与泄漏负例属于后续预测验证阶段。本轮小算例不是真实赛题预测精度评测。

预处理边界依据：[scikit-learn Common pitfalls](https://scikit-learn.org/stable/common_pitfalls.html)。核对日期：2026-10-09。模板增量与合成检查由本项目实现。
