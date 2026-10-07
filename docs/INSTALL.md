# 安装与首次使用

这是随当前源码交付的本地评审候选，尚未公开发布，也未完成全部来源许可确认。以下安装使用交付中的清洁源码或 wheel，不从假设存在的线上仓库下载。

## 先体验：不用安装 Python 分发包

发给内测用户时使用文件名含 `runtime-review` 的用户运行包。解压后只有根目录一个 `SKILL.md`，让 AI 读取它即可；需要注册时执行下面的显式安装工具。文件名含 `source-review` 的完整源码包用于维护、测试和插件开发，包含多个不同用途的发现入口，不应整目录复制到宿主的自动 Skill 扫描目录。

本机已有 Python 3.10+ 时，解压后可以直接读取根目录 `SKILL.md`，用 `python scripts/copilot.py --workspace ../demo-project demo` 开始真实合成演示，再用同一前缀执行 `status` 或 `dashboard --port 8765`。核心、合成示例和建模工作台都使用标准库，不需要先运行 pip。

让本地 AI 工具读取该文件是显式使用入口，不等于已完成宿主的自动 Skill 注册；也不会写入全局 Skill 目录。详细的可复制提示见 [内测使用说明](../内测使用说明.md)。练习项目放在源码之外，demo 目录必须为空或不存在。真实赛题用另一个工作区 `init`，不要混用演示状态。

## 可选 Python 分发安装

要求 Python 3.10+。建议在独立环境中安装，用户工作区放在环境和源码目录之外。

Windows PowerShell，在解包后的源码根目录：

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install --no-cache-dir .
.venv\Scripts\mathmodel-copilot.exe --version
.venv\Scripts\mathmodel-copilot.exe --workspace ..\my-project init --competition mcm
.venv\Scripts\mathmodel-copilot.exe --workspace ..\my-project status
```

Linux：

```sh
python3 -m venv .venv
.venv/bin/python -m pip install --no-cache-dir .
.venv/bin/mathmodel-copilot --version
.venv/bin/mathmodel-copilot --workspace ../my-project init --competition mcm
.venv/bin/mathmodel-copilot --workspace ../my-project status
```

若使用 wheel，把 `pip install .` 的 `.` 换成实际 wheel 文件路径；可加 `--no-deps` 证明标准库核心独立可用。源码构建需要 setuptools 与 wheel；wheel 安装后不需要构建工具。模块入口 `python -m mathmodel_copilot` 等价于控制台入口。`--resource-root` 返回本次安装的资源目录，便于诊断。

## 最小真实演示

以下示例中的 `mathmodel-copilot` 指上述虚拟环境里的命令。目标目录必须为空或不存在。

```console
mathmodel-copilot --workspace ../demo-project demo
mathmodel-copilot --workspace ../demo-project status
mathmodel-copilot --workspace ../demo-project view
mathmodel-copilot --workspace ../demo-project dashboard --port 8765
```

演示使用 MCM 历史题背景与原创合成交通流数据。首次命令会真实运行模型和独立 checker，不拷贝旧结果；运行时长随机器变化。它用于软件路径与模型局限说明，不能宣称真实交通预测能力或正式可提交。建模工作台在终端持续运行，浏览器访问 `http://127.0.0.1:8765`，结束时按 Ctrl+C。它使用标准库 HTTP 服务和静态前端，不需要 Node、构建前端或额外的工作台依赖。

可选 Git 读取：

```console
mathmodel-copilot --workspace ../demo-project git status
mathmodel-copilot --workspace ../demo-project view --git
```

未安装 Git、不是仓库或没有账号时，默认本地模式继续可用。这些命令不创建仓库、不联网同步、不推送。

## 依赖分组

| 分组 | 使用场景 |
|---|---|
| 无 extra | Store、CLI、JSON 配置、合成 demo、只读建模工作台；标准库 |
| `yaml` | YAML payload，以及 doctor 的 Skill/Stage 元数据检查；缺失会明确报告依赖缺失，不能当作代码失败或通过 |
| `documents` | DOCX/PDF 检查与示例生成；外部 Word/TeX 渲染器仍需单独安装 |
| `analysis` | 数据分析、绘图及通过 openpyxl 读取现代 XLSX 工作簿 |
| `historical` | xlrd/xlwt 历史 XLS；不包含任何赛题附件 |
| `test` | 常规回归测试依赖；完整授权历史集成另加 `historical` 和附件 |
| `maintenance` | 资料下载/整理维护工具，浏览器组件另按工具需求安装 |
| `build` | 构建 wheel/sdist 的维护工具 |

例如 `python -m pip install ".[documents,test]"`。旧 `scripts/requirements-runtime.txt` 为兼容保留，包含多个可选组，不能用它代表核心必需依赖。

## Skill / plugin 发现与旧名兼容

主发现名为 `$mathmodel-copilot`。Python 安装不会自动写入全局或用户 Skill 目录。需要让宿主发现时，从清洁源码执行：

```console
python tools/install_skill.py --directory ../isolated-skills
```

安装目录明确由调用者指定，创建 `mathmodel-copilot` 子目录，其中递归只有一个 `SKILL.md`；任何同名现有目录都拒绝覆盖。此命令不会配置宿主，按宿主的目录发现机制选择该显式目录。已装旧版出现多个入口时，先关闭旧入口的宿主注册，再在新目录安装；安装器不会替用户删除历史目录。

只有确实需要旧名时才加 `--legacy-alias`。它另建薄入口 `mathmodel-skill`，并要求此路径不存在；现有上游安装会使整个安装在写入前拒绝。源码保留插件及兼容入口；用户运行包和默认安装不包含嵌套的插件或兼容 `SKILL.md`。不要同时注册同一产品的源码插件和用户运行安装。

Python 与 Skill 安装均不迁移项目。升级、回退及卸载见 [UPGRADE_ROLLBACK.md](UPGRADE_ROLLBACK.md)。

## 维护者：两类分发包

从完整源码运行，输出目录必须是新目录或空目录：

```console
python tools/build_release.py --profile source --output ../source-candidate
python tools/build_release.py --profile runtime --output ../runtime-candidate
python tools/verify_install.py --archive ../runtime-candidate/实际运行包.zip --output ../runtime-evidence --work-dir ../runtime-verification
```

源码包保留测试、构建和插件入口；运行包保留全部现有运行引用、赛事资料、模板、建模工作台、许可证和使用文档，去除构建/测试及重复发现入口。没有虚构“所有平台最多 100 个文件”的统一限制，也不承诺当前运行包低于 100 个文件。宿主的原生 ZIP 导入规则须按其实际版本单独验收；把 ZIP 发给能访问本地文件的 AI 解压安装，与向云端平台上传 Skill 是不同路径。

运行包的 `doctor` 使用明确发行清单、实际文件哈希和单入口数量识别其布局；缺失插件文件本身不算合格运行包。清单仅核验字节一致性，不代表官方签名或外部发布授权。

## 没有 LaTeX 时

仍可整理 Markdown 写作材料并使用 `render_paper.py --no-compile` 生成模板预览；这不等于完成 PDF 编译或排版验收。最终正文由队员主导，AI 按请求提供证据、图表、局部文字建议与检查。需要最终 PDF 时，再在可用的渲染环境完成编译和人工逐页复核。
