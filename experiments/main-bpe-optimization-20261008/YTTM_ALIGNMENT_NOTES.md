# YTTM 对齐与性能复盘笔记

记录截至 2026-10-08 的对齐过程。目标是复刻固定版本 YTTM C++ 的训练机制，同时保留 Tokenizers 的输出要求。这里分别记录 **C++ 机制对齐**、**兼容实现中的冗余删除**、**待验证原因**；三类不能互相当作证明。

参考为 `VKCOM/YouTokenToMe@f4162d846057a3118222ca04a01b84297eb8a8db` 的 `cpp/bpe.cpp`。正确性 oracle 为原始 Tokenizers `bbccb051`，比较完整词表 ID、有序 merge 和特殊 token。修改在隔离分支 `fix/yttm-cpp-alignment` 完成，交付至 `bpe/yttm-rust-reference`；首次对齐提交为 `07577061`。机制说明见 [YTTM_REFERENCE.md](YTTM_REFERENCE.md)。

## 已做的机制对齐

| 点 | 原 Rust 实现与问题 | 对齐后的实现 | 性能结论的范围 |
| --- | --- | --- | --- |
| 逐规则通信 | mpsc 任务/结果消息通道，分配与收发 | 长期 owner，固定两槽任务与结果；完成序号和条件变量 | 删除额外通信机制；没有单项消融证明它贡献了多少秒。 |
| 全局计数 | 除局部计数外维护持续全局计数与 delta 汇总 | 暂停 owner，按需从局部计数求和；新生候选发布局部绝对分数 | 删除 C++ 没有的全局维护层。 |
| 阻塞候选 | 单个 owner 完成后可能重复扫描被在途规则阻塞的 top | 提交/发布后才重选，对应 C++ `last_failed_try` | 删除重复选择工作。 |
| 一个 worker | 特殊直接执行路径 | 一个 owner 线程加协调器，仍走两槽 | 为机制一致而删除自己的优化，未声称它更快。 |
| owner 生命周期 | 初始化与合并使用不同线程 | 同一 owner 线程初始化并持续执行合并 | 匹配 C++ 生命周期；数据的销毁线程仍须单独核对。 |
| result 锁 | 较旧结果的读取曾等待同 owner 较新规则持有 Store 锁 | 独立结果槽，不等待正在更新的 Store | 修正首次实现引入的串行化。 |
| 恢复顺序 | 曾先打开运行 flag 再竞争 owner 锁 | 持锁设置 flag，再释放与通知 | 修正 owner 抢先运行造成的持锁竞争。 |
| 协调器临界区 | 读计数、派发、恢复分别获取所有 owner 锁 | 一次暂停临界区覆盖选择、规则发布与恢复 | v6 修正；为 C++ 锁范围对齐。 |
| head 收集 | 逐 payload 收集，可能提前消费较新规则结果 | 一次遍历全部 owner，只收最早在途规则；新结果留在第二槽 | v6 修正；保持 C++ 的 head 顺序。 |
| 字符 ID 解析 | 每字符建字符串，检查原字符、检查前后缀形式、再查 ID | 初始字符 ID 表；无实际前后缀时直接解析，有前后缀时保留授权和创建顺序 | v7 修正；CPP 本身直接查询 char2id。新增差分测试覆盖过滤位置与特殊 token。 |
| 出生结果表示 | full-pair 集合 → scores Vec → 全局 full-pair map | 左右邻居分别记录并直接汇总；键用实际 replacement | v8 修正；Tokenizers 的真实出生条件、负/零分、coverage 与 `(z,z)` 单侧发布仍保留。 |
| active 列表 | 每次选择分配 Vec 并 clone Rule，实际上最多一条 | 借用最早 Rule 的零/一元素 slice | v9 删除额外物化，对应 C++ 栈上的 last_rule。 |
| 聚合容器生命周期 | 每条规则重新创建 done Vec 与左右 map，publish 消耗 map | 只有最早规则的一组收集容器；drain/clear 后复用 | v9 对齐 C++ checklist 与全局左右表的生命周期。 |
| postings 释放边界 | 在 occurrence 的 Store 锁内释放所选列表 | 释放锁后释放列表，再取锁读完成分数 | v9 对齐 C++ erase 边界。 |

