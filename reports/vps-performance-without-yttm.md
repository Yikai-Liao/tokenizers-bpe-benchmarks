# VPS BPE 性能实测汇总（排除 YTTM）

本报告仅汇总 HF main、HF PR #2348 和 Fork main；所有 YTTM 数据均已排除。使用已经保存的实测记录重新汇总，没有追加性能运行。

## 测试条件

- 主矩阵：每份原始 UTF-8 语料约 32 MiB，按完整行截断。英文和代码使用 ByteLevel；中文分别使用 ByteLevel 和 HF `Whitespace`（包含标点切分）。
- 目标词表大小：100,000；`min_frequency = 2`。
- 每个组合测量 3 次，表中耗时与 RSS 为中位数。每个程序都在独立进程中执行；全套测试只有一次代表性预热。
- 核心数配置为 1 / 2 / 4 / 6；执行环境是 6 vCPU VPS，CPU affinity 使用 0..5 的前 N 个 CPU。机器同时运行后台服务，尤其不宜用四核与六核之间的小幅差异判断回退。
- 这些主矩阵运行来自 Docker，禁用网络，使用 portable release 编译；没有 Docker 内存硬限制。
- 三个实现都通过了相同输入、相同线程数下的完整词表 ID 和有序 merges 对照；本报告对应的 144 次测量全部成功。
- RSS 是整个进程的峰值，包含输入、Feed、Train 和采样到的模型导出；不是 Train 阶段独占内存。
- 1 MiB 历史小语料测试和独立内存增长运行未混入本报告。

## 源码版本

| 实现 | 提交 |
| --- | --- |
| HF main | `4c13417e6b2b717f906bdf803f90889e3e3a6662` |
| HF PR #2348 | `6ac0de5359d9e0e1ed0608422575a360ef91b908` |
| Fork main | `8faaff79d859bfd6b2417cfe8c93ea2851c3aaca` |

## Feed + Train 总耗时

计时包含公共 Feed（读取、预分词、词频聚合）和 Train，排除模型导出。加速比为同轮 HF main 耗时 / 对应实现耗时的中位数；它与直接相除两列中位数略有差异。这里比较的是同一线程数下不同实现的性能。

| 语料 | 核心数 | HF main (s) | HF PR #2348 (s) | Fork main (s) | PR / HF 加速比 | Fork / HF 加速比 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 代码 / ByteLevel | 1 | 10.434 | 4.985 | 3.287 | 2.02× | 3.05× |
| 代码 / ByteLevel | 2 | 8.829 | 3.555 | 2.169 | 2.43× | 4.08× |
| 代码 / ByteLevel | 4 | 7.014 | 2.740 | 1.439 | 2.54× | 4.88× |
| 代码 / ByteLevel | 6 | 6.639 | 2.640 | 1.300 | 2.58× | 5.11× |
| 英文 / ByteLevel | 1 | 7.421 | 3.342 | 2.287 | 2.21× | 3.25× |
| 英文 / ByteLevel | 2 | 6.045 | 2.407 | 1.624 | 2.52× | 3.68× |
| 英文 / ByteLevel | 4 | 5.278 | 1.882 | 1.115 | 2.69× | 4.42× |
| 英文 / ByteLevel | 6 | 5.210 | 1.664 | 0.964 | 3.05× | 5.26× |
| 中文 / ByteLevel | 1 | 61.244 | 15.813 | 7.501 | 3.89× | 8.17× |
| 中文 / ByteLevel | 2 | 62.666 | 15.074 | 4.883 | 4.16× | 12.93× |
| 中文 / ByteLevel | 4 | 52.030 | 13.234 | 3.085 | 4.01× | 16.87× |
| 中文 / ByteLevel | 6 | 50.768 | 13.813 | 2.769 | 3.75× | 18.41× |
| 中文 / HF Whitespace | 1 | 35.795 | 17.753 | 4.012 | 2.02× | 8.92× |
| 中文 / HF Whitespace | 2 | 38.955 | 17.706 | 2.894 | 2.19× | 13.46× |
| 中文 / HF Whitespace | 4 | 35.087 | 17.019 | 1.928 | 2.06× | 17.95× |
| 中文 / HF Whitespace | 6 | 37.509 | 16.278 | 1.831 | 2.30× | 20.66× |

## 仅 Train 耗时

使用与上一张表完全相同的运行，计时仅包含 Train，排除 Feed 和模型导出。加速比使用同轮 Train 耗时计算。

