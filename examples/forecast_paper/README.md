# 原创合成预测 → 独立核验 → 论文导出

本例是已知直线 `y=10+2t`，共 17 个小时观测，每个值延迟一小时发布。固定三个预测起点、一步与两步，共六个预测实例。用于检查因果窗口和工程链路，不是比赛结果或模型精度宣传。

从 Skill 根目录运行，目标目录须不存在或为空：

```text
python examples/forecast_paper/run_example.py --workspace <新建演示目录>
python examples/forecast_paper/run_example.py --workspace <另一个新目录> --pdf
```

需要 analysis/documents 依赖；PDF 另需本机 LibreOffice 或可用且空闲的 Windows Word。不会覆盖文件、上传数据或替换 Skill 安装。

脚本声明题意、数据、模型、参数、代码和独立检查，真正执行预测及 checker，产生 Run/Validation/Result 回执；将指标绑定为 Claim、章节和来源合同，再生成原生 DOCX 与可选 PDF。成功后查看 `example-report.json` 与 `paper/预测核验示例.docx.source-audit.json`。

解析预期为候选 MAE 显示值 0（十二位小数）、最后已发布值基线 MAE 5、实例 6。独立 checker 不导入求解器或 sklearn，另行核对已知直线、发布时点、全部窗口、训练均值及误差运算。工作台可比较两个指标，并明确各自的方法、单位和条件。

Source readback、本地转换与实际页面检查是三种不同保证；示例不完成赛事规则锁、最终交付冻结或人工定稿。修改训练窗口后，有关结果、章节、导出成果须重新核验和导出。
