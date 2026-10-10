# 固定安装包维护约定

公众号与 README 的对外下载入口保持不变。每次推送涉及运行文件的更新时，必须同步已验收的运行安装包，不能只更新源码、版本号或新增带版本号的 ZIP。

- `downloads/MathModel-Copilot-latest.zip`：长期固定入口，始终提供当前公开版本。
- `downloads/MathModel-Copilot-v0.3-Preview.zip`：已用于早期公众号的兼容入口，虽有旧版字样，也必须同步最新版，不能删除或冻结。
- 带完整版本号的 ZIP 用于归档与回退；不能代替前两个入口的更新。

发布时，从已验收的 runtime ZIP 更新两个固定文件，并在同一提交中维护 `downloads/release-index.json`、`downloads/SHA256SUMS.txt` 与下载说明。保留历史版本文件。继续遵守现有授权、许可和验收边界。

推送前执行：

```text
python .github/scripts/check_downloads.py
```

检查对照真实运行文件和 ZIP 内清单，验证两个固定入口、当前版本包、版本索引及哈希。源代码变更但安装包未重建时失败；这项检查已接入 GitHub Actions。仅修改 CI 等不进入运行包的文件无需重打同一份安装包。

推送后执行：

```text
python .github/scripts/check_downloads.py --remote
```

必须匿名下载两个原始固定 URL，确认返回内容与已验收安装包完全相同。GitHub CDN 短暂返回旧缓存时，等待后复查，不以带随机参数的新链接冒充公众号原链接验收成功。检查不会自动上传、重打包或授予发布许可。
