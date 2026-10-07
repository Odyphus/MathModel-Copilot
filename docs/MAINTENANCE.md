# 维护与候选构建

版本展示 `0.2.0-preview.1`，Python 分发按 PEP 440 使用 `0.2.0rc5`。它们是同一候选，不是两个发布。使用 rc5 保持 Python 包版本顺序高于原 rc4；Preview 是用户可见阶段名称。元数据维护入口：`pyproject.toml`、`src/mathmodel_copilot/__init__.py`、`.codex-plugin/plugin.json`、`RELEASE_METADATA.json`、README 与 Skill 展示。

## 资源和打包

`release_support.py` 是 wheel、sdist 和 source-review ZIP 的共同白名单。wheel 保留 `_payload/scripts`、`_payload/competitions`、`_payload/templates`、`_payload/references`、`_payload/dashboard` 的相对关系。launcher 不改变 cwd，不在安装目录写项目事实。

`assets/status-demo.svg` 是旧上游的阶段导航示意，保留在内部产品副本，清洁 ZIP/wheel/sdist 均排除。它不代表当前 Dashboard，也不能把其阶段比例理解为当前需求完成率。清理不删除或改写历史证据。

`tools/build_release.py` 只生成本地评审包，拒绝 `--public`。它不上传、不发布、不修改许可证状态。ZIP 固定成员时间、排序和权限，包含逐文件 SHA-256 清单并回读 CRC/哈希。输出目录必须为空或不存在，避免覆盖已有包或证据。

```console
python tools/build_release.py --output ../fresh-release-directory
python -m pip install ".[build]"
python -m build --wheel --sdist --outdir ../fresh-dist-directory
```

构建前冻结源文件，构建后不要混用旧结果。`tools/verify_install.py` 支持从白名单源码快照或实际 review ZIP 验证。它在新目录回读 CRC、完整文件集合和 SHA-256，构建 wheel/sdist，再从 sdist 重建 wheel 并比较所有成员；随后在干净 venv 安装，运行 init/status/demo、CLI Dashboard 服务、资源检查和可选 Skill 兼容安装，最后卸载并核对工作区保留。它也验证旧 schema 迁移时原始字节备份。报告只证明实际执行的候选快照，不替代全量回归或完整历史验收。

```console
python tools/verify_install.py --output ../fresh-install-verification
python tools/verify_install.py --archive ../fresh-release-directory/MathModel-Copilot-v0.2.0-preview.1-source-review.zip --output ../fresh-unzip-verification --work-dir ../fresh-unzip-work
```

验收需在已安装 `build` extra 的环境运行；候选安装环境由工具另建。证据与工作目录须互相独立、为空且位于源码树外；工具拒绝覆盖已有结果。`result.json` 记录执行环境、候选与分发包哈希、每项实际状态和剩余发行阻塞。ZIP 构建报告的 `installation` 初始为 `not_executed`，不能单凭打包成功宣称安装通过。

Linux 系统 Python 若缺少 `ensurepip`，可给验收命令加 `--virtualenv <已独立取得的 virtualenv.pyz 路径>`。该方式用专属 app-data 和内置 seed 包创建新环境，关闭下载、周期更新和 `.venv` 重定向；报告记录启动器哈希。该启动器是独立构建工具，不随候选打包，也不会修改系统 Python。

完整内部回归在含已授权历史附件的独立副本执行；清洁发行源码不伪造这些附件。贡献者 CI 默认记录常规回归及缺依赖跳过，另有显式完整历史验收步骤说明。远程 CI 仅配置时写 `not_executed`。

## 可选浏览器检查

可选浏览器回归使用 Node 和 Playwright，仅是维护工具，不是核心或 Dashboard 运行依赖。先为真实 demo 或历史案例启动 Dashboard，再执行 `node tools/verify_dashboard_ui.js --url http://127.0.0.1:8765 --output ../new-ui-verification --channel chrome`；使用 Playwright 自带 Chromium 时省略 `--channel`。调用环境应已安装 Playwright（也可通过 `MATHMODEL_PLAYWRIGHT_MODULE` 指定现有模块）。该检查从真实 API 取得需求定义与任务前置/产出并检查实际页面、中文可读性、本机范围与往返操作，保存资源哈希、截图和只读前后对照。没有符合条件的前置任务时会明确记为不适用，不能据此宣称任务导航通过。

## 发布阻塞

权利未确认、维护者/仓库缺失、必要技术验收受阻或没有公开授权时，仍交付 RC 和证据，不变更 `published`。真正发布前人工核对来源处置、最终包哈希和授权；本工具没有自动公开路径。
