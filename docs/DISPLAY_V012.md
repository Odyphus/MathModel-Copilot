# v0.1.2 数值显示精度合同

本模块允许已经核验的结果 `182.8125` 在明确登记保留两位小数后显示为 `182.81`。原始 Result、运行记录与验收数值不变，原有数值匹配容差不变。没有合同的数字继续使用原来的证据检查；错误合同直接报错，不能退回宽松匹配。

## 数据与 API

实现位于 `scripts/copilot_display.py`，只有标准库与现有 `copilot_store.digest` 依赖，不读写文件，不创建第二套状态。Runtime 将合同保存到原权威对象的 payload 中，并沿现有 Claim → Result → Run 依赖链管理版本与失效。

```python
validate_display_contracts(cp, result_ids, contracts, *, source_errors=None)
```

- `cp` 必须来自当前可信 `state/decision_log.json` 的 `copilot` 子树。此函数不是接收任意外部 JSON 并授予真实性的接口。
- `result_ids` 是本条 Claim 明确声明的 Result 依赖集合。合同不能借用集合外的结果。
- `contracts` 是合同列表，空列表返回空绑定。最多 256 条，完全重复的合同报错。
- 可选的可信回调 `source_errors(result_id) -> list[str]` 用于调用 Runtime 的实际文件及证据检查，例如 `lambda ident: object_errors(root, cp, ident)`。错误列表非空则拒绝；布尔值、`None`、非列表返回值均不是核验收据。
- 返回现有 `numeric_bindings` 形状的列表；任一合同错误抛出 `ValueError`。函数不局部采用“其中正确”的合同。

合同恰好包含以下八个字段，字段缺失或增加未知参数均拒绝：

```json
{
  "version": "0.1",
  "result_id": "result.Q1.RUN-example@1",
  "metric_path": "/value",
  "raw_value": "182.8125",
  "display_value": "182.81",
  "format": "decimal",
  "decimal_places": 2,
  "rounding": "half_even"
}
```

| 字段 | 合同 |
|---|---|
| `version` | 固定为字符串 `0.1`，是显示合同版本，不是产品版本。 |
| `result_id` | 当前、已核验的 `ResultRecord` 对象 ID，包含具体版本。 |
| `metric_path` | 相对 `ResultRecord.payload.metrics` 的 JSON Pointer；例如 `/nested/0/score`、键 `a/b` 写成 `/a~1b`。不接受 Python 表达式、点路径、通配符或数组负索引。 |
| `raw_value` | 有限十进制字符串；必须精确等于该指针处实际 JSON 数字经 `Decimal(str(value))` 得到的值，不允许布尔、文本指标或自行改短的原值。 |
| `display_value` | 明确展示字符串，须与指定格式、位数和舍入策略的实际计算结果逐字相等。 |
| `format` | `decimal` 或 `percent`。后者仅作 fraction × 100 后附 ASCII `%`，不推断原指标单位。 |
| `decimal_places` | 整数 0–12，不接受布尔、浮点、字符串、负数或超界位数。 |
| `rounding` | `half_even` 或 `half_up`，均由 `Decimal` 确定性计算。 |

`raw_value` 按数值比较：`182.81250` 与 `182.8125` 是同一原值。它不是未经解析的原始 JSON 字面量归档。若上游 JSON 的数值经解析为 Python float，合同不能恢复解析前已经丢失的任意精度；高精度数据需要在上游结果类型中另作设计。

## 核验顺序和审计输出

1. 检查合同结构、枚举、位数和明确的原值/展示值类型。
2. 确认 Result 在 Claim 依赖中，且 kind/status 为 `ResultRecord` / `verified`。
3. 递归核对 Result 及全部依赖的 `current` 指针、对象 ID、有效状态和实际 payload hash。依赖缺失、环路、陈旧祖先、错指针、篡改 payload 均拒绝。
4. 若有可信 `source_errors` 回调，执行实际文件核验。同一 Result 在一次调用中只检查一次。
5. 按 JSON Pointer 读取有限 JSON 数字；严格比较登记 `raw_value` 与实际 metric。
6. 在独立 Decimal Context 中计算格式与舍入，不受调用者全局精度、舍入或 `Inexact` trap 影响。
7. 严格比较计算得到的展示字符串，返回可审计绑定。

