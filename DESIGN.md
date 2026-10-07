---
name: "MathModel Copilot"
description: "可核对状态与来源、按需记录意见的浅色本地工作台"
colors:
  canvas: "#fafaf7"
  surface: "#fff"
  sidebar: "#f0f2ee"
  ink: "#202c27"
  muted: "#58645d"
  line: "#dce2da"
  accent: "#245a43"
  accent-soft: "#e7efe9"
  warn: "#79500b"
  warn-soft: "#fff4da"
  bad: "#a23535"
  bad-soft: "#fcecea"
  quiet: "#eef0ed"
  focus: "#146a9a"
typography:
  headline:
    fontFamily: "\"Segoe UI\", \"Microsoft YaHei\", \"PingFang SC\", system-ui, sans-serif"
    fontSize: "28px"
    fontWeight: 650
    lineHeight: 1.4
    letterSpacing: "-0.02em"
  title:
    fontFamily: "\"Segoe UI\", \"Microsoft YaHei\", \"PingFang SC\", system-ui, sans-serif"
    fontSize: "18px"
    fontWeight: 650
    lineHeight: 1.5
  body:
    fontFamily: "\"Segoe UI\", \"Microsoft YaHei\", \"PingFang SC\", system-ui, sans-serif"
    fontSize: "15px"
    fontWeight: 400
    lineHeight: 1.65
  control:
    fontFamily: "\"Segoe UI\", \"Microsoft YaHei\", \"PingFang SC\", system-ui, sans-serif"
    fontSize: "13px"
    fontWeight: 400
    lineHeight: 1.6
  badge:
    fontFamily: "\"Segoe UI\", \"Microsoft YaHei\", \"PingFang SC\", system-ui, sans-serif"
    fontSize: "11px"
    fontWeight: 600
    lineHeight: 1.5
  technical:
    fontFamily: "Consolas, \"SFMono-Regular\", monospace"
    fontSize: "12px"
    fontWeight: 400
    lineHeight: 1.65
rounded:
  status: "4px"
  control: "6px"
  surface: "8px"
spacing:
  base: "8px"
  compact: "12px"
  normal: "16px"
  reading: "24px"
  section: "28px"
  layout: "32px"
components:
  button-primary:
    backgroundColor: "{colors.accent}"
    textColor: "{colors.surface}"
    typography: "{typography.control}"
    rounded: "{rounded.control}"
    padding: "7px 13px"
  button-secondary:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    typography: "{typography.control}"
    rounded: "{rounded.control}"
    padding: "7px 13px"
  button-quiet:
    backgroundColor: "transparent"
    textColor: "{colors.muted}"
    typography: "{typography.control}"
    rounded: "{rounded.control}"
    padding: "5px 7px"
  search-input:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    typography: "{typography.control}"
    rounded: "{rounded.control}"
    padding: "8px 11px"
  navigation-selected:
    backgroundColor: "#dee9df"
    textColor: "{colors.accent}"
    rounded: "{rounded.control}"
    padding: "12px 14px"
  status-verified:
    backgroundColor: "{colors.accent-soft}"
    textColor: "{colors.accent}"
    typography: "{typography.badge}"
    rounded: "{rounded.status}"
    padding: "3px 7px"
  notice-warning:
    backgroundColor: "{colors.warn-soft}"
    textColor: "{colors.warn}"
    typography: "{typography.control}"
    rounded: "{rounded.surface}"
    padding: "16px 18px"
  object-link:
    backgroundColor: "transparent"
    textColor: "{colors.accent}"
    typography: "{typography.control}"
---

# Design System: MathModel Copilot

## Overview

**Creative North Star: "项目审阅桌"**

系统以“项目审阅桌”为视觉方向：平面的暖白阅读区、安静的浅灰绿导航、石墨正文和节制的森林绿选择态。区块依靠标题、留白和细分隔线组织，精确标识保持等宽，状态始终同时给出文字。

面向需要连续查证的中文工作场景，优先保证密集记录可扫描、来源关系可往返和窄窗口可重排。除临时详情阅读区外不制造层叠深度；没有装饰图表、远程字体或品牌插画。

本文件从已实现代码提取，来源为 dashboard/styles.css、dashboard/app.js 与已检查的原创预设。2026-10-05 的设计结论属于独立内部审查，没有用户批准记录；该审查完成时真实数据尚未接入。后续适配、字段对照和真实运行验收由独立记录证明，本文件不替代它们。

**Key Characteristics:**

- 平面阅读表与细线分隔
- 中文层级和等宽精确标识并存
- 选择态克制，风险态明确
- 按可用空间重排，保留完整对象内容

## Colors

纸白和浅灰绿建立安静的阅读底色，森林绿指示选择与正向状态，琥珀和红色只伴随明确风险文字。准确值以前置 tokens 为准。

### Primary

- **森林绿（accent）**：选中导航、主按钮、可进入对象和已核验状态的文字。
- **浅绿状态底（accent-soft）**：正向状态和信息提示的轻底色，不替代文字含义。

### Neutral

- **纸白底色（canvas）与阅读白（surface）**：页面与临时阅读面。
- **浅灰绿导航（sidebar）**：全局导航的稳定背景。
- **石墨正文（ink）与低调次文字（muted）**：主内容与来源、时间等附属信息。
- **细分隔线（line）与安静灰底（quiet）**：行界线及中性提示。

### Status and focus

- **深琥珀 / 浅琥珀底（warn / warn-soft）**：缺口、受阻及失效。
- **深红 / 浅红底（bad / bad-soft）**：失败、超时、中断及缺少输出。
- **蓝色键盘焦点（focus）**：键盘位置，不承载业务状态。

**The Explicit State Rule.** 颜色必须附着于可读状态文字；同一种绿色不能独立证明执行、核验或提交已完成。

