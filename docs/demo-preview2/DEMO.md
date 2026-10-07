# 一次参数变化，怎样影响结果与论文

保留原演示日期：2026-10-06。当前产品为 0.3 Preview；本页保留旧版实际证据，未将截图重标为新版本。

这是 MathModel Copilot v0.2.0-preview.2 的实际程序与浏览器演示。使用内置合成交通模型，没有调用 AI 生成结果，没有拦截或替换页面数据，也没有修改产品源码。它展示运行、核验、变更失效与恢复，不是完整赛题解答或现场交通测试。

## 1. 在新目录运行

在产品目录执行：

```sh
python scripts/copilot.py --workspace ../demo-project demo
python scripts/copilot.py --workspace ../demo-project dashboard --port 8765
```

`demo-project` 必须为空或不存在。第二个命令保持运行时打开输出的本机地址。

该示例建立流体排队模型，在 3 种合成需求模式、3 个需求倍率下，分别枚举 8 个控制方案，共 72 组方案。每组模拟 600 秒。独立检查器核对 43,200 个时间步；它不导入求解器来充当自己的检查依据。

检查包括流量守恒与非负状态、能力与控制规则、有限枚举的选择及导出数值、技术摘要的约定内容。检查摘要存在必要说明，不等于专家认可摘要质量。

![初次运行后的总览](https://github.com/Odyphus/MathModel-Copilot/blob/main/docs/demo-preview2/assets/01-overview.png?raw=true)

![按项查看示例要求](https://github.com/Odyphus/MathModel-Copilot/blob/main/docs/demo-preview2/assets/01-requirements.png?raw=true)

第一次实际运行的结果保存在 [01-demo.json](evidence/01-demo.json)。`synthetic=true`，`old_results_reused=false`，5 项示例要求均关联当前有效结果。当前仍是历史题目练习，正式提交状态为 false。

## 2. 改变一个参数

使用正式 Runtime 事务，将 ParameterSet 中的假定通行能力由 0.8 vehicle/s 改为 0.7 vehicle/s，模型结构不变。系统生成新的参数版本；没有手工编辑权威状态文件。

这一时刻不重新计算。只读查询和页面均显示 0/5 项要求已核对，旧结果、旧结论和旧章节需要重检。

![新参数使旧依据需要重新检查](https://github.com/Odyphus/MathModel-Copilot/blob/main/docs/demo-preview2/assets/02-overview.png?raw=true)

事务和实际状态见 [02-parameter-change.json](evidence/02-parameter-change.json)。

## 3. 重新计算并核验

执行新运行，绑定新参数，实际执行同一独立检查器，再将新结果关联到对应要求。5/5 项要求恢复为已核对。

![复算后的项目总览](https://github.com/Odyphus/MathModel-Copilot/blob/main/docs/demo-preview2/assets/03-overview.png?raw=true)

旧论文段落保留为需要重检。更新计算与更新论文依据是不同操作，本演示没有替作者重新登记旧段落。新运行、核验、指标与旧章节状态见 [03-rerun.json](evidence/03-rerun.json)。

| 项目 | 初次运行 | 参数修改后 | 新计算核验后 |
|---|---|---|---|
| 假定通行能力 | 0.8 vehicle/s | 0.7 vehicle/s | 0.7 vehicle/s |
| 已核对要求 | 5/5 | 0/5 | 5/5 |
| 旧章节来源 | 已核对 | 需要重检 | 仍需重检 |
| 正式可提交 | 否 | 否 | 否 |

## 复现参数修改与复算

`evidence/extend_demo.py` 是本次演示辅助脚本，调用产品已有 Runtime API，不是产品新增命令。在完成上面的初次 demo 后，可分别执行：

```sh
python evidence/extend_demo.py "PATH_TO_PRODUCT" "PATH_TO_DEMO_PROJECT" evidence change
python evidence/extend_demo.py "PATH_TO_PRODUCT" "PATH_TO_DEMO_PROJECT" evidence rerun
```

这两条命令从本素材目录执行。`PATH_TO_PRODUCT` 替换为解压后含 `scripts/` 的产品目录绝对路径；`PATH_TO_DEMO_PROJECT` 填写第一步创建的同一个演示项目的绝对路径，避免切换目录后指向另一个项目。先运行 change 查看页面，再运行 rerun。不要在真实比赛项目中演示参数替换。

本机截图由实际 Chrome 页面生成。三轮浏览器记录均确认页面读取前后权威文件与关联文件观察未变，且无浏览器脚本错误。演示使用合成输入，浏览器响应来自真实本地服务。

## 这段演示能说明什么

能说明预先登记的计算与检查实际执行、参数更新撤回旧依据的有效性、新计算不会自动让旧论文通过。不能证明模型适合真实道路、枚举解是全局最优、论文已经过人工审定，也没有测试真实 AI 从页面被唤醒。

公开传播可以使用前三张概览截图及上述状态对照。无需把内部运行编号、哈希和原始长数值放在文章正文中。
