# cumcm-workflow 1.6.0 迁入说明

本次把已有领域对象和校验逻辑接入 MathModel Copilot 的单一状态；没有把原来的 `.cumcm` 状态系统、CLI 或活动安装一起迁入。

## 1. 来源与边界

来源为用户明确指定迁入的本地 `$CODEX_HOME/skills/cumcm-workflow`，读取时 `VERSION=1.6.0`。此候选用变量替换个人绝对安装路径，原始路径保留在独立历史证据中。源码文件的实际 SHA-256 与函数范围见本文末尾。该目录没有发现根 `LICENSE`；此处记录为“用户提供、授权本地迁移的实现”，不把它自动改写为上游 mathmodel-skill 的 MIT 授权。活动安装未修改。未复制原项目的论文样例、图片、二进制 Office 资产、语料或第三方转换器。

Mathmodel-skill 的原 MIT 许可证和版权归属继续保留。公开再分发时需要单独确定迁入部分的授权范围；当前交付不包含发布行为。

## 2. 唯一状态与对象所有权

唯一可写权威仍是 `state/decision_log.json`，由 Store 在锁内检查状态版本并提交。原 Stage、评分、子问字段继续存在，新功能放进 `copilot` 子树：不可覆盖对象版本、当前指针、Task、事件、成员基线、采用与核验记录。

迁入模块只做以下操作：

- 解析和校验原对象字段。
- 计算 semantic_hash、record_hash 与实际文件 SHA-256。
- 按显式输入的依赖边计算影响闭包。
- 读取待检文件，返回检查结果。

它们不读取 Store，不修改状态，不建立 `.cumcm/events`，不把来源安装目录作为运行时依赖。`decision_log.json` 的旧字段与新对象之间的衔接由 Store/Runtime 负责，不能各自写入后再互相覆盖。

原 CUMCM `load_state`、`save_state`、`init_project`、`register_run`、`promote_run`、`build_evidence_map`、`validate_project` 和所有 CLI 状态写入口均未迁入。`RunRecord`、`EvidenceMapEntry` 等对象只有一套字段定义；新的 Execution Receipt 是对真实执行事实的补充，不能生成另一套可与 RunRecord 冲突的运行状态。

## 3. 实际复用清单

| 新文件 | 复用来源 | 保留内容 | 必要适配 |
| --- | --- | --- | --- |
| `scripts/copilot_domain.py` | `cumcm_core.py` | ModelSpec、ParameterEntry/Set、ActivationRecord、RunRecord、EvidenceMapEntry、ArtifactRecord、ProvenanceEdge、ValidationCheck、公式映射对象、密封/哈希、模型和参数校验、数据/代码/重复/运行报告校验 | 移除原状态、路由和 CLI 依赖；调用者注入当前对象与依赖 |
| 同上 | `workflow_v13.py` | RequirementEntry、ProblemContract、AmbiguityEntry、AssumptionEntry、HumanDecisionEntry、AuditFinding、合同、数据契约和验证计划检查 | 原注册表改为显式参数，不按 `.cumcm` 路径找文件 |
| `scripts/copilot_model_evidence.py` | `model_evidence.py` | 预处理范围、时序切分、公式独立数值证据、基线、语义、敏感性、主张范围与表图一致性 | 文件读取辅助函数只依赖新纯领域模块 |
| `scripts/migrated/docx_audit.py` | 同名源文件 | OOXML、原生数学、公式书签、可见源码、表格几何、图像语义、元数据与视觉记录绑定 | 移除 CLI；包内相对导入；CUMCM 版式由 Competition Pack profile 显式选择 |
| `scripts/migrated/pdf_audit.py` | 同名源文件 | PDF 可读性、空页、A4、正文页数、字体、源 DOCX/元数据/逐页记录绑定 | 移除渲染与 QA 写入入口；页数、A4、身份检查参数化 |
| `scripts/migrated/citation_audit.py` | 同名源文件 | ReferenceRegistry/CitationMap 与 DOCX 书签双向闭环、编号、重复文献、核验状态 | 移除 CLI；不生成正文和引用 |
| `scripts/migrated/supporting_materials.py` | 同名源文件 | 白名单、静态程序入口、字节哈希、ZIP 成员、CRC、大小写冲突、路径、附录源代码 | 移除 ZIP 写入和 CLI；大小/匿名/无程序陈述参数化；禁止把新权威 `state/` 混进支撑材料 |
| `scripts/migrated/office_common.py` | 同名源文件 | ArtifactFinding、文本提取、敏感信息扫描、OOXML 事实、哈希、结果转换 | 仅保留只读辅助函数，删除 Word 生成、样式与文件写入 |
| `scripts/migrated/office_formula.py` | 同名源文件 | 原 `formula_bookmark_name` | 仅提取确定性书签命名，不迁入转换器或 Microsoft XSL |
| `scripts/migrated/workflow_policy.py` | 同名源文件 | formal/historical/open_research 的模式、范围与核验身份策略 | 模块本身无 IO；不承担新的状态存储 |
| `scripts/migrated/cumcm_ai_declaration.py` | `cumcm_core.py` | 原 AI 声明段落定位与句式检查 | 仅在选中的 CUMCM 文档 profile 中使用 |
| `scripts/copilot_document_checks.py` | 适配层 | 统一加载上述只读检查器 | 把 pack policy、当前文件和检查结果相连，不把检查写成真实人工行为 |
| `templates/copilot/` | `assets/templates/` | 20 个原对象模板 | 保留原对象 Schema；Run 模板的默认状态改为 not_executed |