## Typography

中文及控件共用前置 sans 字体栈，不下载字体；只有明确展开的文件原文和数据使用等宽栈；ID 与哈希保留在诊断导出中。系统字体是当前中文 Operate 界面的明确约束，不是通用展示字体规范。

- **Headline**：页面主标题；窄于 880px 时降为 24px。
- **Title**：区块标题；当前工作标题采用 17px，详情主标题采用 23px。
- **Body**：基础正文；说明段落与操作控件通常采用 control 的较紧密尺寸。
- **Control**：按钮、输入与对象标题；状态文字采用 badge。
- **Technical**：仅用于明确打开的原始文本和计算数据；普通列表不展示次级 ID。

行内数值使用 tabular-nums。说明文字最大 75ch，标题均衡换行；精确字符串允许任意必要断行，不为了对齐丢失内容。

**The Exact Identifier Rule.** 等宽只用于数据和技术标识，不把全部叙述变成终端风格。

## Layout

桌面由 220px 导航与弹性工作区构成，主区内边距 32px，双列约 1.9:1、间隔 32px。小于 1120px 时导航收至 190px、内容内边距 26px；小于 880px 时导航成为顶部可横向滚动的一行，主区变为单列。

工作区还使用自身宽度判断：可用宽度小于 860px 时，双列按阅读顺序展开。此规则同时服务窄窗和 CSS 放大，不能用它声称原生浏览器缩放已经验收。小于 520px 时表格按记录逐条排列，并显示字段名称；详情占满窗口宽度。大于 1700px 时主区最大宽度 1570px，边距 48px。

间距以 8px 为基本节奏，密集行采用 12–15px 上下留白，区块间隔 28px。优先保持相关内容靠近、区块之间清楚分隔；不要用同样大小的卡片重建表格。

## Elevation & Depth

页面区块默认平面，依靠细线和底色区分。唯一主要阴影属于临时详情阅读区：侧向柔和阴影为 -12px 0 30px #172b191a，背景遮罩为 #13221a30。阴影表示当前阅读层，不作为普通行或区块装饰。

## Shapes

小状态标签、操作控件与提示面分别使用前置圆角 token。边界以 1px 细线为主；状态小底块不是大面积胶囊。图标为原创 24px SVG path，通常显示 18px、描边 1.65px；状态图标显示 12px，导航选中时增加描边力度。没有第三方品牌图片或字体文件。

## Components

### Buttons

主按钮用于明确的查看操作，森林绿底配白字；次按钮白底加细边，轻按钮透明。按钮最小高度 36px，focus-visible 使用 3px 焦点线及 3px 外偏移。禁用时降低透明度；支持减少动态效果的偏好。

### Inputs / Fields

搜索框与 select 使用白底、细边和相同圆角；输入 caret 跟随森林绿。占位文案保持可读对比。搜索匹配对象 ID、标题以及界面显示的类型和状态；排序标签说明实际排序依据。

### Navigation

带文字的细线 SVG 与稳定选中底色构成导航。选中项加重文字和图标，不增加装饰边条。窄窗口保持全部入口可横向移动，并保留原来的页内筛选。

### Status labels and notices

状态由图标、明确文字和底色共同表达；中性、正向、风险、失败各自有清晰含义。提示面使用轻底色和细边，不以醒目色面替代失败原因或恢复说明。

### Object rows and detail reader

对象采用可读中文名称；状态与说明分列，内部 ID 不进入普通阅读界面。详情宽度为 min(550px, 92vw)，窄于 520px 时铺满；顶部操作条固定，正文按状态、标题、关键说明、适用范围与按需展开的关联内容和文件排列；原始诊断另行导出。切换对象重置阅读位置，关闭后恢复触发控件焦点。所有记录以纯文本呈现；示例与真实观察有可见区别。

### Loading, empty and failed observations

首次加载使用低幅度底色变化，prefers-reduced-motion 下静止。后续刷新保留阅读位置与已展开内容，同时在页头和已打开的详情中说明这是上次观察、正在重新核对；更新后重新解析当前记录，失败则撤下旧事实。空内容给出可执行的下一步，错误状态说明原因与重读入口。

变化摘要和待判断事项沿用原有细线分隔结构。摘要区优先失效与成果变化；待判断区按候选解释、影响和已有依据组织，讨论提纲按需展开。没有采用按钮或自动批准；专业模型名称与必要单位保留。页面可见时的本机观察不触发模型请求。

## Do's and Don'ts

### Do:

- Do 让状态同时使用文字、图标和颜色，保留失败、未知、未执行与不适用的区别。
- Do 在诊断导出中保留精确来源；普通阅读使用中文名称，长标题允许换行。
- Do 为键盘操作保留清晰焦点，关闭详情后返回原触发控件。
- Do 沿用当前组件的平面结构和留白，用现有层级增加内容。

### Don't:

- Don’t 仅靠颜色表示是否可采用或是否完成。
- Don’t 添加虚构的完成百分比、准备分数、成员头像或在线状态。
- Don’t 把历史或演示记录装饰成真实核验与正式提交成功。
- Don’t 为普通区块增加重阴影、嵌套卡片或外观仿真的材质。

## Local workbench revision

四个主导航为项目总览、各问进展、成果与依据、论文准备。首页优先下一步和按问进度，不使用汇总指标卡。模型方案和题目目标嵌入小问；人工待确认事项仅在真实记录存在时展示。空的可选区块隐藏，本机变化移至页尾辅助入口。页头只展示可读项目、模式及读取时间。界面不宣称团队实时同步，旧的六页对象浏览结构由内容驱动的四页取代。详情折叠用于次要来源与文件，必要的错误原因和适用范围仍可找到。
