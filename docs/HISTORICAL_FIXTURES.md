# 历史附件与独立获取

清洁候选不携带官方题目 PDF、空表 XLS、参数数据或内部案例输出。源码中的历史 CUMCM 算法、checker 和原测试为保留回归而留下，其公开权利仍受 [LICENSE_SCOPE.md](../LICENSE_SCOPE.md) 的发行阻塞约束。

## CUMCM 2018 B

官方入口：[2018 CUMCM Problems](https://en.mcm.edu.cn/html_en/node/b4184fa60b0e32c59e451c1e351d321d.html)。在确认适用取用条件后，由用户从该官方入口取得 B 题与附件，放入独立、非公开的测试副本 `examples/cumcm2018b/assets/`：

- `CUMCM-2018-Problem-B-English.pdf`
- `CUMCM-2018-Problem-B-English-Appendix-1.pdf`
- `Case_1_ result_E.xls`
- `Case_2_ result_E.xls`
- `Case_3_ result_1_E.xls`
- `Case_3_ result_2_E.xls`
- `official_parameters.json`：来自题面 Table 1 的本地转录，需与原题逐项核对。

文件名是现有 runner 接口要求，不是下载来源或许可证明。记录来源 URL、获取日期和每个文件 SHA-256；有内部授权基准清单时逐一核对。不要使用未验证镜像填补缺文件，也不要把取得附件误称为获得公开再分发许可。

安装 `.[historical]` 后运行原 `test_copilot_benchmark.py` 或 `examples/cumcm2018b/run_benchmark.py`。本次内部完整证据与清洁发行包是不同文件集合：内部回归可以使用已授权附件；清洁包安装验收使用原创合成 demo。缺少上述任意附件时，三项历史集成测试明确 skip 并逐一列出缺失文件；报告标记为 fixture_missing，不计为通过。附件齐备后的断言失败仍按代码或断言失败报告。完整历史集成缺口不能从验收承诺中静默删去。

## MCM 合成演示

`examples/mcm2009a/` 只保留新编写的模型代码、checker 和局部问题说明；官方题目不打包，按案例说明中的官方链接取用。需求、容量与控制策略是明确标注的合成演示，不使用真实车辆或私人数据。来源边界和模型局限应随结果一同阅读。