同时删除了原 Rust 自有的 8 字节 position、owner cache-line 对齐、零计数删除、稀疏缓冲收缩等选择；恢复两个 `u64` 的 16 字节 position 和清空后保留容量。它们属于消除非必要差异，不能都叫性能优化，更不能假定恢复 C++ 布局必然更快。

## 兼容实现中的冗余删除

这些项保持 Tokenizers 计分结果，**不是把计分语义改回 C++**。

| 点 | 为什么出现 | 删除的工作 | 状态 |
| --- | --- | --- | --- |
| 所选非自配对的抵消更新 | C++ 扣减所选 pair；Tokenizers 保留所选 pair 的 occurrence credit。Rust 原先先 `add(weight)` 再对相同 key/weight `subtract`。 | 两次哈希查找与 checked RMW 净效果为零，改为不更新所选分数；邻居事件保持原样。 | v10 已改，22 项差分测试通过，独立 review 确认普通、长度限制及 ID 复用后的路径等价；分步实验及最终矩阵见下文。 |
| 压缩 AA 的两次更新 | Tokenizers 使用 `L-1` 选择质量，并保留实际替换的 `floor(L/2)` credit。 | 将 `+w*floor(L/2)` 与 `-w*(L-1)` 合成一次 `-w*(L-1-floor(L/2))`。 | v10 已改并 review；`L>=2`，算术范围安全，`L=2` 净零时跳过查表。 |

不能把这两项描述为“C++ 行为没有对齐”。优化前后 Rust 的所选 pair 计分都按 Tokenizers，仍与原版 C++ 不同。

## 必须保留的语义与安全表示

- 同频候选按 Tokenizers 的 `(left_id,right_id)` 顺序；C++ 默认桶尾选择不同。
- AA 选择分数为重叠邻接数 `L-1`，实际替换为 `floor(L/2)`。
- 所选 pair credit、邻居计数事件、实际 live survivor，保持原始 Tokenizers 行为。
- 特殊 token、alphabet 授权、前后缀的创建顺序，以及过滤前的 first/last 位置。
- ID 复用时的 coverage、惰性 witness 顺序、reserved 候选对全部 owner 的刷新。
- 长度限制的严格邻居过滤及负分转换行为；兼容路径需要未压缩 occurrence 顺序。
- 使用 checked `i128` 容纳负分及完整权重范围；不能直接换成 C++ 的无符号计分。
- Rust 的取消、错误传播与 panic 退出保护。保护的存在有理由，普通路径是否重复检查需要另行核对。

## 仍在核对的机制与生命周期

