# BPE main 优化候选交接（2026-10-08）

本次交接包含 10 个独立候选、2 个阶段诊断分支，以及另一台机器可直接运行的统一 benchmark。所有训练候选已推送到 [Yikai-Liao/tokenizers](https://github.com/Yikai-Liao/tokenizers)，没有合入 main。目前没有确认一个能在不同批次、线程数和中英文上稳定获益的组合；请重新测量后筛选，不继承此前聊天中的收益排名。

用户最后确认的默认配置是 **中英文各 256 MiB 原始语料、100K 目标词表、4 线程、2 轮交错测试**。多线程候选获益后，再补小规模单线程；建议取相同原始语料的 32 MiB 整行前缀。保留候选时要避免英文优化带来中文的大额外成本，并检查深模块、私有资源生命周期和代码简洁性。

## 分支与实现

基线固定为 `8faaff79d859bfd6b2417cfe8c93ea2851c3aaca`。完整提交、分支和候选 ID 见 [candidates.json](candidates.json)。下表每个候选都相对于这个基线比较；safe 和 BMP 是其前一个实验的修订，其他候选互不叠加。没有创建组合版本。

| 候选 ID | tokenizers 分支 | 提交 | 改动及复测注意事项 |
|---|---|---|---|
| parallel_cleanup | [experiment/main-parallel-cleanup](https://github.com/Yikai-Liao/tokenizers/tree/experiment/main-parallel-cleanup) | ec92103b | 成功完成时并行释放 pair owners；arena 和 worker scratch 在实际执行 worker 上释放。先释放 position owners，再释放 arena。错误和 restart 的隐式清理没有改。 |
| scratch_reuse | [experiment/main-scratch-reuse](https://github.com/Yikai-Liao/tokenizers/tree/experiment/main-scratch-reuse) | 0648b878 | 缓存 accumulator 空 entries、promotion headers 和 owner routing 数字元数据；不跨阶段保存事件引用或位置 payload。用于复现早期测量。存在下文列出的私有异常路径问题。 |
| scratch_reuse_safe | [experiment/main-scratch-reuse-safe](https://github.com/Yikai-Liao/tokenizers/tree/experiment/main-scratch-reuse-safe) | becfd293 | 同一复用实现，加上 forgotten-drain 后重新 touch 再转移时的 entries 清理。后续评估复用方案优先用此分支。 |
| terminal_publication | [experiment/main-terminal-publication](https://github.com/Yikai-Liao/tokenizers/tree/experiment/main-terminal-publication) | c479c79f | 最后一轮共享 commit 核心保留所有 count 和 codec 检查，跳过不可再消费的候选发布/前缀补充。没有跳过位置编码。 |
| lean_materialization | [experiment/main-lean-materialization](https://github.com/Yikai-Liao/tokenizers/tree/experiment/main-lean-materialization) | ea6d7314 | ordinary prepare 直接收集 writes/chunks；按已知输出数预留 jobs；消费 CompactString 时用 into_string。 |
| sparse_character_ids | [experiment/main-sparse-character-ids](https://github.com/Yikai-Liao/tokenizers/tree/experiment/main-sparse-character-ids) | f16dcbd7 | 参照实际 tk-encode SparseFold：ASCII 直读，BMP bitmap/rank + packed IDs，non-BMP hash。中文退化已重复出现，不建议直接保留。 |
| hot_cold_priorities | [experiment/main-hot-cold-priorities](https://github.com/Yikai-Liao/tokenizers/tree/experiment/main-hot-cold-priorities) | 887107c4 | 初始 fresh 候选排序为 cold 流；新生和修复项进入 hot 八叉堆；每次重新比较两个前沿。保留全宽 key/count；reuse 队列不变。6 线程曾获益，4 线程中文退化。 |
| unrestricted_births | [experiment/main-unrestricted-births](https://github.com/Yikai-Liao/tokenizers/tree/experiment/main-unrestricted-births) | 184bd4b9 | 每个 fresh job 一次证明 span limit 覆盖完整 corpus，跳过逐边的可选长度计算；有限长度、AA、reuse 仍走原语义。 |
| ascii_pair_grid | [experiment/main-ascii-pair-grid](https://github.com/Yikai-Liao/tokenizers/tree/experiment/main-ascii-pair-grid) | e5f86d16 | 只对 plain ASCII 初始 ID 使用 128² u16 索引网格和独立 state 存储，其余 key 保留 hash。每个 owner 的网格为 32 KiB；u16 是 cell 索引，不是 TokenID。稀疏/大 reserved-ID 范围及 reuse 有回退。没有把 7,898/20,755 个 Unicode 字符组成全网格。 |
| bmp_character_ids | [experiment/main-bmp-character-ids](https://github.com/Yikai-Liao/tokenizers/tree/experiment/main-bmp-character-ids) | 9846f172 | 修订字符查找：BMP 用 256 KiB ID 直读表，non-BMP 稀疏存储，移除逐字符 rank/popcount。英文两轮获益，中文接近持平但尚未紧邻复测。 |

诊断分支只用于解释阶段耗时，不能当作最终生产候选：

| 候选 ID | 分支 | 提交 | 父版本 |
|---|---|---|---|
| phase_baseline | [experiment/phase-baseline](https://github.com/Yikai-Liao/tokenizers/tree/experiment/phase-baseline) | 14229959 | 基线 |
| phase_scratch | [experiment/phase-scratch](https://github.com/Yikai-Liao/tokenizers/tree/experiment/phase-scratch) | 9a5a412a | scratch_reuse 原始实验 |

两个诊断分支加了完全相同的 joined phase 计时、batch histogram、出生事件/分组计数和 contiguous 模式次数。数据输出到每个 attempt 的 stderr。原始诊断 binary 在提交前从完整 dirty snapshot 构建；snapshot 已保留，与此处最终提交的代码一致。新机器应直接按以上提交重建，脚本不会接受 dirty build。

## 正确性与代码审查

每个训练候选都通过默认功能和 `--no-default-features` 的现有 101 项 tk-train lib tests，以及 `cargo clippy --lib --no-default-features -- -D warnings`。没有添加新的 test function；必要边界通过扩展已有 fixture/参数覆盖。所有已经运行的标准 benchmark 都校验了 vocabulary IDs 和 ordered merges 完全一致；6 次 perf 诊断也做了相同模型比较。

scratch 原始实验的具体异常路径：忘记一个 Drain 后再 touch 新 ID，`into_storage` 的 drain_pending 分支会清理目录但留下新 entries，违反返回空缓存的约定。safe 分支添加 `entries.clear()`，并在已有 forgotten-drain 测试中覆盖此场景。正常训练没有触发这一问题；保留原始分支仅为了比较同一早期 binary。

已有封装审查：scratch 重置由 IdAccumulator/Execution 负责，coordinator 不知道缓存布局；owner routing 缓存只持有数字引用，joined 后清空；terminal 使用一个共享 checked commit 核心；字符查找布局封装在 Vocabulary 内。真正保留前，还需对新机器证明有收益的版本重新审查；不要为没有收益的实验继续增加抽象层或测试框架。

## 当前测量与限制

完整逐运行记录在 [measurements.json](measurements.json)，包含输入/build IDs、时间、CPU 时间、RSS、swap、亲和性、模型 hash、诊断计数和 perf 结果。它保留不同批次，不能把 1/4/6 线程或 256/512 MiB 混成一个样本集合。以下变化是同 block 相对 baseline 的训练时间百分比：**负值为更快**，两个数字分别为两轮。它们是观察值，不是已确认的稳定收益。

### 最新 256 MiB / 4 线程 / 100K，两轮、7 arms

| 候选 | English 两轮 | Chinese 两轮 |
|---|---:|---:|
| hot_cold_priorities | -5.60% / -5.89% | +2.77% / +7.93% |
| lean_materialization | -7.28% / +5.86% | +0.71% / +6.31% |
| sparse_character_ids | -6.70% / -9.62% | +19.57% / +5.11% |
| ascii_pair_grid | +3.96% / -6.27% | +14.79% / +7.55% |
| scratch_reuse_safe | -3.93% / -7.62% | +6.74% / +0.45% |
| bmp_character_ids | -2.46% / -10.01% | +3.01% / -1.58% |

### 512 MiB / 6 线程 / 100K，两轮、8 arms

| 候选 | English 两轮 | Chinese 两轮 |
|---|---:|---:|
| parallel_cleanup | +0.75% / +2.35% | -6.18% / +9.62% |
| scratch_reuse | -1.38% / -10.70% | +10.53% / -0.18% |
| terminal_publication | +2.92% / -8.00% | +0.04% / +3.63% |
| lean_materialization | +2.09% / -9.89% | -4.56% / -2.18% |
| sparse_character_ids | -8.29% / -8.73% | +6.22% / +8.00% |
| hot_cold_priorities | -0.88% / -3.95% | -4.74% / -6.41% |
| unrestricted_births | -0.42% / -11.69% | +2.25% / -1.29% |

另有最早 4 arms / 32 runs 的 512 MiB 结果。该批多 arm 调度采用旋转，两个 block 的 arm 顺序没有反转；新交接分支包含调度修复，不应从最早批次单独得出排名。二元 AB/BA 的旧调度原本正确。

### scratch 为何前后反转

已核对：最早和 expanded 批次的 baseline/scratch 使用同一 binary SHA、同一输入、同一 Cargo.lock/编译配置；caller word map 固定 seeds `[11,13,17,19]` 和重建顺序；同一 CPU set；没有 swap。库内部分 AHashMap/IndexSet 的默认 hasher 和并行任务/分配时序仍未固定，尚未证明它们分别贡献了多少波动。

紧邻 512 MiB / 6 线程 AB/BA 复测中，中文 scratch 两轮分别快 14.4%、6.6%，英文分别慢 9.0%、快 0.5%。因此不能根据 expanded 批次直接宣布 scratch 无效，也不能沿用最早的高收益百分比。

256 MiB / 4 线程的相同阶段诊断显示：中文两轮 batch histogram、53,721,782 个 sampled births、17,592,506 个 sampled groups 和 27 次 contiguous rounds 完全一致。第一轮合并循环 7.315→6.096 秒；第二轮 6.930→6.420 秒。第二轮初始化 3.199→3.624 秒，抵消了大部分循环收益，总时间只从 10.308→10.209 秒。准备/提交阶段有获益证据，但端到端收益受其他阶段波动影响；英文循环本身也反转。

硬件计数器诊断使用同一 English 256 MiB baseline binary，记录的是**整个进程（包含 loading 和 serialization）**。首尾训练时间 2.797→3.102 秒；全进程指令数 17.973→17.965 billion（变化不到 0.05%），CPU cycles 21.888→23.544 billion，IPC 0.821→0.763，cache misses 117.18→122.62 million；cycles/ref-cycles 1.301→1.296。两次 migrations 为 10/9，context switches 为 27,474/26,731。这支持执行成本在变，不能仅解释成模型工作量或明显的频率/迁移增加。缓存布局、分配/线程时序和宿主资源竞争的贡献还未分别锁定。ASLR 关闭只做了能力探测，没有用它跑候选或 A/A；也没有实施逐 worker 固定核。

原机器是 KVM、6 vCPU、Xeon Gold 6140，Rust 1.98.1 / LLVM 22.1.8。所有候选使用普通 portable release，fat LTO、codegen-units=1、空 Rust flags。没有在性能运行期间编译或跑测试。即使采取这些措施，同一 baseline 仍出现约 10–18% 的跨运行变化，所以 2–6% 的变化不够支持稳定收益结论。

### 中文字符查找退化

bitmap/rank 方案不只是加分支：非 ASCII 路径多了 bitmap、row_start、packed ID 的依赖读取及 rank 计算。原机器的 portable build 没有使用 POPCNT；[实际 CharacterIds::get 机器码](sparse-character-get.asm) 是移位、掩码、乘法组成的软件 popcount。分支预测准确不会消除这些操作。BMP 直读版本避免了这条路径，但 non-BMP 仍是 sparse lookup，最终是否保留以新机器中英文结果为准。

## 在另一台 Linux 机器上运行

在新机器重建，不复制本机 binary/build.json。需要 Git、Rust/Cargo、uv、taskset 和足够内存。选择并记录同一个 Rust toolchain；本机参考版本为 1.98.1。下面的共同 [Cargo.lock](Cargo.lock) 固定了此次实验使用的依赖（SHA-256 `8ceda6c725afdb2c6d8f16049f6e6d1551fb990f408743b04a6517eebd3377a3`）。

```sh
git clone https://github.com/Yikai-Liao/tokenizers.git tokenizers
git clone --branch experiment/main-bpe-optimization-handoff \
  https://github.com/Yikai-Liao/tokenizers-bpe-benchmarks.git tokenizers-bpe-benchmarks
cd tokenizers-bpe-benchmarks
uv sync
```

输入可以使用你自己的固定 English/Chinese 原始文本，也可以先用仓库的 pinned Wikipedia 配置下载：

```sh
uv run python -m bench corpus --dataset datasets/wikipedia-en.json \
  --size-mib 256 --out .bench/corpora/en256
uv run python -m bench corpus --dataset datasets/wikipedia-zh.json \
  --size-mib 256 --out .bench/corpora/zh256
```

注意：这个 English 下载配置未核对为旧 512 MiB English 文件的原始来源，因而它是**新输入上的复测**。如果要精确复现本机输入，需要另行复制下面两个本机文件；不在 Git 中发布大型语料：

- English：`/root/code/tokenizers-bpe-benchmarks/.bench/main-yttm-inspired/inputs/en256/text.txt`，268,434,529 bytes。
- Chinese：`/root/code/tokenizers-bpe-benchmarks/.bench/main-yttm-inspired/inputs/zh256/text.txt`，268,435,162 bytes。

新机器各 arm 必须用同一份文本和 prepared words；脚本取整行前缀、记录 source SHA 和实际字节数，统一由 baseline 预处理。English 用 WhitespaceSplit，Chinese 用 Whitespace；没有 ByteLevel、affix、length limit，min_frequency=2。

### 先检查同版本重复测量

```sh
uv run python experiments/main-bpe-optimization-20261008/run.py \
  --source ../tokenizers \
  --en-text .bench/corpora/en256/text.txt \
  --zh-text .bench/corpora/zh256/text.txt \
  --self-check --out .bench/main-opt-self-check
```

A/A 把完全相同的 baseline build 作为 baseline 和 baseline_repeat。默认 4 线程、两轮、两个语料，共 8 次 measured runs；CPU 默认选择当前允许集合的前四个，可用 `--cpus 0,1,2,3` 指定。CPU set 是进程允许集合，不代表每个 worker 永远固定在其中一个核。先看 A/A 的 paired ratios 和逐运行时间；如果自身波动与候选收益同级，就报告无法判定，不强排收益名次。可以用 `--blocks N` 自行增加重复，但当前用户默认仍为两轮。

### 独立候选统一测试

```sh
uv run python experiments/main-bpe-optimization-20261008/run.py \
  --source ../tokenizers \
  --en-text .bench/corpora/en256/text.txt \
  --zh-text .bench/corpora/zh256/text.txt \
  --out .bench/main-opt-all
```

默认构建 baseline 和全部 10 个候选，读取固定提交、同一个 lock 和空 Rust flags，再运行 44 次 measured processes；warmup=0，两个 block 的 arm 顺序互为反向，模型精确校验。诊断分支默认不加入。每次使用新的 `--out`，已经构建的内容会由 immutable build cache 复用。可先减少候选：

```sh
uv run python experiments/main-bpe-optimization-20261008/run.py \
  --source ../tokenizers --en-text /path/to/en.txt --zh-text /path/to/zh.txt \
  --arms scratch_reuse_safe,bmp_character_ids,hot_cold_priorities \
  --out .bench/main-opt-selected
```

只有新机器多线程收益成立的候选再跑小规模单线程，例如：

```sh
uv run python experiments/main-bpe-optimization-20261008/run.py \
  --source ../tokenizers --en-text /path/to/en.txt --zh-text /path/to/zh.txt \
  --arms bmp_character_ids --size-mib 32 --workers 1 \
  --out .bench/main-opt-small-single
```

脚本会写 `build-index.json`、文本/words manifests、`comparison.json` 和标准 `runs/attempts`、`runs/report/summary.json`。后续可以用 `--build-index /path/to/build-index.json` 复用经过提交/lock/flags 检查的本机 builds；`--plan-only` 只做 build、输入准备和 config 生成。诊断可用 `--arms phase_baseline,phase_scratch`，它还会包含普通 baseline，以区分 instrumentation 带来的编译/计时差异。

harness 的 `performance_conclusion_valid` 只表示模型、协议和资源检查允许报告这些时间，**不表示统计稳定或证明加速**。复测要同时保留失败 attempt、CPU 时间、RSS、swap、亲和性、输入/build IDs 和两轮原始值。

## 交接时未完成的工作

- 测量不稳定的根因没有完全隔离；同版本 A/A、内部随机布局、allocator/worker 时序和共享宿主缓存影响需在新机器继续分析。
- BMP 版没有完成单独紧邻复测；多线程获益候选的小规模单线程 follow-up 尚未开始。
- 未合入 main，未创建组合候选，未确认推荐落地版本。
- 两份笔记的 encode-only 方向已放入 [candidate-pool.json](candidate-pool.json)，未在本次 training benchmark 中实现/验证；不能从本次结果声称 encode 获益。

参考材料已经随此目录保留：[YTTM_ALIGNMENT_NOTES.md](YTTM_ALIGNMENT_NOTES.md)、[TRANSFER_ADDENDUM.md](TRANSFER_ADDENDUM.md)。候选实现前读过实际 tk-encode 的 SparseFold、MergeQueue/QueueSink、BpeScratch、top_index/top_values；转移条件和暂缓理由见候选池。
