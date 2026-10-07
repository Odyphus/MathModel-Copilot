# MathModel Copilot 下载

点击 [下载最新版 MathModel Copilot](https://github.com/Odyphus/MathModel-Copilot/raw/refs/heads/main/downloads/MathModel-Copilot-latest.zip)，下载后把包交给能操作本机文件和运行 Python 的 AI，请它安装唯一的 mathmodel-copilot Skill。已有安装拒绝覆盖，先确认升级位置；安装不会修改比赛项目。

当前包为 **0.3.0-preview.2**，对应当前发布源码的运行文件，只有一个 Skill 入口。校验值见 [SHA256SUMS.txt](SHA256SUMS.txt)，版本与文件清单摘要见 [release-index.json](release-index.json)。源码即本仓库；运行包不支持直接 `pip install .`，详见 [安装说明](../docs/INSTALL.md)。

固定 latest 下载入口、兼容的 `MathModel-Copilot-v0.3-Preview.zip` 与 [固定版本包](MathModel-Copilot-v0.3.0-preview.2.zip) 内容相同。旧包原样保存在 [历史版本](archive/MathModel-Copilot-v0.3.0-preview.1.zip)，便于核对，不作为当前推荐安装包。

仓库已公开，下载不要求登录。运行包不会自动配置 GitHub、上传资料或发送 Issue。本轮验收与未验证项见 [验收记录](../docs/ACCEPTANCE_V032.md)；来源许可范围见 [许可记录](../LICENSE_SCOPE.md)。

## 后续发布时如何维护

保留带版本号的历史安装包。每次发布新版时，将已经验收的版本包复制为 `MathModel-Copilot-latest.zip`，同时更新本页的版本说明和 `SHA256SUMS.txt`，在同一次提交中发布。文件名中的 `latest` 本身不提供自动更新功能，发布者必须完成这一步。

发布后，从上面的固定链接匿名下载一次，核对 ZIP 完整性及其与本次版本包的字节一致性。不要把开发中的源码 ZIP 当作安装包更新到这个入口。