| 项 | 已确认事实 | 当前结论 |
| --- | --- | --- |
| 源词向量释放线程 | Rust 主线程生成 token Vec，分区后 `Store::build` 在 worker 消耗并逐词释放；C++ 保留全局源词，worker 读取或本线程复制。 | v11 已改为借用 shard，源 Vec 保留至 join 后由主线程释放。正反顺序分步实验确认总耗时降低；具体 allocator 内部机制未追踪。 |
| Store 销毁线程 | Rust startup registry 持有 Arc，Store 通常最终在协调器线程销毁；C++ 的节点、postings 等是 worker 局部变量，在 worker 退出时销毁。 | v12 已在停止后由 worker 取走并释放私有容器；counts/结果仍由主线程释放。独立安全 review 与 22 项差分测试通过。 |
| 私有准备的锁范围 | Rust 清空出生集合、取 postings 位于整个 Store 锁内；C++ 私有准备在计数锁外。 | 需要先重组所有权，不能直接去锁；没有单项耗时证据。 |
| 任务表示 | C++ 两个共享 task；Rust 每 owner 两个 Task 并复制 Rule。两边结果都是每 owner 两槽。 | 任务表示尚不同；不能误说 Rust 结果槽数量翻倍。 |
| occurrence 的停止检查 | Rust 每 posting 读 stop、use_counts、再读 stop；C++ 普通路径只读一次 use_counts。 | stop 是取消保护；两次普通路径 stop 读取属于额外工作，尚未修改。 |
| 最后两条结果 | Rust 达到目标后仍汇总/发布剩余候选；C++ 最后派发后退出协调器循环，join 完成 worker。 | 最终候选已无消费者；可在保持 worker 完整执行的前提下避免汇总。尚未修改。 |
| 词与权重布局 | Rust Vec<Word>；C++ 节点与权重分列。 | 纯布局区别，不能凭源码认定分列更快。 |
| 通知锁 | 两边均有等待互斥锁配合完成通知。 | 没有证据支持“Rust 多一轮完成通知锁”。 |
| high/low 计数查询 | 独立 review 已核对 top 与协调器刷新；未发现 Rust 额外一轮全 owner count 扫描。 | 不再把剩余差距笼统归因于重复 top 刷新。 |
| 质量计算 | Rust 在 tokenization 后另扫 words/counts；C++ 在字符统计阶段累加质量。 | 一次独立遍历是额外工作；溢出检查仍需要。尚未修改，不能先认定它是主要瓶颈。 |
| 节点列表外层容量 | Rust `store.words` 从空 Vec 增长；C++ 一次 `resize` 为分区词数。 | 一次初始化时的分配表示差异；尚未修改或测量。 |
| 初始/结束护栏 | Rust 初始 frontier 取所有 owner 锁；正常结束 StartupGuard 再 stop/wake 一轮，C++ 初始化 barrier 后直接读 counts。 | 一次性工作；初始化失败和 panic 护栏需要保留。 |
| 普通模式可选功能薄层 | 空 coverage 表的交换/drain/remove，以及 born/length Option 判断仍经过普通路径。 | 普通模式没有提前分配 coverage；是否被内联消掉、实际开销待采样。 |
| 哈希容器与数值 | Rust AHashMap/Set + RandomState、i128；C++ flat_hash_map 的默认哈希和 u64。 | 是真实表示区别；没有证据支持任意换 hasher，i128 不能直接缩成 i64。 |
| API 返回 | Rust 构造字符串 vocab/merges；当前 C++ 适配器返回数字规则。 | Tokenizers API 必需成本，应单独测量；不算合并机制未对齐。 |

独立 reviewer 已完成 v10 的整条路径集中核对，覆盖清单如下。上表不代表所有非必要差异已经删除。

| 覆盖范围 | 核对的函数/分支 |
| --- | --- |
| 输入解析与初始 ID | `compute_alphabet`、`tokenize_words`、`do_train_with_workers`，single-character special、过滤前首尾、affix 创建 |
| 分区和初始化 | `train` 的质量与等词数分区，`run_initial`，`Store::build`，启动 barrier 与初始 frontier |
| 所有局部辅助更新 | `node/set/append`、`add/subtract`、边界 add/remove、AA mass、`decrement/try_merge` |
| occurrence 四分支和 AA | AA 奇/偶压缩；普通 pair 两边均 run、仅左 run、仅右 run、均单节点；flat AA 与历史长度 |
| ID 复用兼容路径 | `enable_coverage`、`expand_runs`、`begin_rule` 的 witness 保留/去重、闲置尾部与全 owner 刷新 |
| 出生与结果 | `record_birth`、`birth_scores_into`、`finish_task`、`merge_payload`、`publish` 的左右键、负/零分、`z:z` |
| 整条调度 | `pause`、`select/count`、`dispatch`、`Paused::drop`、两槽、head collect、commit、`wait` |
| 两类队列 | high 刷新/最大值选择；low 惰性重验；canonical tie 与复用 witness |
| 退出与销毁 | 目标达成、Driver/StartupGuard、初始化失败、worker error、panic、源数组和所有 Store 字段的实际销毁线程 |

C++ 的 count 表和左右结果表是全局容器，仍由主线程释放；局部节点、postings、word_freq 与出生集合才由 worker 释放。后续生命周期调整应保持这个区分。不能把整个 Rust Store 都搬到 worker 上释放后声称与 C++ 完全相同，也不能用 `clear()` 代替释放，因为 `clear()` 保留容量。