## 4. 领域 API

所有校验器返回错误列表，空列表表示其检查范围没有发现结构/绑定错误。文件读取和哈希验证不会证明数学模型正确或声明中的独立性真实发生。

```python
validate_problem_contract(root, payload, *, ambiguities=(), assumptions=(), for_freeze=False)
validate_modelspec_structure(modelspec)
validate_parameter_entries(parameters, *, formal)
validate_parameter_contract(expected_parameters, actual_parameters)
validate_data_contract(root, inventory, passport, split, *, assumptions=(), formal=False)
validate_validation_plan(payload)
validate_run_report(root, payload, run, expected_check_ids=())
validate_data_manifest(root, payload, *, expected_version)
validate_code_manifest(root, payload, *, expected_question, expected_spec_id,
                       expected_modelspec_hash, expected_revision)
validate_repeat_ledger(payload, *, expected_count, expected_seed)
validate_evidence_entry(root, payload, run, *, run_is_current_verified,
                        run_integrity_errors=(), verified_literature_ids=())
impact_analysis(edges, source_id)
seal_record(payload)
verify_sealed_record(payload)
```

`ProblemContract` 和 `ModelSpec` 可直接使用原 dataclass。参数仍为 `estimated`、`human_set`、`external`、`derived` 四类；ReqID 沿用 `REQ-Q1-001` 形式。不要再维护另一套“简化 ModelSpec”或“简化 ParameterSet”。

原对象 `schema_version=1.0` 与新 Store 的版本不是同一个概念。对象 Schema 不应为了匹配项目版本号全部重写。

`validate_run_report(...) == []` 也可能对应一份结构真实、状态为 `fail` 的失败报告。提升结果必须同时要求真实执行成功、预定实质检查通过、依赖当前有效和文件未漂移。失败报告必须保留。

`validate_evidence_entry` 的 `run_is_current_verified` 由 Store/Runtime 对当前状态计算，不能直接取 Claim 自报的 `status=pass`。它要求当前 Run 及其真实输出，并沿用原 EvidenceMap 对数据、代码、表图、验证、引用类型的检查。文献内容核验 ID 集合同样来自当前权威状态。

密封对象的 semantic_hash/record_hash 与核心文件 SHA-256 保留原 64 位大写十六进制表达。Office 原元数据辅助函数使用小写哈希。对外层文件哈希比较应忽略大小写；不要把相同哈希的文本大小写当作版本变化。

## 5. 原实现中本次实际发现并修复的风险