| 语料 | 核心数 | HF main (s) | HF PR #2348 (s) | Fork main (s) | PR / HF 加速比 | Fork / HF 加速比 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 代码 / ByteLevel | 1 | 7.279 | 1.680 | 0.939 | 3.86× | 7.36× |
| 代码 / ByteLevel | 2 | 7.067 | 1.731 | 0.800 | 3.88× | 8.86× |
| 代码 / ByteLevel | 4 | 5.935 | 1.674 | 0.736 | 3.55× | 8.03× |
| 代码 / ByteLevel | 6 | 5.804 | 1.684 | 0.738 | 3.43× | 7.87× |
| 英文 / ByteLevel | 1 | 5.331 | 1.254 | 0.688 | 4.35× | 7.74× |
| 英文 / ByteLevel | 2 | 4.883 | 1.282 | 0.662 | 3.83× | 7.34× |
| 英文 / ByteLevel | 4 | 4.618 | 1.256 | 0.625 | 3.61× | 6.86× |
| 英文 / ByteLevel | 6 | 4.596 | 1.196 | 0.612 | 3.84× | 7.51× |
| 中文 / ByteLevel | 1 | 59.206 | 13.682 | 5.703 | 4.31× | 10.38× |
| 中文 / ByteLevel | 2 | 61.307 | 13.594 | 3.861 | 4.51× | 15.88× |
| 中文 / ByteLevel | 4 | 51.116 | 12.373 | 2.592 | 4.22× | 19.72× |
| 中文 / ByteLevel | 6 | 49.880 | 12.777 | 2.354 | 3.91× | 21.00× |
| 中文 / HF Whitespace | 1 | 34.329 | 16.172 | 2.707 | 2.12× | 12.42× |
| 中文 / HF Whitespace | 2 | 37.955 | 16.692 | 2.135 | 2.27× | 17.78× |
| 中文 / HF Whitespace | 4 | 34.384 | 16.315 | 1.549 | 2.10× | 22.32× |
| 中文 / HF Whitespace | 6 | 36.909 | 15.593 | 1.500 | 2.37× | 24.86× |

## 吞吐、Feed 与峰值 RSS

吞吐分子均为实际输入的原始 MiB。总吞吐用输入 MiB / Feed + Train 中位耗时；Train 吞吐用输入 MiB / Train 中位耗时。RSS 使用 GiB（二进制单位）。

