# v0.1.2 章节数字与来源

章节编号、模型参数和计算结果有不同来源。v0.1.2 只增加受限的结构解析和来源投影；不扩大数值误差，也不把 `method`、`year` 或 `constant` 标签当作核验依据。

## 标题编号

`# 1 模型结果`、`## 1.1 结果核验` 的开头编号可以通过。每级为一至两位正整数，必须与标题正文有空格；单独计量单位不构成章节标题。标题剩余内容继续接受 Claim 检查，`# 1 结果为 999 m`、`# 结果为 999 m`、`# 999 m` 均无结构豁免。此规则识别排版，不证明章节标题中的自然语言判断。

## 来源说明块

`Delivery.section(..., source_bindings=[...], structure=[...])` 是原接口的可选扩展。CLI 对应 `section --source-bindings sources.json --structure structure.json`，两个文件均为列表。

一条来源绑定严格包含 `id, kind, source_id, source_path`。章节独立段落写 `[[source:source_id_in_this_section]]`；运行时从当前对象字段生成完整可见文字，调用者不能提交 `expected_text`、任意忽略区间或“核验通过”布尔值。

| kind | 允许来源 | 可见文字的性质 |
| --- | --- | --- |
| year | RulesLock 的 `/problem_year`、`/rules_year` | 已锁定的题目/规则年份 |
| parameter | ModelSpec 的 `/parameters/N/current_value` 或 ParameterSet 的 `/entries/N/current_value`，可继续指向其中的数值叶子 | 模型中明确声明的数值、符号、含义和单位 |
| formula | ModelSpec 的 `/formulas/N/expression` 或 `/formulas/N/latex` | 原样引用已登记的模型公式 |

来源段落只说明输入/模型约定，不宣称运行结果通过。所有对象、文件、依赖须当前有效；来源成为 PaperSection 的正式依赖，更新后通过既有 Impact 机制使下游失效。任意结果句仍必须绑定已核验 Result 的 Claim。不能把 `[[source:x]]` 嵌进“结果是……”，也不能追加未经支持的数字。

## 图、表和公式标识

声明 `{"kind":"figure","number":1,"artifact_id":"...@1"}`（table 同理），并在章节独立段落写 `[[figure:1]]`。ArtifactRecord 必须有实际文件绑定，类型与声明一致。公式声明为 `{"kind":"formula","number":1,"source_id":"...@1","source_path":"/formulas/0/expression"}`，对应 `[[formula:1]]`。

正文的 `图 1`、`表1`、`式（1）` 只在存在相应唯一声明时视为结构引用。其余数字仍被检查。标识存在和图片字节一致不证明图片内容的科学解释正确；统计结论依旧需要 Claim/Evidence 和实质验证。

参考文献使用同一机制：`{"kind":"reference","number":1,"artifact_id":"...@1"}` 绑定 `artifact_type=reference_registry` 的 ArtifactRecord 和一个真实注册表 JSON。独立段落 `[[reference:1]]` 从其 title 派生 `[1] 标题`，正文 `[1]` 仅在该声明存在时是结构引用。注册表结构复用原 CitationAudit，最终仍必须检查引用书签、编号、核验/采用记录和引用双向闭环。任意“引用编号”标签、未知编号或自报文本不能替代文件来源。此时调用 `section_projection(..., root=workspace)`，用于读取并核对绑定注册表。

## 到最终文档

`section_projection(cp, text, source_bindings, structure)` 返回来源标记展开后的可见 Markdown。它只是派生函数，不能替代 `_section_errors` / `Delivery.section` 的当前性核验。新来源/结构或显示精度的章节必须在 Delivery manifest 提供 `paper_source`；通过实际 DOCX 回读比较，不能仅靠外层哈希和 Claim 子串存在宣称完整装配。

旧文档仍按其原协议可读。旧协议没有全篇来源投影证明，不能将向后兼容解释为补发这种证明。LaTeX 排版和自然语言语义等价不属于此投影协议的自动核验范围。