1. 原 RunRecord 和模板缺省 `status=completed`。新缺省改成 `not_executed`，Runtime 必须用实际回执显式给出成功、失败或超时；其他原字段保持兼容。
2. 原数据合同的库存复检直接拼接项目根与输入路径。迁入时复用既有安全路径解析，拒绝绝对路径和越界路径。
3. 原运行验证报告用集合记录检查 ID，但没有拒绝重复 ID。迁入后显式拒绝重复 ID，避免同名检查覆盖歧义。
4. RequirementEntry 的输出、输入、单位、证据等列表增加类型预检，防止字符串冒充列表而通过非空检查。
5. 原 ZIP 审计只检查内部清单。适配入口还把内部清单与本次选择的外部清单比较，拒绝两个各自有效但版本不同的材料包。
6. 原 `.cumcm` 状态加载可能重建投影并写文件。本次整个写入依赖未迁入，读检查无法制造第二个权威状态。

这些修复有对应负向测试，并不是只写在操作规范里。

## 6. 文档与 Competition Pack 接口

`copilot_document_checks` 的 `audit_docx`、`audit_pdf`、`audit_supporting_materials` 均要求显式传入 `policy`：

```json
{
  "profile": "cumcm",
  "paper_max_bytes": 20971520,
  "supporting_max_bytes": 20971520,
  "body_max_pages": 30,
  "require_a4": true,
  "anonymity_required": true,
  "require_visual_qa": true,
  "ai_before_references": true,
  "no_program_statement": "本论文没有用到程序",
  "no_supporting_statement": "本论文没有支撑材料"
}
```

以上只是 CUMCM 已有检查器所接受的参数例子，不能代替当届官方来源核验与 rules.lock。`profile=generic` 不强行执行 CUMCM 摘要首屏、无目录、附录全代码、官方 AI 原句。对不支持的专项请求应返回明确未执行，不能借 generic 获得某赛事的完整合规结论。

`audit_pdf` 当前复用 DOCX→PDF 派生路径，检查源文件与元数据。继承的 TeX 装配/编译路径仍由 `render_paper.py` 负责；本检查器通过不能证明 TeX 编译成功。未安装 `lxml`/`pypdf` 时返回 `not_executed`，而不是将可选能力缺失当作通过。

所有文档审计保持输入文件不变。主 Store 决定何时登记新报告、标记旧报告失效、生成交付清单和请求真实人工确认。审计器不签字、不上传、不宣称已有官方回执。

## 7. 已完成的独立验收

测试命令：`python -B -m unittest discover -s tests -p test_copilot_domain.py -v`。

环境：Windows，Python 3.14.2，临时目录位于当前工作区的 `work/tmp`。全部领域测试为独立输入输出测试，包括正常合同、负向条件、实际文件变更、ZIP 和最小真实 OOXML 文件；不以源代码静态字符串存在作为通过。

2026-10-05 独立模块 checkpoint：35 个测试全部通过，0 跳过，0 失败。参数契约测试还确认实际数值可变，但参数含义、单位、类别、边界与来源策略不可绕过模型版本更新。

测试覆盖：密封篡改和非有限数；完整/重复/错问/字段类型的 ReqID；真实题面漂移；高影响歧义；未绑定合同的冻结模型；人为参数伪装与未检敏感性；数据库存漂移与越界；重复主体/时间/预处理泄漏；计划和报告漏检查、重复检查、未执行、失败、输出漂移；代码清单；失败重复；跨问传递影响及环；缺少真实运行的 Claim；旧结果拒绝引用；原 Word/ZIP 检查及新状态目录排除；读检查不制造第二状态。

所有 YAML 对象模板已在未安装 PyYAML 的 Python 中使用迁入的原离线解析器逐个解析。模板内的 null、待填内容和示例状态不是已完成工作，不能直接提升为有效对象。

该模块验收不等于完整旧题通过、真实 Word 导出、全页面人工视觉核验、真实三人异地使用或官方提交；这些由集成层和实际验收材料分别报告。

## 8. 未迁入的运行系统与后续边界

当前没有迁入旧 `cumcm.py`、`.cumcm/events`、旧版本迁移器、路线关键词注册表、环境安装器和旧项目目录生成器。新 Host Adapter 与 Task Runtime 应调用迁入纯接口，通过同一 Store 更新。

