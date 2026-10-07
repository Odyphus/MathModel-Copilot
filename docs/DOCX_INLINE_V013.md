# DOCX 行内读取与拒绝边界（v0.1.3）

本版修复 `copilot_paper_source` 对可见行内内容的漏读。原 `node.iter()` 只收集文字、制表和部分换行，其他构造默默消失；因此普通追加文字会被拒绝，同样的字体符号却可能通过来源审计。修复保留当前来源合同和调用入口，不新增权威状态或字符豁免列表。

## 明确读取的构造

段落与表格单元格使用同一 `_paragraph_text`，普通 run 与数学 run 使用同一 `_run_text` 的字符规则。遍历按完整命名空间及父容器识别，不因 local name 相同接受未知节点。

| 构造 | 实际读取或检查 |
|---|---|
| 普通 `w:t` / 数学 `m:t` | 保留原文字及出现顺序，字符节点不能包含未知子节点 |
| `w:tab` | 制表字符；数字 token 在空白归一化之前提取 |
| `w:cr`、显式 `w:br` | 换行；包含 page/column break，不能把两侧数字拼成一个数 |
| `w:noBreakHyphen` | 在原位置保留 `-`，不得丢掉可能的负号 |
| 书签、`proofErr` | 明确的空范围标记，不能包裹其他内容 |
| `w:hyperlink` | 按顺序读取受支持的文字 run 和标记，不跳过整个超链接 |
| `w:lastRenderedPageBreak` | 非作者输入字符的渲染分页标记；不改变源文本 |
| 支持的原生 OMML | 保留原表达式合同；数学 run 同样读取字符或拒绝未知内容，复合结构不得藏额外子项 |
| 原生内嵌图片 | 只接受现有 `wp:inline` / picture 路径及明确列出的结构；真实图片字节仍必须绑定当前 ArtifactRecord |
| 代码附录 | 沿用当前绑定源码，完整保留换行和缩进后比较，不能以正文去空白规则处理代码 |

`w:noBreakHyphen` 使用与 U+002D 相同的字形；`w:cr` 是明确换行。这些行为依据 [Microsoft NoBreakHyphen](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.nobreakhyphen?view=openxml-3.0.1) 和 [Microsoft CarriageReturn](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.carriagereturn?view=openxml-3.0.1)。这是本检查器的有界源文本投影，不是完整 Word 排版实现。

## 明确拒绝的构造

`w:sym` 的显示字符取决于其指定字体的字形编码，不能只把 `w:char` 当作普通 Unicode。参见 [Microsoft SymbolChar](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.symbolchar?view=openxml-3.0.1)。本版本对所有字体的 `w:sym` 都明确拒绝，包括正文、独占段落、表格、代码和受支持数学 run；不为 Arial 或某个数字串设置特例。

动态字段（如 `fldSimple`、`fldChar`、`instrText`）、条件软连字符、未支持的内容控件/行内容器、未知命名空间、旧式图片和额外 DrawingML 内容也明确拒绝。不能可靠读取时不能返回“来源一致”。既有段落和字符格式属性仍交由原隐藏样式、文档与渲染检查，不把字体、视觉遮挡或数学等价性宣称为本读取器已完整证明。

如遇拒绝，应通过正常文档制作流程换成来源可表示的受支持构造，重新登记受影响版本并重审。不要删掉可见内容、增加 ignore 字段或改动权威 JSON 来绕开错误。

## API、兼容性与证据

- `read_docx_blocks()` 对不支持的内容抛出包含节点名的 `ValueError`；这是明确拒绝，调用方诊断代码应处理异常。
- `audit_paper_source()` 捕获该错误，返回 `passed=false` 和具体 `errors`；既有 DeliveryAudit 继续使用这一结果。
- `paper_source.version=0.1`、state schema 4.0、copilot 0.1、Context 0.1.1、Claim assurance 0.1.2 保持原合同。本次不改数值容差、对象可信度、状态更新、规则或提交语义。
- 旧 461 个测试方法与 29 个文件保留；新增 `test_inline_v013.py` 和 `test_inline_v013_redteam.py` 直接检查实际 DOCX 来源消费行为。
- 原附带探针在修后调用底层读取诊断时会遇到原脚本未捕获的 `ValueError`，因而退出 1；这不是“原 14 场景全通过”。交付另保留同一四份 DOCX 原字节的来源审计前后对照及独立相邻探针。

报告分别记录来源层反例、文档检查、已交付 PDF 回读、新渲染尝试和人工审查。原合成符号反例不能证明全部 Delivery 门禁可被绕过，也不能证明历史正常稿有伪造内容。历史项目即使来源与文档回归通过，仍维持 `submission_ready=false`。
