# CSV/XLSX 数据入口

在 Stage 2/4 读表、或 Stage 5 首次运行前按需加载。先从题面确定列、单位、缺值策略和时标含义，再生成解释文件；工具不会猜这些条件。模板是 `templates/copilot/table_spec.json`，示例日期与数字须替换，不能当作真实附件。

## 两步使用

```bash
python <skill-root>/scripts/copilot.py --workspace <project> data inspect --spec table_spec.json
python <skill-root>/scripts/copilot.py --workspace <project> data prepare --spec table_spec.json --output normalized/Q1/v1
```

`inspect` 只读，预览最多 5 行及位置/填充示例，标明截断。`prepare` 要求新目录，生成 `normalized.csv`、完整 `report.json` 和 `data_contract.json`；不覆盖附件，不修改建模权威状态，不宣称模型正确。

取得实际题意合同 ID 与当前 revision 后，沿用已有登记入口：

```bash
python <skill-root>/scripts/copilot.py --workspace <project> register --kind DataContract --key data.Q1 --payload normalized/Q1/v1/data_contract.json --depends <current-problem-contract-id> --expected-revision <current-revision>
```

登记时重读附件，重算转换并比较输出与报告。原附件、解释文件、归一化文件和报告全部进入已有 inventory；既有漂移机制使相关运行和结果需要重检查。不要手改归一化文件或报告后续用旧合同。新数据用新输出目录和同 key 新版本。

## 解释字段

| 字段 | 必填与含义 |
|---|---|
| `schema_version`、`question` | `1.0`、`Q1` 等实际所属小问 |
| `source.path` | 安全项目相对路径，用 `/` |
| `source.sheet` | XLSX 必填，明确哪张工作表 |
| `source.header_row`、`encoding` | 表头默认第 1 行；CSV 默认 UTF-8，GBK 须明确声明 |
| `columns[].name/source/type` | 输出列名、原表头、`number/integer/string/date/time` |
| `unit/output_unit` | 数值列源单位必填，无量纲填 `1`；不转换可省输出单位 |
| `nullable` | 默认 false；明确 true 时保留缺值，不能补零 |
| `fill` | 默认 reject；日期可明确 forward，或仅在 XLSX 合并区域内用 merged；测量列禁止前向填充 |
| `format` | 文字日期的格式，默认 `%Y-%m-%d`；Excel 日期/time 类型直接规范化 |
| `min/max` | 可选，归一化输出单位下的有限边界；不是自动异常值清洗 |
| `unique_keys` | 可选，已声明列组成的唯一键；缺失与重复都报错 |
| `time_axis` | 使用时间槽或功率转能量时声明日期/时间列、start/end 时标、分钟粒度、首槽起点与总槽数 |
| `power_basis` | 功率转能量须为 `interval_mean`，即区间平均功率；瞬时采样须先有单独且有依据的积分/近似方案 |
| `split` | 可选，沿用既有 DataSplitPlan；拟合/预测必须给出实际切分，不能使用默认“不适用切分” |

数值换算仅支持 W/kW/MW、Wh/kWh/MWh 同量纲缩放，以及已声明区间平均功率×时长到能量。其他明确且相同单位保持原值，跨单位换算不支持就报错。10 分钟平均 60 kW 对应 10 kWh，是算术例，不是赛题结果。

时标 `end` 表示时点标注前一槽，`start` 表示后一槽；`0:00+1` 与 `24:00` 明确跨日。槽位必须从声明起点连续、唯一、按序，并与总数吻合。转换记录保留原行/列、日期填充锚点、单位因子和时标解释。读回按实际序列逐槽、逐字段比较，序列化容差为 0；数学求解的容差另在 ValidationPlan 声明。

## 支持边界

CSV 读入使用标准库；XLSX 需要 openpyxl（`analysis` extra）。数值序列号不猜成时间，带时刻的日期不静默截断，公式没有缓存就报原表位置并要求先重算。缺槽、乱序、重复表头、未知字段拼写、非有限数值及未获准的缺失值均不能通过。

本轮只支持单张规则表及无时区的本地日历时间。不包括 XLS、OCR、多表拼接、夏令时/时区换算、任意单位系统、储能物理模型或赛题语义自动确认。解析通过只证明声明范围内的数据转换；单位含义、平均功率假定和建模取舍仍须有题面或单独记录支持。
