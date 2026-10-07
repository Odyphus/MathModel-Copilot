# CUMCM Papers Download Report

**来源清单总计**: 91 份公开收集的 CUMCM 论文 PDF（约 432 MB）

> 91 是来源文件数，不是自动统计的有效样本数。归档蒸馏中有 59 份满足当前文本提取条件；所有分位数只代表这 59 份可提取子集。

| 来源 | 数量 | 备注 |
|------|------|------|
| 教育部"中国大学生在线"展廊 (2023) | 9 | Playwright 渲染详情页 + 图片重建 PDF (image-only) |
| 教育部展廊 (2024) | 16 | 同上 |
| 教育部展廊 (2025) | 7 | A 题验证为 2025 真题 (无人机烟幕) |
| GitHub `zhanwen/MathModel/国赛论文/2023年优秀论文/` | 58 | 直接公开 PDF, A-F 题号齐全 |
| GitHub `Jackyleo-Zhao/cumcm-2025` (国二) | 1 | 2025 C 题 NIPT |

## 来源抽检

曾抽查 3 份官方展廊文件（2023-B226 / 2024-B195 / 2024-E218）的首页，确认年份与文件名一致；另检查 2025-A196 的题目内容与当年 A 题相符。这是来源抽检，不等同于对全部 91 份文件逐篇审计。

## 已知限制

- 32 份展廊重建 PDF 是图片型，`pdfplumber` 无法直接提取正文；`ingest_papers.py` 会按文本量过滤，因此归档统计只使用 59 份可提取文件。
- 题号覆盖: 2023 A/B/C/D/E/F, 2024 A/B/C/D/E, 2025 A/B/C/D/E (含 1 篇国二)。

## 重新下载方式

`scripts/download_cumcm_papers.py` 是维护脚本，不在比赛运行时调用。它当前只覆盖脚本中登记的 2023、2024 官方展廊页面，不能重建清单中的 GitHub 与 2025 来源。运行前先安装 `scripts/requirements-maintenance.txt`，并确认站点结构与来源使用范围：

```bash
python scripts/download_cumcm_papers.py --papers-dir /path/to/cumcm-papers --years 2023 2024
```
