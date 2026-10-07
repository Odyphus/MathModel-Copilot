# 0.3.0-preview.2 验收记录

本轮基于公开 main 的 a9ae360855c70f7a6738854fe58463ac0eb93a7b 更新，并保留随后 a5884049f0dfd5834af9ef57b789a7256a288795 新增的固定 latest 下载入口；保留既有内核与 schema 4.0，不修改已有用户安装或比赛项目。旧下载包保留，新包与发布源码按运行文件清单逐项校对。

## 本轮修复与增加

- 工作台隐藏哈希和内部编号时，保留真实整数、小数、科学计数法及相邻单位，保留阻塞理由中的中文小问。
- 总览合并共同事项时核对语义、状态与来源，保留每问可展开详情；不同方案、来源或状态不合并。
- 待处理事项显示实际原因与假设，重大影响排在优先位置，不把编号当事实。
- 新增可选私有队伍仓库开通引导：登录检查、空私有建仓、按用户名邀请写权限、独立回读。邀请发出与接受分开；不自动上传文件或改变 Store。
- 同步公开仓库信息、当前版本和安装说明，区分源码 Python 安装与单入口 Skill 运行包。

## 实际测试

环境为 Windows / Python 3.12。所有回归所需 Python 包已安装在独立测试目录，未改用户现有安装。

| 检查 | 结果 |
|---|---|
| Python 全量回归 | 856 项，850 通过，0 失败、0 错误，6 跳过 |
| 工作台 JavaScript 回归 | 118/118 通过，0 跳过；含真实历史投影复放 |
| 编译与三个赛事 doctor | 通过；doctor 使用 `--skip-tools`，不证明外部渲染器可用 |
| Skill 三个源码入口结构检查 | 通过；运行发行版仍只有一个发现入口 |
| ZIP 新目录安装与重复安装 | 通过；重复安装拒绝且原字节保持不变 |
| 标准库真实合成演示 | 5/5 需求核验，43200 步独立检查；正式提交 Ready 为 false |
| Chrome 四个工作台入口 | 均有内容，0 页面错误、0 失败 HTTP 响应 |
| 390px 窄屏与只读状态 | 无横向溢出，权威文件字节不变 |
| GitHub 登录预检 | 真实 GET /user 返回 HTTP 200；无远端写入 |
| 私有建仓/邀请 | 离线 API、两层 CLI 与拒绝路径回归通过；未向真人发邀请 |

独立审查额外复放数值/单位/中文归属与重大影响排序反例；另发现权限与邀请回读只比较名称的身份缺口，已补齐不可变用户、仓库 ID 核对及正式负向测试，并重新审查。详细程序摘要见 [验收摘要](https://github.com/Odyphus/MathModel-Copilot/blob/main/docs/verification/v032-prepublish-summary.json)。

首轮全量测试因个人目录位于外层 Git 树，以及沙箱对真实路径解析的拒绝而中止，原日志保留，没有将它计成代码通过。使用非 Git 个人临时目录及正常宿主测试环境后完整重跑；没有削弱产品保护。

首次完整 856 项运行还发现 2 个过时的 README 装饰断言，要求已由用户移除的横幅与版本徽章。保留确认后的正文，将断言更新为实际版本说明、下载入口与全部本地链接检查，模块复放通过后，再将全部 856 项按独立模块重跑（3 个隔离进程，每模块仍使用 `tools/run_regression.py` 并核对同一来源清单）。运行代码没有为此修改，旧失败记录保留。

### 主动跳过清单

- `test_copilot_benchmark.BenchmarkIntegrationTests.test_checker_rejects_forged_completed_count`：historical_fixture_missing: CUMCM-2018-Problem-B-English.pdf, CUMCM-2018-Problem-B-English-Appendix-1.pdf, Case_1_ result_E.xls, Case_2_ result_E.xls, Case_3_ result_1_E.xls, Case_3_ result_2_E.xls, official_parameters.json; obtain authorized assets in a private test copy; see docs/HISTORICAL_FIXTURES.md
- `test_copilot_benchmark.BenchmarkIntegrationTests.test_existing_workspace_is_preserved`：historical_fixture_missing: CUMCM-2018-Problem-B-English.pdf, CUMCM-2018-Problem-B-English-Appendix-1.pdf, Case_1_ result_E.xls, Case_2_ result_E.xls, Case_3_ result_1_E.xls, Case_3_ result_2_E.xls, official_parameters.json; obtain authorized assets in a private test copy; see docs/HISTORICAL_FIXTURES.md
- `test_copilot_benchmark.BenchmarkIntegrationTests.test_real_smoke_covers_two_questions_without_formal_ready`：historical_fixture_missing: CUMCM-2018-Problem-B-English.pdf, CUMCM-2018-Problem-B-English-Appendix-1.pdf, Case_1_ result_E.xls, Case_2_ result_E.xls, Case_3_ result_1_E.xls, Case_3_ result_2_E.xls, official_parameters.json; obtain authorized assets in a private test copy; see docs/HISTORICAL_FIXTURES.md
- `test_render_guard.CumcmLatexGuardTests.test_abstract_overflow_fails_compilation`：XeLaTeX with ctexart.cls is not installed
- `test_render_guard.CumcmLatexGuardTests.test_body_over_thirty_pages_fails_compilation`：XeLaTeX with ctexart.cls is not installed
- `test_render_guard.CumcmLatexGuardTests.test_original_template_compiles_a_short_electronic_paper`：XeLaTeX with ctexart.cls is not installed

依赖缺失、主动跳过、代码失败分别记账。没有以缺少赛题授权附件为由伪造历史完整验收。

## 尚未验证

真实队伍私有建仓、队友收到并接受邀请、实际远端资料接力仍需具体目标和授权后验收。页面直接唤醒当前 AI、真实反馈 Issue 创建与回读、最终 PDF 编译与人工视觉核验、本轮 Linux/macOS 实跑、不同宿主的自动注册及真人首次体验未纳入本轮通过项。GitHub Actions 未执行，不把配置文件视作 CI 通过。

已有公开访问事实与完整来源许可确认分别记录，见 [许可范围](../LICENSE_SCOPE.md)。本版本仍为 Preview，不增加正式提交、跨电脑实时同步或统一模型表现的承诺。

## 复核方式

```text
python tools/run_regression.py --output ../fresh-regression-evidence
node --test tests/test_*.js
python -m compileall -q scripts templates/shared/code_starter
python scripts/doctor.py --competition cumcm --skip-tools
python scripts/copilot.py --workspace ../new-demo demo
python scripts/copilot.py --workspace ../new-demo dashboard --port 8765
```

涉及个人经验的测试临时目录必须位于 Git 树之外，可设置 `MATHMODEL_PRIVATE_TEST_TEMP`；这是个人信息保护约束。完整日志含本地路径，公开摘要保留判据和结果，原始用户过程不上传。