已有保留的 dataclass 包含不在 v0.1 完整自动化范围的字段。字段存在不等于功能已经完成：例如 `HumanDecisionEntry` 不证明人类确认，`validation_status` 不证明检查执行，`ArtifactRecord` 不证明视觉可读。当前正式有效性始终要依赖实际执行、文件绑定与检查证据。

单机文件事务解决本地共同写入端的并发，不代表跨三台电脑的云盘具有事务保证。文档专项模块也不承担分布式同步。

## 9. 源码指纹与抽取位置

下表由本次读取的本地源文件生成。源码位置按迁入前文件计；后续新模块行号会随修复变化。

| Source file | SHA-256 | Installation manifest |
| --- | --- | --- |
| `scripts/cumcm_core.py` | `2EB3AFEF725EA3BE09FC81CD80D1150F8662997CCDAD37561494A95C56F5EB30` | match |
| `scripts/workflow_v13.py` | `B86C5EB449322617DA8268DEF4D2D58BEAF67ABEA93FF90D7EE301B58C6E591D` | match |
| `scripts/model_evidence.py` | `77BFBF12C5B744AFF28F48043F90FF51DF2F08E91320C2B8E814F9B64768F41B` | match |
| `scripts/docx_audit.py` | `2D06BD87EC362406658F50E19E012CD87FC2393D26A51F3E667A3624D9062537` | match |
| `scripts/pdf_audit.py` | `6169704A4C76298E8B533C28A445F484E601B5412AF271312F962BC4C39940B0` | match |
| `scripts/citation_audit.py` | `A220E853E832B975E66DD4C937441BAA34D4A1369B66D25DADC5BBF59261AD24` | match |
| `scripts/supporting_materials.py` | `8E4D1BDC1653E94C552DDA8BD8F865AD610FF0F5DDC673DDBA53004B15EE8B01` | match |
| `scripts/office_common.py` | `99B38CB6FE0F39A4AC2E3A96327FF3C480946B55CAEDD82FDCEBB61C1FA0525F` | match |
| `scripts/office_formula.py` | `A3C573C4B63F13ACD155717B2C2FF7FE72B10DAA741A602C046E63F1265A3B86` | match |
| `scripts/workflow_policy.py` | `347215045B0933FC5FB7384D5D42619F5E6FDBBD32DC2E2BB96145067104A35B` | match |

| Target | Source symbols and original lines |
| --- | --- |
| `cumcm_core.py` | `ParameterEntry` (671-708), `FormulaCodeAuditEntry` (712-741), `EvidenceMapEntry` (745-774), `ArtifactRecord` (956-979), `ValidationCheck` (983-999), `ModelSpec` (1003-1077), `ActivationRecord` (1149-1199), `ParameterSet` (1203-1250), `ProvenanceEdge` (1254-1273), `RunRecord` (1277-1406), `seal_record` (167-179), `verify_sealed_record` (194-210), `validate_modelspec_structure` (1731-1830), `validate_parameter_entries` (1833-1874), `_parameter_contract_errors` (2115-2144), `_data_manifest_errors` (3433-3472), `_code_manifest_errors` (3475-3525), `_repeat_ledger_errors` (3528-3558), `_run_validation_report_errors` (3561-3702), `_evidence_claim_errors` (4412-4524), `impact_analysis` (5600-5628) |
| `workflow_v13.py` | `RequirementEntry` (104-133), `ProblemContract` (137-169), `AmbiguityEntry` (173-193), `AssumptionEntry` (197-221), `HumanDecisionEntry` (225-249), `AuditFinding` (253-270), `_contract_validation_errors` (498-591), `validate_data_contracts` (1118-1194), `_validation_plan_errors` (1219-1242) |
| `model_evidence.py` | `preprocessing_scope_errors` (14-56), `temporal_split_errors` (59-93), `check_semantic_evidence` (96-154), `audit_semantic_evidence` (157-187) |
| `docx_audit.py` | `audit_docx` (415-704) |
| `pdf_audit.py` | `audit_pdf` (302-468) |
| `citation_audit.py` | `audit_citations` (270-556) |
| `supporting_materials.py` | `validate_manifest` (179-366), `audit_supporting_zip` (428-517), `audit_docx_appendix` (579-666) |
| `office_common.py` | `docx_structural_facts` (336-374), `extract_docx_text` (309-318), `scan_sensitive_text` (321-333) |
| `office_formula.py` | `formula_bookmark_name` (192-204) |
| `workflow_policy.py` | `mode_of` (15-19), `policy_errors` (26-44), `visual_reviewer_errors` (89-102) |