`182.8125 → 182.81` 的返回值包含：

```json
{
  "text": "182.81",
  "sources": [{
    "result_id": "result.Q1.RUN-example@1",
    "metric_path": "/value",
    "value": 182.8125
  }],
  "display_contract": {"...": "完整原合同"},
  "derived_value": "182.81",
  "rounding_delta": "-0.0025",
  "rounding_delta_basis": "source_metric",
  "source_payload_hash": "实际 Result payload hash"
}
```

`rounding_delta` 始终按原 metric 单位记录。例如原比例 `0.1828125` 显示为 `18.28%`，差值为 `-0.0000125`，不是百分数单位的 `-0.00125`。合同本身也保留在绑定中，可区分原值、显示值及计算方式。

## 支持和拒绝的表示

| 原值与声明 | 结果 |
|---|---|
| `182.8125`，decimal，2 位，half_even | `182.81` |
| `2.665`，decimal，2 位，half_even | `2.66` |
| `2.665`，decimal，2 位，half_up | `2.67` |
| `-2.665`，decimal，2 位，half_up | `-2.67` |
| `9.995`，decimal，2 位，half_even | `10.00` |
| `0.1828125`，percent，2 位，half_even | `18.28%` |
| `182.8125`，decimal，0 位 | `183`，属于明确的整数显示合同 |
| `0.0001`，decimal，2 位 | 拒绝非零值被显示成零；应提高精度。 |
| `182.8125`，2 位，但写 `182.82` / `999` | 拒绝错误舍入。 |
| `182.8125`，2 位，但写 `182.810` / `1.8281e2` | 拒绝与声明格式不一致的表示。 |
| 任意 `tolerance` / `scale` / `offset` / `number_kind=year` 参数 | 拒绝未知参数；不能扩大容差或豁免数字。 |

原值文本最多 512 字符，展示值最多 1024 字符，十进制量级/指数绝对值最多 1000；指针最多 1024 字符、32 层。这些是计算与输入边界，不是数值容差。未提供任意格式化程序、表达式求值、未知舍入策略或单位缩放。

## 与 Runtime、Claim、Section 的边界

该模块证明的是“指定、仍然有效的 Result 数字按声明规则得到此展示值”。它不证明自然语言的因果关系、最优性、单位解释、统计显著性或经过舍入后的阈值断言。例如 `0.049 → 0.05` 的合法展示合同不能自动证明“原值大于等于 0.05”。科学判断仍要由原结果与正文的证据检查承担。

Runtime 对可直接识别的风险增加了一个有限门禁：存在非零 `rounding_delta`，且正文含 `<`、`>`、`≤`、`≥` 或明确比较/阈值词组时，每个发生舍入的源 Result 都须在独立 checker 实际返回的 metrics 中包含与完整 Claim 一致的结论文本。否则 numerical Claim 拒绝登记，其他类型保持 `generated`，不能取得核验状态。它使用 `comparison_status` 记录是否等待 checker 结论；另一 Result 的结论不能为该显示来源提供通行证，结论文本本身也不能豁免额外未绑定的数字。

`approximately 0.05` 这类普通近似表述仍可使用明确显示合同。简单的 `=` 或 `≈` 不被自动解释成阈值判断。该门禁不尝试覆盖全部自然语言、任意公式推导或模糊语义；结论文本绑定的是实际 checker 输出，也不自动证明该 checker 的算法本身正确。若需要可机器证明的复杂比较，应单独定义结构化 predicate 和相应验证计划。

