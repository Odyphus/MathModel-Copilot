# v0.1.1 Claim 内容与证据保证

本次修复保留 EvidenceMap、Result、Requirement、Task、PaperSection 和 Store 合同。`claim_type` 仍描述用途，不再决定哪些结果数字免于校验。

## 登记、内容绑定与语义审阅

所有类别都需实际当前已验证 Result、对应 Run 和具体 Requirement，以及可核对的数据、代码和验证引用。每个参与支持的 Result 必须对应同一问题和相关具体要求；跨问比较由该问 checker 计算成比较指标后再引用。

随后按正文内容决定保证：

| 内容 | 登记结果 |
|---|---|
| 正文有数字，全部可绑定实际已验证 metrics 的数字叶节点 | `verified`，保留数值与 Result ID / metric path / value 的绑定；与类别无关 |
| `numerical` 无数字或含无依据数字 | 拒绝，保留原数值主张的严格错误语义 |
| 其他类别含未支持数字 | 可以登记为 `generated` / payload `draft`，明确待来源核验，不可完成需求或生成已验证章节 |
| 没有数字的普通方法说明、限制或定性结论 | 可以登记为 `generated`，不能仅因附有一次 Run 就获得内容已核验保证 |
| 没有数字且完整正文等于独立 checker 已验证 metrics 中的某个字符串 | 可登记为 `verified`，保存该原文与 metric 路径的绑定 |

因此年份、步骤编号、公式常数不被禁止；当它们只是待查明来源的说明时正常保留。工具不会接受调用者自行标注“这是年份/常数”作为免检通行证。用户可先保留草稿，或者让合适的独立检查器核对相应内容和来源。

对象的 `claim_assurance` 分别记录 `numeric_status`、`numeric_bindings`、`statement_bindings`、`unbound_numbers`、`scope` 和 `semantic_review`。`semantic_review=not_performed` 明确表示机器并未证明任意自然语言推论、因果性、单位含义或全局最优。精确数字匹配仍需正确且独立的领域 checker 与最终内容复核。

## 章节与旧版本兼容

PaperSection 从实际 Result metrics 重新计算支持数字，不再把 Claim 正文中出现的数字当成证据。默认 verified 章节只接受当前有效且有内容保证的 Claim。生成的说明可以继续保留在草稿文件和 Artifact 中，不会偷偷升级为 verified 章节。

读取/消费旧 v0.1 的 `verified` Claim 也会重新检查实际引用与内容；旧 `status`、外层哈希和缓存 `numeric_bindings` 均不能替代核验。真实且当前的旧数值主张仍可用。原本只有用途标签或泛泛引用、没有实际内容依据的主张会显示待补证，其后代章节也不可继续采用。

此过程不会重写历史。修复现有项目应从当前有效的 Result/Validation 补充具体主张，登记同一 Claim key 的新版本，再更新相关章节。无依据的旧版本仍保留，不能直接修改历史 status 使其复活。

旧 PaperSection 读取时也复用章节内容检查。即使它引用真实数值 Claim，旧版曾漏检的虚假结果标题也不会继续显示有效。符号与数字之间的空白、Unicode 负号、百分号与指数表示先统一解析，避免把负值或比例误读成碰巧匹配的正数。

2018B 示例原 Q1 方法描述只泛称测试通过；本版改为明确引用实际 `algorithm_tests` 数量。Q2 checker 另外暴露已独立重新计算核对的故障统计和敏感性统计，以供真实论文数字绑定；算法、仿真假设与可行性验证器保持不变。

## 检查

`tests/test_claim_v011.py` 覆盖类别替换、实际正对照、缺 Evidence 引用、合法方法数字草稿、无数字事实、旧坏对象消费、伪造缓存绑定和真实 checker 定性原文。独立 `tests/test_v011_redteam.py` 继续覆盖相邻反例；最终结果以发行验收记录为准。
