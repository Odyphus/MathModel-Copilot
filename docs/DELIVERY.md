# 论文与交付合同

`scripts/copilot_delivery.py` 将原项目的论文装配入口、EvidenceMap、迁入的文档检查器与同一个 `decision_log.json` 连接起来。所有写入使用 `Store` 的 revision/CAS 事务，结果记录在 `copilot.objects`；`copilot.delivery` 只记录当前对象和状态。规则锁位于 `copilot.rules_lock`，不会产生第二份权威状态。

## 调用接口

以下方法返回 `{revision, result}`。`revision` 必须是调用方读取到的当前版本；冲突必须重新读取和处理，不能自动覆盖。

```python
delivery = Delivery(project_root)
delivery.lock_rules(revision, pack, problem_year, rules_year, evaluation_mode,
                    source_snapshots, reviewer, actor="integrator")
delivery.section(revision, key, path, claim_ids, actor="writer")
delivery.audit(revision, manifest, actor="qa")
delivery.freeze(revision, actor="integrator")
delivery.package(revision, relative_path, actor="integrator")
delivery.event(revision, state, evidence_path=None,
               actor_kind="human", actor="integrator")
submission_status(project_root, decision_log)
```

`pack` 可以是 `load_pack` 返回值、注册名或 pack.json 的路径；`manifest` 可以是对象或项目内 JSON 相对路径。其余文件引用必须是项目内正斜杠相对路径。现有资产不会被打包入口覆盖。外部提交事件不执行上传。

## 持续论文与证据

v0.1.1 补充：章节允许使用的数字从实际已核验 Result.metrics 重建，不再使用 Claim 文本自身作为支持数字。`claim_type` 无法豁免这一步。说明性 Claim 的登记状态与结果核验状态分开，参见 [Claim 保证](CLAIM_V011.md)。已有 v0.1 的无依据 verified Claim 在消费时也会被阻断，历史记录不会被改写。

PaperSection 当前接受 Markdown/TXT。每项主张引用已采用、当前有效且完成独立验证的 EvidenceMap 对象版本：

```markdown
Computed length is 10 m. [[claim:C1@1]]
```

调用时 `claim_ids=["C1@1"]` 必须与标记集合完全相同。段落必须保留对应 Claim 原文；数值段落缺少标记、引用失效结果、额外加入未支持数值均拒绝登记为 verified。数字识别与 Runtime 共用规范化逻辑，区别 `.10`、`−10`、`10e2`、`10%`，也保留符号与数字间空白表达的符号和比例。围栏中的代码不当作论文结论；标题中的数值仍须有证据，不能藏入标题绕过检查。读取旧版 verified PaperSection 时同样重新检查实际文件与 Claim。该检查保证登记段落的数值来源，不替代语义推理、公式审查和人工内容核验。

最终 DOCX/PDF 还会逐项检查 Claim 原文是否实际存在；manifest 必须包含全部当前 PaperSection，Claim 集合与 Section 集合一致，并覆盖全部有效 Requirement。任一预期子问未覆盖时交付审计失败。

## Manifest

```json
{
  "files": [{
    "path": "paper_output/paper.docx",
    "role": "paper",
    "metadata_path": "paper_output/paper.metadata.json",
    "visual_qa_path": "reviews/visual.json",
    "rendered_pdf": "paper_output/paper.pdf",
    "render_receipt": "reviews/render.json",
    "render_metadata_path": "paper_output/pdf.metadata.json",
    "render_visual_qa_path": "reviews/pdf-visual.json"
  }],
  "sections": ["paper.results@1"],
  "claims": ["C1@1"],
  "reviews": [
    {"kind": "anonymity", "path": "reviews/anonymity.json"},
    {"kind": "content", "path": "reviews/content.json"}
  ],
  "citation_registry": "references/registry.json",
  "supporting_manifest": "supporting/materials.yaml",
  "rule_review": "reviews/competition-rules.json"
}
```