## 性能证据与版本

所有排名测量使用同一份预切分词频表及相同 AHashMap 词顺序/owner 分区；ByteLevel alphabet 为全部 256 个映射字符。1/6 worker 分别绑定 CPU 0 / 0–5。两边 portable O3/LTO，Rust 单 codegen unit；计时排除预切分、词频文件加载与导出。C++ 为加权输入适配器，保留原版 worker/queue/coordinator；同频与 AA 语义仍不同，所以不是跨语言输出 oracle。

| 版本 | EN32 ByteLevel 100K，1 / 6 worker | EN512 whitespace 50K，1 / 6 worker | 说明 |
| --- | --- | --- | --- |
| `07577061` / final | Rust `3.347 / 5.148 s`；C++ `2.966 / 4.628 s` | Rust `28.702 / 20.365 s`；C++ `23.841 / 12.203 s` | 三轮中位数；六线程大语料差距约 +66.9%。 |
| v6 | 仅单轮筛查，不作最终排名 | Rust `29.497 / 22.022 s`；C++ `24.289 / 12.742 s` | 只修锁/收集，不足以消除大语料差距。 |
| v7 | 仅单轮筛查，不作最终排名 | 单线程 Rust `23.668 s`、C++ `23.446 s`；Rust 六线程约 `16.971 s` | 字符解析改动后的方向性证据，不能单项归因全部变化。 |
| v8 | Rust `2.909 / 4.417 s`；C++ `2.920 / 4.795 s` | Rust `24.096 / 16.614 s`；C++ `23.002 / 12.297 s` | 三轮中位数；六线程大语料仍 +35.1%。 |
| v9 | Rust `2.765 / 4.346 s`；C++ `3.055 / 4.813 s` | Rust `23.335 / 16.540 s`；C++ `22.770 / 12.039 s` | 三轮中位数；六线程 +37.4%，逐轮配对 +29.9%～+40.6%。 |
| v10 | 最终矩阵未测 | 两轮分步实验见下表 | 只删除兼容计分中的抵消更新。 |
| v11 | 最终矩阵尚未测 | 生命周期分步实验见下表 | 增加源数组保留至主线程释放。 |
| v12 | Rust `2.812 / 4.052 s`；C++ `2.819 / 4.598 s` | Rust `22.736 / 10.915 s`；C++ `22.359 / 12.378 s` | 最终三轮矩阵；单线程 −0.3% / +1.7%，六线程 −11.9% / −11.8%。 |

v9 的 Rust 输出在所有重复与 worker 配置下相同，且与 `07577061` 相同。默认/无默认 feature 各 22 项单元测试、1 项文档测试通过；中英文约 1 MiB 的真实语料在 1/2/4 worker 下与 original oracle 相同；Clippy 仅有两处未修改的 oracle 字段写法警告。

### 分阶段诊断：v9，EN512，单轮

诊断副本仅在阶段边界计时，无每 posting/每规则计时；这是定位证据，不替代三轮排名。

| 阶段 | Rust 1 worker | C++ 1 worker | Rust 6 worker | C++ 6 worker |
| --- | ---: | ---: | ---: | ---: |
| alphabet / 字符 ID | 1.127 s | 1.326 s | 1.003 s | 1.331 s |
| owner 初始化与初始队列 | 4.100 s | 3.833 s | 4.155 s | 0.870 s |
| 协调器合并阶段（含等待） | 15.925 s | 15.112 s | 8.065 s | 9.021 s |
| 公开训练/适配器总时间 | 23.059 s | 22.291 s | 16.443 s | 12.192 s |

六线程差距主要出现在初始化与剩余的分区/清理工作；这次诊断中 Rust 合并阶段反而更短。总时间减去表中阶段不能全部直接叫“释放耗时”：Rust 还包括质量计算、分区、scoped join/退出、Store 销毁和输出构造。下一步需要拆开这些部分，并验证输入/Store 释放线程的影响。

### 生命周期分步验证：EN512，6 worker，正反顺序各一轮

