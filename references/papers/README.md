# 论文样本维护区

> 本目录只用于维护者离线更新描述性统计。运行时工作流不读取原始 PDF，也不需要此目录存在。

## 当前口径

- 来源清单记录 91 份公开可访问的 CUMCM 论文文件。
- 其中 59 份满足当前文本提取条件并进入统计。
- 其余 32 份主要是图片型 PDF，未进入文本分位计算。
- 详细来源数量与抽检边界见 [`_DOWNLOAD_REPORT.md`](./_DOWNLOAD_REPORT.md)。

这些数字描述的是归档样本和当前提取器，不代表完整获奖论文总体。来源标签、题型分布、年份和 PDF 可提取性都可能带来偏差。

## 更新流程

仅处理你有权访问和分析的文件，并保留来源、年份、题号与使用条件。不要把原始论文 PDF 提交到本仓库。

```bash
python -m pip install -r scripts/requirements-maintenance.txt

python scripts/ingest_papers.py \
  --papers-dir /path/to/authorized-papers \
  --output /tmp/empirical_distribution.md
```

更新后必须人工检查：

1. 来源数量与成功提取数量是否分别记录；
2. 图片型、乱码和正文过短文件是否被排除；
3. 年份与题型构成是否造成明显偏差；
4. 分位数是否只被描述为样本观察，而非官方阈值；
5. `competitions/cumcm/empirical.json`、说明文档与测试是否同步。

下载与提取工具的依赖、参数和限制见 [`../../scripts/README.md`](../../scripts/README.md)。