只有 `files` 明确列出的文件进入总包。角色为 `paper/code/data/figure/table/instructions/evidence/supporting_archive`，必须恰有一篇最终论文。审计读取的元数据、检查凭据、渲染图片会记录哈希，但不会因被读取而自动加入交付包。需要随总包提供时也必须显式加入白名单和人工检查的文件集合。

PDF 主稿可通过 `source_docx` 指定可编辑母版。当前 PDF 检查器保留迁入的 DOCX→PDF 单向派生合同；纯 TeX PDF 尚无等效的自动来源核验链，不能据此宣称正式 Ready。原 `render_paper.py` 的 TeX 装配能力仍保留。

Office sidecar 沿用迁入工具的小写 SHA-256 契约。Runtime 文件记录及总包 SHA-256 使用大写。人工检查文件哈希接受任意大小写；比较的是实际字节。

## 人工检查与实际渲染证据

匿名和内容核验文件必须是结构化记录，绑定白名单全部文件及其当前哈希：

```json
{
  "kind": "anonymity",
  "actor_kind": "human",
  "reviewer": "实际检查人",
  "reviewed_at": "2026-10-05T09:00:00+08:00",
  "result": "pass",
  "notes": ["记录实际检查位置、范围和发现，不能只有通过标记"],
  "files": [{"path": "paper_output/paper.docx", "sha256": "实际SHA256"}]
}
```

历史复现允许明确标为 `agent_evaluator` 的检查；正式交付必须为 human。工具核验结构、实际文件、版本一致性和检查覆盖范围，不认证签署人的真实身份，也不会自动生成真实人的核验记录。

视觉核验沿用迁入的 `source_docx_sha256` 或 `source_pdf_sha256`、`status`、`page_count`、`inspected_pages` 合同，并增加 `reviewer/actor_kind/notes` 与 `rendered_pages=[{page,path,sha256}]`。工具实际读取图片并检查每张图片哈希，不能只填 `visual_checked: true`。

正式交付另需真实 Word/TeX 渲染记录：

```json
{
  "renderer": "实际执行的渲染程序及版本",
  "command": ["实际程序", "实际参数"],
  "exit_code": 0,
  "files": [
    {"path": "paper_output/paper.docx", "sha256": "实际SHA256", "byte_size": 123},
    {"path": "paper_output/paper.pdf", "sha256": "实际SHA256", "byte_size": 456}
  ],
  "log_path": "reviews/render.log",
  "log_sha256": "实际SHA256"
}
```

这些数据必须来自实际渲染。Delivery 读取实际源文件、PDF、执行日志和检查记录；DOCX 还需对应 PDF 通过迁入 PDF 审查器。单独填写成功布尔值、宿主上发现程序已安装、或仅有生成的 DOCX，都不能满足正式交付条件。本模块不启动 Word/TeX、不代替使用者确认其执行日志来源。

## Competition Pack 必需检查

显式映射的 `required_checks` 为 `rules_verified/anonymity_passed/page_limit_passed/ai_disclosure_passed/supporting_materials_passed`。每项保留 executed/status，未知必需项直接失败。页数必须来自实际 PDF；字节上限执行 pack 中的 `lt` 或 `lte`，不是统一写死。其他官方规则（例如 MCM 的字号、页眉、Summary Sheet、语言）需逐规则人工记录，否则正式交付阻断。

`rule_review` 沿用上面的文件绑定检查格式，`kind="rules"`，增加 `pack_digest`（`copilot_store.digest(lock["pack"])`）和 `rules`：

```json
{
  "minimum_font_size_pt": {
    "rule_digest": "digest(lock.pack.rules.minimum_font_size_pt)",
    "result": "pass",
    "notes": ["写明实际查验页、样式或字体事实"]
  }
}
```

这里的 `rules` 对象嵌入完整 human 检查记录；不使用占位字符串作为实际 digest。