物理文件漂移不一定已写入 `status=stale`：直接改动磁盘文件时，权威对象仍可能显示历史的 `verified`。因此，Runtime 的 Claim 登记、读取可用性和交付入口必须保留 `object_errors` 文件核验，或在本函数中传入该回调。仅运行无回调的纯函数只能证明权威对象图和数值合同，不能证明当前磁盘内容。专属集成测试实际修改了已运行输出，并确认带回调时拒绝且不偷偷改写 authority。

已有 v0.1.1 对象不含 `display_contracts` 时保持空列表语义。新增显示合同不改变旧 Run/Result、不迁移 Store、不覆写历史，也不允许用历史 Result 绕过当前版本要求。上游 ParameterSet 产生新版本后，旧 Result 的合同立即不可用。

消费返回绑定时，Claim/Section 仍应逐项核对正文中的数字；不能仅因为本条 Claim 含一个合法合同，就把其他数字、其他命题、同段或同标题的内容一起视为已核验。

## 结构编号、年份与公式常数的安全边界建议

这些语义由 Section/Runtime 所有者实现，本显示模块不提供豁免类别。

- 结构编号只能在严格语法位置识别并移除编号本身，继续检查同一行的正文。例如标题 `# 1 结果为 999` 中 `1` 可作为章节编号，`999` 仍须有结果证据；整行跳过不成立。
- 图、表、公式引用应指向已登记、实际存在的相应目标。仅写“图 999”或“常数 999”不能取得免检资格；标号的存在也不核验其后叙述。
- 题目年份和规则年份是不同事实，允许使用时须精确绑定当前 `problem_year` 或 `rules_year`，或明确的已登记来源字段。不能按“长得像四位年份”统一放行。
- 公式常数与参数应绑定当前 ModelSpec/ParameterSet 的具体数值及适用上下文；读到“常数”“系数”等标签不等于证据。公式语法与结果命题必须分开核对。

## 复现与检查记录

在冻结的 v0.1.1 上，实际 solver 读取 `n=91.40625`，独立 checker 通过加法核验 `2n=182.8125`。原版本接受原值数字、拒绝正确的两位显示 `182.81`，也拒绝虚假的 `999`。未给旧 API 硬塞新字段的实质复现保存在 `verification/display/02-baseline-rounding-failure.txt` 与 `01-baseline-rounding-facts.json`。更早一次探针向旧 dataclass 传入新字段产生的 TypeError 单独保留在 `01-baseline-rounding-failure.txt`，不冒充数值功能失败。

新模块首次 33 项测试中有 5 个输入形状子案例报非预期异常；修复为明确 `ValueError` 后，同一 33 项全部通过，记录于 `03-display-first-checkpoint.txt` 与 `04-display-after-input-fixes.txt`。其中 3 项真正经过 Runtime 执行和独立 checker；其余使用明示的合成对象图验证纯数值与依赖规则，不将合成 fixture 冒充真实运行。

随后独立集成复核增加 10 个方法：4 个 Section/DOCX 反例和 6 个比较门禁检查。四个实证缺口（带空格指数被图号解析截断、表格隐藏文本、表格内可见内容控件漏读、数值被空白拆开后误判同文）均先保留失败日志，再由对应实现所有者修复，原路径复验通过。43 个新增方法目前按组通过；具体分组、日志与全套验收边界见 `verification/display/INDEPENDENT_FINDINGS.md`。

运行时随后根据实际 profile 对一次可用性观察中的重复依赖检查消重，既不持久化也不跨独立读取复用文件结果。专属 `test_observation_v012.py` 12/12 通过，另有原 Context/Runtime/Red Team 93/93 邻近回归通过；同 cp、同 revision 下直接修改磁盘文件仍会在下一次调用发现。该优化不改变本显示 API、数值容差、权威状态或历史 Context 协议。

本模块测试命令：

```text
python -m unittest discover -s tests -p test_display_v012.py -v
```

应在可写的项目本地临时目录下运行，并设置 `TEMP` / `TMP`；原有测试文件保持不变。完整产品回归、Claim/Section 接入和论文/交付链由 v0.1.2 总验收记录汇总，本页不以模块测试代替端到端交付结论。