### Template byte provenance

| Template | Source SHA-256 | Migration |
| --- | --- | --- |
| `activation_record.yaml` | `022AFD9D6A6D0EF2F09885844F722144CC0AFA8DB06D80F59CCB3805CE8403CE` | byte-identical |
| `code_manifest.yaml` | `AE07280E5A6B11B253DFFC4C6E78BC46E5E0F39F117751CC3E2157A6E422C7C8` | byte-identical |
| `data_manifest.yaml` | `254DFC541334FEE5863722DBF786B9BF5625953DE04D91600B9F762D4726F047` | byte-identical |
| `data_split_plan.yaml` | `6C0DC663131349EC152367B576B2E8CEB73EC23E9AC70EEDEE54ED6EC2379F87` | byte-identical |
| `dataset_passport.yaml` | `94BC35F4556596DE387D10730F730C2A7EC1D59A4CE89858DA639E1D57BB8312` | byte-identical |
| `evidence_map.csv` | `D08F9045E6B784875185CA0041F4EDA9662E518288F898E20FC60C66E364F72F` | byte-identical |
| `formal_run.yaml` | `12922A94F89CC92E8C50DEACE6C9C9726A2ECE9DAC9633B4E3C245657CB04645` | Run status default only: completed -> not_executed |
| `formula_code_audit.csv` | `58BD8621623F4F2DACE64FED97D110F0AED1521ECD802B812A090C1FBE41380A` | byte-identical |
| `modelspec.yaml` | `DC225892C9ED2110E908D6745C5CEA327BB5FD199BFBEE0FBC0485E10347AD49` | byte-identical |
| `parameter_set.yaml` | `1B2BC39C0C0DC03764C8B3EF66987BC3C1378A55DBE6630265059635C78C741D` | byte-identical |
| `parameter_sources.csv` | `4A72B9F7AF4A416995B0414FC648F8BF735A96745FF339BF451B2C93D66310BE` | byte-identical |
| `problem_contract.yaml` | `5D5D00010AA1E9B7D3DF92F13DCB4D963EC584ECBC2AD6DE85BBE6BEBF1E403E` | byte-identical |
| `provenance_edges.csv` | `7ACA9689AAEC1AEE17D221869F46451F66AF17DEEB726CB02D9E8C7B9E6D9964` | byte-identical |
| `raw_data_inventory.yaml` | `F7BC1E52AA338ECD8557EE9750E35C1C58C585017C2777E4BCD5DBAC27EE2D4E` | byte-identical |
| `reference_registry.yaml` | `02912C2B1B2DDF97BCEC3A3592C97180F6BC717DA7CCEA405A77AE2ED8213185` | byte-identical |
| `repeat_ledger.yaml` | `30943FBB8184A7424F238D2B5C77CD9AB4081B46E2C3F44F4BD9DCC2914FF983` | byte-identical |
| `run_config.yaml` | `6D835FE32549AA035B8E45E3203769F6590DD894FED1715433BF533A4BCB0EA4` | byte-identical |
| `run_validation_report.yaml` | `D7C25F93042EFAE8EA959752C3B398A7B6275BFA882E18490EFDD8F581E50A4B` | byte-identical |
| `supporting_materials_manifest.yaml` | `A2B920B1F1E173AD44E996BA821FBD579DB1755832CD0AFE077A16311B80BE54` | byte-identical |
| `validation_plan.yaml` | `31530CD2CDA38E3DA7F340D00EFDA3EF3ADD84A9C7043389335C7FC6D1B93104` | byte-identical |