使用同样的构建选项、输入、分区与 CPU affinity，正向 `v9→v10→v11→v12→C++`、反向 `C++→v12→v11→v10→v9`；运行期间没有编译或测试。全部 Rust 输出相同。

| 实现 | 正向轮 | 反向轮 | 与前一版本唯一新增的源码改动 |
| --- | ---: | ---: | --- |
| v9 | 17.215 s | 18.037 s | 生命周期修改前 |
| v10 | 16.245 s | 16.458 s | 删除 selected 计分中的抵消更新 |
| v11 | 12.264 s | 13.004 s | 源 token 数组留在协调器，worker 借用；join 后由协调器释放 |
| v12 | 10.876 s | 10.289 s | 停止后 worker 释放自己的节点/postings/出生集合；counts/结果保持主线程释放 |
| C++ | 11.889 s | 12.653 s | 固定原版核心的加权输入适配器 |

两轮都支持：先前的主要额外耗时来自 Rust 的初始化/清理生命周期安排，而不是 feed 或必要 Tokenizers 计分语义。尚未用 allocator trace 证明具体的锁竞争，因此不能进一步把全部改善精确归因于某一种 malloc/free 内部机制。保留源数组增加了 Rust 进程峰值 RSS：本组从 v10 约 1.95 GiB 到 v12 约 2.27 GiB，约增加 320 MiB。这个成本与保留 C++ 式源数据生命周期一起记录。

原始结果与各版本构建 ID 保存在 `lifetime-experiment-v12/results.json`、`summary.json`、`build-v10.log`、`build-v11.log`、`build-v12.log`。最终排名仍以 v12 的完整三轮矩阵为准，不把两轮分步实验当作所有负载的性能结论。

最终 v12 的 24 次运行全部成功；Rust 完整导出在两种语料的所有 worker 配置、重复中均一致，并与 `07577061` 一致。源码 hash 与最终构建快照核对通过。默认/无默认 feature 各 22 项单元测试及 1 项文档测试通过，中英文真实语料的 1/2/4 worker oracle 检查通过，Clippy 仅保留两处原 oracle 警告。最终时间、范围、逐轮配对比例与 RSS 在 `rust-cpp-v12/summary.json`。

### 修正后的分阶段诊断：v12，EN512，单轮

| 阶段 | Rust 1 worker | C++ 1 worker | Rust 6 worker | C++ 6 worker |
| --- | ---: | ---: | ---: | ---: |
| alphabet / 字符 ID | 1.038 s | 1.357 s | 1.056 s | 1.423 s |
| owner 初始化与初始队列 | 4.201 s | 3.945 s | 0.734 s | 0.861 s |
| 协调器合并阶段（含等待） | 16.050 s | 15.291 s | 7.206 s | 8.724 s |
| 公开训练/适配器总时间 | 23.390 s | 22.576 s | 9.939 s | 12.064 s |

六线程 owner 初始化由 v9 的 `4.155 s` 降至 `0.734 s`，恢复并行扩展。Rust core 总时间减去 owner/queue 初始化与合并阶段，剩余分区/join/清理由约 `3.20 s` 降至约 `0.91 s`。这与分步修改的生命周期证据相互支持；该单轮仍不能替代最终三轮排名。单 worker 的初始化差距没有相同的多线程退化，保留本次测量，不能把六线程收益直接推广到所有 worker 数。

此处性能排名和阶段诊断均不含 feed、预切分、文件加载和导出；不能据此声称 feed 已测过。生命周期一致也不意味着 RSS 一致：分步实验中 v12 Rust 约 `2.27 GiB`，C++ 约 `2.60 GiB`，还包含各自输入表示及输出容器。

本机证据目录：`/root/code/tokenizers-bpe-benchmarks/.bench/yttm-cpp-alignment/`。三轮结果在 `rust-cpp-final`、`rust-cpp-v8`、`rust-cpp-v9`；分阶段源码与日志在 `phases-v9`，Rust 诊断 worktree 为 `/root/code/tokenizers-workspaces/yttm-phase-diagnostics`。每轮 JSON、输入/源码/二进制 hash、构建选项与模型导出均保留。原先 worktree 的四个未提交文件已经核对，内容未改变。
