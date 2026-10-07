# Generic / Custom 赛事规则

此包没有默认的已核验赛事规则。它不提供页数、格式、AI政策或文件大小的“通用官方值”。

在项目目录中复制此包，设置独立 `id`、`rules_year`、官方来源、规则及验收项。为每条规则标记 `official_rule`、`maintainer_default`、`team_default` 或 `empirical_observation`。官方规则引用来源 ID；团队默认和经验观察不能伪装成官方门槛。

加载自定义 `pack.json` 后，保存适用届次的官方来源文件到项目中，再生成绑定文件哈希的规则锁。只填写 `verified=true`、网页链接或核对日期都不能生成有效规则锁。此文件是使用说明，不是官方来源快照。
