# Generic / Custom Competition Pack

`generic` 与 `custom` 加载同一未核验起点。自定义赛事不需要修改 Core 的枚举或数值阈值：复制本目录到项目内，编辑 `pack.json` 并用其路径加载。

必须给规则明确届次与来源。默认的空来源、空规则、`rules_year=null` 会阻止生成规则锁。原有三赛事 Stage、Critic、模板与经验资料继续保留；通用包不假装拥有未制作的赛事专用 LaTeX 模板或权重。
