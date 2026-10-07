# 2018 B 题：真实运行与证据链演示

这个例子把已有的 2018 B 题复现代码接入 MathModel Copilot Runtime。运行时重新计算所有结果，不读取或复制先前实验结果。它演示审题需求、冻结模型与参数、真实执行、独立复验、证据绑定、论文片段和状态投影之间的关系。

原题是**两项任务、三种工况**。Q1 为建模与算法，Q2 为代入题给三组参数、比较效率并填写附件表格；三种工况不是三个子问。完整例子分别拆为 Q1 的 3 条和 Q2 的 11 条 Requirement。

## 一键重跑

在项目根目录，用具有 `xlrd`、`xlwt` 的 Python 环境运行：

```powershell
$env:PYTHONUTF8 = '1'
python examples/cumcm2018b/run_benchmark.py --workspace ../cumcm2018b-new-run
```

目标目录必须不存在或为空；已有文件不会被覆盖。`--workspace` 可指定任意新的工作目录。仅验证软件集成时可加 `--smoke`，此时只运行第 1 组参数和 2 个种子；报告明确标记为 `smoke`，其余组的结果表保留空白，不能作为完整题目结果。

完整配置执行：

- 三组官方时间参数；每组 254 种固定刀具分配、2 种双工序策略，共 1,524 个候选。
- 12 条代表轨迹，包括单工序/双工序、健康/故障 seed 0 的全部组合。
- 6 组故障对照和 54 组故障概率/维修时间敏感性配置，每配置 32 个种子；保留逐种子件数及统计区间。
- 四份官方格式 XLS 表，共 18 个工作表；独立程序回读并核对每个数值单元格。

算法保留文件 `rgv_simulator.py`、`verify_schedule.py`、`test_rgv.py` 从先前复现证据包原样复制。新增的 `driver.py` 负责读取 Runtime 冻结输入和导出表格，`checker.py` 负责独立运行原验证器并检查候选空间、样本统计和表格内容。原算法的 7 项边界、因果性与故障测试也真实执行。

## 证据路径

每个子问按以下链条执行，Q2 的模型还显式依赖 Q1 的已验证 Result：

`ProblemContract → ModelSpec → ParameterSet/DataContract/CodeManifest/ValidationPlan → RunRecord → ValidationRecord → Result → Claim → PaperSection`

`state/decision_log.json` 是唯一权威。`.copilot/runs/` 包含每次实际执行的输入快照、输出、标准输出/错误及运行回执；`.copilot/checks/` 包含预声明 checker 的复验报告。`results/Q1`、`results/Q2` 是登记在 ArtifactRecord 中的可读副本，不能取代 Claim 绑定的原始运行证据。`benchmark_report.json` 给出对象 ID、覆盖事实、检查计数和状态；`benchmark_report.md` 是可读报告。`source_manifest.json` 保留本次全部源文件哈希及“未复用旧结果”标记。

算法内部每次仿真都调用独立的 `verify_schedule` 后才记录结果；外部 checker 再次独立回放 12 条代表轨迹，核对完整候选及 Monte Carlo 账本、重新计算统计量，并回读四份表格。外部 checker 并未重新生成每个随机样本的完整轨迹，因此报告分别给出内部逐次可行性检查与外部代表轨迹复验的数量，不将二者混称。

## 来源与结论边界

官方材料来源为 [2018 CUMCM Problems](https://en.mcm.edu.cn/html_en/node/b4184fa60b0e32c59e451c1e351d321d.html)。当前清洁仓库与运行包不携带 `assets` 中的题目 PDF、流程说明 PDF、四份原始空白 XLS 或 Table 1 时间参数转录；完整运行前须按 [历史附件说明](../../docs/HISTORICAL_FIXTURES.md)独立取得有权使用的材料。缺附件的集成测试会明确跳过。算法来源是用户提供的《mathmodel-skill 复现与拆解报告》随附证据包，非赛事官方参考答案；其公开再分发范围仍待确认。

本例只在限定策略与固定刀具分配中选择已观察到的最佳结果，不证明全局最优。故障按每次加工开始的独立概率解释，故障时刻与维修时间采用明确的均匀分布假设；仅携带一个中间件、即时清洗交付和卸料保守计时等原模型限制均保留。敏感性实验使用健康情况下选定的配置，不对每个随机情景重新优化。均值区间描述本模拟的抽样误差，不能推断真实工厂的普适表现。

状态固定使用 `historical_benchmark`、题目年份 `2018` 和规则年份 `2026`。这不是正在参赛的项目：没有当届规则锁、团队人工终审、正式排版论文、提交包或提交回执。即使全部需求通过机器核验，`submission.ready` 仍应为 `false`。

## 自动验证

```powershell
python -m unittest discover -s tests -p test_copilot_benchmark.py -v
```

测试执行一个真实冒烟项目，并验证其两问覆盖、论文证据绑定、正式 Ready 拒绝、既有目录保护、伪造交付件数拒绝，以及缺失统计区间端点和重复敏感性配置的拒绝。完整三组实验通过上述一键入口独立运行，不以冒烟结果代替。
