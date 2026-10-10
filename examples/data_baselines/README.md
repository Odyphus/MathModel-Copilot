# 原创合成数据与算法验收例

在新目录运行：

```bash
python examples/data_baselines/run_example.py --workspace <new-empty-project>
```

需要 `analysis` extra。脚本生成原始 CSV 与解释文件，规范化并读回，登记题意/模型/参数/数据/代码/检查计划，真实执行 LP 与回归，独立检查并覆盖两个要求，再改一个参数验证失效与重新计算。所有文件留在指定项目目录；不覆盖已有文件，不自动提交比赛或上传数据。

- Q1：144 槽平均 60 kW、每槽 10 分钟，总能量 1440 kWh；只演示三个供应商的**总量采购**，并非逐槽调度或储能模型。容量各 600 kWh、价格 2/3/4 时费用 3960；首价改 2.5 后为 4260，旧 Run/Result 必须失效。
- Q2：合成关系 `y=1+2x`，前四行训练、后两行测试；解析预测 9/11，训练目标均值基线为 4、测试 MAE 为 6。浮点拟合误差允许 `1e-7`；此例不声明真实预测性能。

`example-report.json` 可查看最新对象 ID、指标和范围；`state/decision_log.json` 是唯一建模权威；`.copilot/runs/` 保存实际输入、上下文、stdout/stderr、receipt 与输出，独立检查回执同样保留。正常结尾应为 2/2 需求 verified，但正式 submission.ready 为 false。

独立 checker 不导入适配器或 starter：Q1 重新核对槽位和能量，算约束和解析最优下界；Q2 直接用解析关系及逐行误差/均值计算。历史结果、源文件与新版本都保留，可用于排查数字为什么变化。
