# 论文来源回读合同（v0.1.2）

`copilot_paper_source.audit_paper_source(root, cp, section_ids, docx_path, contract)` 对实际 DOCX 主文档执行只读回读。它从当前已登记的 PaperSection 源文件派生正文，而不接受用户自报的 `expected_text` 或任意公式 hash。结果包含 `passed`、`errors`、实际文件绑定 `files` 和对象依赖 `dependencies`，由 DeliveryAudit 接入现有审计与失效链。

最小合同如下，章节顺序必须覆盖提交的全部章节且恰好一次：

```json
{
  "version": "0.1",
  "sections": ["SEC-introduction@1", "SEC-results@1"],
  "supplements": [
    {"kind": "source_code", "source_id": "CODE-solver@1", "path": "solver.py"}
  ]
}
```

章节需经 `Delivery.section` 登记。检查器再次校验当前对象、绑定文件以及 `_section_errors`，不能仅凭 `status=verified` 通过。带 `source_bindings`、`structure` 或显示数值合同的章节仍遵守 Runtime 的 Claim 和来源门禁。`section_projection` 只展开已登记来源块，结果主张的显示值仍须由 Claim 的确定性格式合同解释。

支持的正文子集为 Markdown 标题、段落、原生管道表格、单行 `$$ 表达式 $$`、独占段落图片。检查按原始顺序比较实际 DOCX 段落、表格每格、原生 OMML 表达式 token 和内嵌图片字节 hash。文本经 Unicode NFKC 和空白归一化，同时逐段、逐单元格保留归一化前的数字 token 顺序与边界，防止 `182.81` 被替换成 `18 2.81` 后误通过。不声称检查字体、分页、美观或数学等价性。公式支持明确的线性项、下标、上标、分式、根式、上横线和显式累加算子，其他构造拒绝并说明限制。分子、分母和下标位置不会被忽略。

图片必须同时出现在章节的 `structure` 声明中，并指向一个绑定真实图片文件的当前 ArtifactRecord；仅提供 Markdown 路径不足以授权图片。源程序附录只能通过 `source_code` supplement，从当前 CodeManifest 或 ValidationPlan 绑定的真实文件派生。渲染时完整源码应写入既有 `CUMCMSourceCode` 或 `CopilotSourceCode` 样式的原生段落，保留缩进和换行，不能用自由文本替换。

完整支撑材料文件表可使用 `{"kind":"file_list","source_id":"current@1","paths":["assets/input.csv"]}`。来源只允许当前 ProblemContract、DataContract、CodeManifest、ValidationPlan、ArtifactRecord 或 RunRecord，每条路径必须已经在该对象的真实 `files` 中绑定，且本轮重新核对文件大小与 hash。它固定派生“文件：路径”段落，并加入审计依赖；不接受任意说明文字、绝对路径、未绑定文件、空清单或重复项。最终支撑材料检查仍要求论文包含每个实际提交文件，不能通过少列合同内容消除缺项。

文献结构编号由 `copilot_section` 的 reference ArtifactRecord 合同派生，源模块传递真实 root 读取注册表；它不能取代迁入 CitationAudit 的正文书签、文后书签、来源核验记录和双向对应检查。

检查器拒绝多余、缺失、重排的内容，自报预期文本，未绑定代码，隐形正文、修订内容、外部图片、嵌套表格与不支持的混合公式/图片段落。表格各层采用结构白名单，不能默默忽略单元格内可见内容控件。DOCX 在实际回读前后重复取 hash，读取途中被替换会失败。其返回的文件与依赖必须由 DeliveryAudit 绑定，后续源文件或对象变更会使审计失效。

为避免 `styles.xml` 的隐藏段落、字符、继承样式、表格样式或默认样式绕过正文可见性检查，当前版本保守拒绝样式表中任何为真或无法确定的 `vanish` / `webHidden` 定义，即使该隐藏样式尚未使用；显式 `false` 定义可通过。此实现没有冒充完整的 Word 样式引擎。普通原生样式和实际报告生成器须通过正例检查；复杂模板若带隐藏样式，应先明确处理可见性再登记新文档。

真实交付还需现有文档检查：实际 Word/受支持引擎导出、DOCX 与 PDF 文本对应、每页渲染图及视觉检查、引用与 AI 披露、支撑材料和代码附录。来源回读通过不能替代这些检查，也不能代替团队人工终审。历史复现项目即使 DeliveryAudit 通过并冻结，仍不表示正式 `submission_ready`。

`tests/test_paper_source_v012.py` 验证实际正例以及追加虚假结果、漏段、重排、表格换值、公式颠倒、图片替换、伪造预期文本、源对象/文件过期、未绑定附录等负例。

v0.1.3 保留此来源合同，在公共段落/行内入口补充明确的读取语法，防止符号、连字符、换行或未知内容被静默遗漏。支持与拒绝范围、API 错误语义和本轮证据分层见 [DOCX 行内读取](DOCX_INLINE_V013.md)。
