# 升级、恢复与卸载

v0.2.0-preview.1 保留 v0.1.3 的根状态 schema 4.0 与 copilot 子树 0.1。产品版本和状态 schema 是两件事；安装软件不会自动重写任何项目。

## 已有 v0.1.3 工作区

先停止写入端，复制整个工作区到一个新目录，包括隐藏的 `.copilot/`、`state/` 和所有实际输入输出。保留原目录作为恢复点，在副本中用新版执行 `status` 和必要回归。不要把现有项目放进 Python 环境或安装资源目录。`init` 是 create-only，已有权威状态只报告续接，不能用它重置历史。

## 更早的 schema 3.1

在副本执行：

```console
mathmodel-copilot --workspace ../legacy-copy migrate --expected-revision 0
mathmodel-copilot --workspace ../legacy-copy status
```

迁移会把旧权威 JSON 原字节保存到 `state/migrations/<digest>.json`，通过现有 Store 事务写入 schema 4.0。旧评分和旧 `pass` 不会变成当前真实运行证据。重复调用和 revision 冲突按实际状态处理，冲突后先重新读状态，不绕过事务。备份 JSON 只覆盖迁移前的权威文件；项目级回退仍须保留完整目录副本。

## 回退

最可靠的回退是重新使用升级前保留的完整工作区副本和旧版独立环境。不要在新版已经产生工作后直接覆盖当前 `decision_log.json`，那会丢失后续历史；保留新版目录供核对。先前环境保留时只需切换调用路径；需要重装时使用本地保留的旧包，而不是猜测线上版本。

## 卸载

在候选专用环境执行：

```console
python -m pip uninstall mathmodel-copilot
```

pip 卸载仅删除该发行包的安装记录文件，不负责删除项目、运行证据或旧版本环境。安装验收工具会实际检查卸载前后独立工作区的权威文件哈希一致。删除整个虚拟环境前确认它是候选专用目录，工作区位于目录外。

显式 Skill 安装记录在 `INSTALL_MANIFEST.json`。若不再需要，可移走这一个新建安装目录；先确认其中没有加入用户项目。可选旧名薄入口单独保留或移走，不操作已有上游目录。没有自动清理用户目录的卸载脚本。