AI 台账继续使用 `compliance.ai_usage` 及 `render_ai_usage.py` 原验证器。`null` 表示未核对，不能解释成未使用。CUMCM 声明必须在参考文献之前且与实际台账一致；非空台账要求真实支撑 ZIP 内包含规则指定的详情 PDF，PDF 提取内容需覆盖台账中的工具、交互或过程说明、人工核验和采用信息。MCM 非空台账需要 manifest 的 `ai_disclosure={solution_last_page,report_pages}`；报告区间必须是实际 PDF 连续尾页，并以 `Report on Use of AI` 标题开始。解答页数与 AI 报告页数按已锁规则区分。未定义 AI 披露规则的赛事保持阻断，不能用未发现规则推导为通过。

正式引用检查需要实际 `citation_registry` 并运行原 CitationMap/ReferenceRegistry 检查器；完全不适用时提供 `reference_applicability` 路径，文件为 `kind="references_not_applicable"` 的版本绑定人工检查，另含具体 `reason`。缺少 registry 本身不构成不适用证据。

要求独立支撑包的 pack 必须提供实际 `supporting_archive` 和 `supporting_manifest`。支撑包继续复用原 ZIP 白名单、匿名、SHA/CRC、内部清单与外部清单一致性以及 CUMCM 源码附录检查，不混入论文总包的规则。

## 状态与失效

| 状态 | 含义 |
|---|---|
| generated | 已有草稿或本次审计失败，不表示完成 |
| checked | 当前 Requirement、证据、论文和适用检查通过 |
| frozen | 冻结当前通过审计；可以生成本地总包 |
| awaiting_submission | 正式项目当前总包满足条件，等待外部提交 |
| submitted | 人工显式记录外部已提交凭据 |
| receipt_received | 人工显式记录平台回执 |

只有 `formal_contest` 在 `awaiting_submission` 且所有版本绑定条件通过时，`ready=true`。历史/开放研究项目可 checked/frozen/package，正式 Ready 始终 false。submitted 和 receipt_received 表示已记录的外部事件，不再是待提交 Ready。

`audit` 失败也生成 failed 对象及具体错误。Requirement 集合/覆盖、预期题目数、规则锁、AI 台账、PaperSection 版本以及实际审计输入的哈希改变后，旧 audit/freeze/package 不再有效。上游运行、参数、代码变更沿已有依赖图传导。查询不会通过写状态来掩盖漂移。

`event` 只接受 `frozen → awaiting_submission → submitted → receipt_received`。后两项需 `actor_kind="human"` 和外部凭据 JSON：`state/package_sha256/external_reference/recorded_at/receipt_path/receipt_sha256`。实际凭据文件及记录本身也绑定哈希，后续事件依赖前一事件，变更早期凭据会使整条证据链失效。函数始终返回 `performed_upload=false`。

## 本地总包

`package` 生成包含论文及显式文件白名单的 ZIP，内部为 `delivery-manifest.json`，保存文件 role、byte_size、sha256 与 audit/freeze 对象版本。完成后重新打开 ZIP 检查 CRC、成员集合、重复/大小写冲突、路径安全、符号链接、加密以及所有文件哈希。

总包用于本地交接归档；它与赛事官方支撑材料 ZIP 是两个独立产物，不能把总包自动当成赛事上传文件。生成总包不会记录已上传或已收回执。

## 测试与当前范围

`python -m unittest discover -s tests -p test_copilot_delivery.py -v`

测试使用显式 synthetic custom pack、真实 Python 子进程与独立 checker、真实 DOCX/PNG/ZIP 字节。正向路径覆盖 historical checked/frozen/package；负向覆盖缺子问、无证据或多余数字、旧审计、匿名、来源漂移、AI 台账变化、未知规则、严格字节边界、无支撑包、无实际渲染记录、路径越界和 CRC。测试人工字段都是合成夹具，不是对真实论文的人工签署，也不证明真实 Word/TeX 或赛事平台已运行。