| 语料 | 核心数 | 实现 | Feed (s) | 总吞吐 (MiB/s) | Train 吞吐 (MiB/s) | 峰值 RSS (GiB) |
| --- | ---: | --- | ---: | ---: | ---: | ---: |
| 代码 / ByteLevel | 1 | HF main | 3.177 | 3.07 | 4.40 | 0.246 |
| 代码 / ByteLevel | 1 | HF PR #2348 | 3.340 | 6.42 | 19.05 | 0.099 |
| 代码 / ByteLevel | 1 | Fork main | 2.349 | 9.73 | 34.10 | 0.058 |
| 代码 / ByteLevel | 2 | HF main | 1.788 | 3.62 | 4.53 | 0.252 |
| 代码 / ByteLevel | 2 | HF PR #2348 | 1.825 | 9.00 | 18.49 | 0.098 |
| 代码 / ByteLevel | 2 | Fork main | 1.381 | 14.76 | 40.00 | 0.061 |
| 代码 / ByteLevel | 4 | HF main | 1.116 | 4.56 | 5.39 | 0.269 |
| 代码 / ByteLevel | 4 | HF PR #2348 | 1.097 | 11.68 | 19.11 | 0.098 |
| 代码 / ByteLevel | 4 | Fork main | 0.699 | 22.24 | 43.47 | 0.063 |
| 代码 / ByteLevel | 6 | HF main | 0.867 | 4.82 | 5.51 | 0.276 |
| 代码 / ByteLevel | 6 | HF PR #2348 | 0.916 | 12.12 | 19.00 | 0.100 |
| 代码 / ByteLevel | 6 | Fork main | 0.537 | 24.62 | 43.38 | 0.063 |
| 英文 / ByteLevel | 1 | HF main | 2.090 | 4.31 | 6.00 | 0.199 |
| 英文 / ByteLevel | 1 | HF PR #2348 | 2.129 | 9.57 | 25.52 | 0.079 |
| 英文 / ByteLevel | 1 | Fork main | 1.599 | 13.99 | 46.48 | 0.046 |
| 英文 / ByteLevel | 2 | HF main | 1.163 | 5.29 | 6.55 | 0.205 |
| 英文 / ByteLevel | 2 | HF PR #2348 | 1.126 | 13.29 | 24.96 | 0.080 |
| 英文 / ByteLevel | 2 | Fork main | 0.962 | 19.70 | 48.32 | 0.050 |
| 英文 / ByteLevel | 4 | HF main | 0.652 | 6.06 | 6.93 | 0.215 |
| 英文 / ByteLevel | 4 | HF PR #2348 | 0.630 | 17.00 | 25.48 | 0.080 |
| 英文 / ByteLevel | 4 | Fork main | 0.493 | 28.70 | 51.17 | 0.056 |
| 英文 / ByteLevel | 6 | HF main | 0.513 | 6.14 | 6.96 | 0.225 |
| 英文 / ByteLevel | 6 | HF PR #2348 | 0.491 | 19.23 | 26.75 | 0.082 |
| 英文 / ByteLevel | 6 | Fork main | 0.352 | 33.19 | 52.29 | 0.058 |
| 中文 / ByteLevel | 1 | HF main | 2.037 | 0.52 | 0.54 | 2.276 |
| 中文 / ByteLevel | 1 | HF PR #2348 | 2.125 | 2.02 | 2.34 | 0.795 |
| 中文 / ByteLevel | 1 | Fork main | 1.797 | 4.27 | 5.61 | 0.313 |
| 中文 / ByteLevel | 2 | HF main | 1.359 | 0.51 | 0.52 | 2.300 |
| 中文 / ByteLevel | 2 | HF PR #2348 | 1.318 | 2.12 | 2.35 | 0.800 |
| 中文 / ByteLevel | 2 | Fork main | 1.021 | 6.55 | 8.29 | 0.326 |
| 中文 / ByteLevel | 4 | HF main | 0.914 | 0.62 | 0.63 | 2.368 |
| 中文 / ByteLevel | 4 | HF PR #2348 | 0.900 | 2.42 | 2.59 | 0.811 |
| 中文 / ByteLevel | 4 | Fork main | 0.492 | 10.37 | 12.34 | 0.340 |
| 中文 / ByteLevel | 6 | HF main | 0.788 | 0.63 | 0.64 | 2.421 |
| 中文 / ByteLevel | 6 | HF PR #2348 | 0.785 | 2.32 | 2.50 | 0.809 |
| 中文 / ByteLevel | 6 | Fork main | 0.399 | 11.56 | 13.59 | 0.439 |
| 中文 / HF Whitespace | 1 | HF main | 1.561 | 0.89 | 0.93 | 1.358 |
| 中文 / HF Whitespace | 1 | HF PR #2348 | 1.576 | 1.80 | 1.98 | 0.580 |
| 中文 / HF Whitespace | 1 | Fork main | 1.266 | 7.98 | 11.82 | 0.212 |
| 中文 / HF Whitespace | 2 | HF main | 1.000 | 0.82 | 0.84 | 1.450 |
| 中文 / HF Whitespace | 2 | HF PR #2348 | 1.014 | 1.81 | 1.92 | 0.579 |
| 中文 / HF Whitespace | 2 | Fork main | 0.759 | 11.06 | 14.99 | 0.204 |
| 中文 / HF Whitespace | 4 | HF main | 0.712 | 0.91 | 0.93 | 1.554 |
| 中文 / HF Whitespace | 4 | HF PR #2348 | 0.685 | 1.88 | 1.96 | 0.582 |
| 中文 / HF Whitespace | 4 | Fork main | 0.379 | 16.60 | 20.65 | 0.226 |
| 中文 / HF Whitespace | 6 | HF main | 0.604 | 0.85 | 0.87 | 1.595 |
| 中文 / HF Whitespace | 6 | HF PR #2348 | 0.684 | 1.97 | 2.05 | 0.583 |
| 中文 / HF Whitespace | 6 | Fork main | 0.331 | 17.47 | 21.33 | 0.250 |

## 六核观察

六核下 Fork main 相对 HF main 的同轮中位加速比如下。此处报告较大的跨实现差距，不把四核到六核的细小变化解释为算法回退。

| 语料 | Feed + Train 加速比 | Train 加速比 | Fork RSS / HF RSS |
| --- | ---: | ---: | ---: |
| 代码 / ByteLevel | 5.11× | 7.87× | 23.0% |
| 英文 / ByteLevel | 5.26× | 7.51× | 25.7% |
| 中文 / ByteLevel | 18.41× | 21.00× | 18.1% |
| 中文 / HF Whitespace | 20.66× | 24.86× | 15.7% |

这台 VPS 上的结果适用于记录的 32 MiB 输入和编译方式。512 MiB 推荐配置以及其他物理服务器的扩展性需要在对应环境实测。

## 原始记录

- 完整数据目录：`/root/code/tokenizers-bpe-benchmarks/.bench/docker-vps-1246-light-warmup/results/`
- 主矩阵与每次运行：`matrix/spec.json`、`matrix/attempts/<attempt_id>/`。每次运行保存 job、runner JSON、模型、stdout/stderr 和 RSS 采样。
- 汇总来源：`report/summary.json`、`report/matrix.csv`。本报告旁的 `vps-performance-without-yttm.json` 保留筛选后的 48 行、全部耗时与 RSS 样本。
- 完整原始实验及测量镜像归档索引：`/root/code/tokenizers-bpe-benchmarks/.bench/evidence-20261007/index.json`。
