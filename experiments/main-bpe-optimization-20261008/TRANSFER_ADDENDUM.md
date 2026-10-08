# BPE 训练与推理优化迁移增补审查

日期：2026-10-08。审查基线：Yikai-Liao/tokenizers，提交 `8faaff79d859bfd6b2417cfe8c93ea2851c3aaca`。

本文补充双向迁移建议的正确性条件、现有机制和验证入口。结论是：若干方向值得保留为条件化实验，其中记录宽度的存储节省可以计算；吞吐收益与实施顺序均须由目标工作负载的成本剖面决定。

本次仅审读该提交源码，没有运行项目代码、测试或基准，没有修改仓库，也不评价后续 `16db…` 提交或当前 PR。粘贴材料在“现有 boun…”处截断；以下只审查可见主张及其源码对应，不补写被截断的结论。

## 一 对训练算法的优化启发

### 1 紧凑优先级

**现状。** 训练已有紧凑 slot 和分层候选结构；初始 pair key 的窄化检查范围有限。

**借鉴。** 沿用推理的字段打包思路，候选限定为可证明范围的 fresh-only 路径。

**条件。** 可考虑在 fresh-only 路径用一个 u64 保存 32 位 count 与取反后的 16 位左右 ID，维持“大 count 优先、同 count 小 pair 优先”的次序。门槛必须覆盖所有未来生成 ID，以及尚未激活但已预留的词表 ID；仅验证初始输出 ID 不足以证明整个训练过程安全。`compact_pair_keys()` 的检查只服务初始键。

计数上界可保守采用加权初始边总量，使用宽算术或 checked 运算计算；无法证明不超过 `u32::MAX` 时走原宽路径，不能因此拒绝原本合法的训练。ID 65535 在打包 priority 中可合法表示，不能套用 u16 slot 的 separator 约束。identity reuse 路径默认回退原宽 priority；分别验证计数域和 tie-break。[priority 定义](https://github.com/Yikai-Liao/tokenizers/blob/8faaff79d859bfd6b2417cfe8c93ea2851c3aaca/tokenizers/tk-train/src/trainers/bpe/engine/pair_index.rs#L83-L106) [初始键范围](https://github.com/Yikai-Liao/tokenizers/blob/8faaff79d859bfd6b2417cfe8c93ea2851c3aaca/tokenizers/tk-train/src/trainers/bpe/engine/vocabulary.rs#L272-L275) [训练分派](https://github.com/Yikai-Liao/tokenizers/blob/8faaff79d859bfd6b2417cfe8c93ea2851c3aaca/tokenizers/tk-train/src/trainers/bpe/engine/mod.rs#L231-L244)

**成本。** 增加宽窄模式、转换和维护成本。

**验证。** 测 priority 存储、比较与搬移耗时；覆盖 65535、65536、计数上界、预留 ID 和 reuse 回退。

### 2 ASCII 加稀疏 Unicode 映射

**现状。** 训练的 `0x110000` 个 u32 字符表约 4.25 MiB，属于初始化阶段，并在 corpus prepare 结束处释放。ASCII 加稀疏结构可能降低初始化峰值；额外分支和间接访问也可能增时。必须保持基于原始 UTF-8 坐标的 first/last 标志，以及按输入遍历分配装饰 token ID 的顺序。[字符表与装饰分配](https://github.com/Yikai-Liao/tokenizers/blob/8faaff79d859bfd6b2417cfe8c93ea2851c3aaca/tokenizers/tk-train/src/trainers/bpe/engine/vocabulary.rs#L132-L212) [初始化表释放](https://github.com/Yikai-Liao/tokenizers/blob/8faaff79d859bfd6b2417cfe8c93ea2851c3aaca/tokenizers/tk-train/src/trainers/bpe/engine/corpus/prepare.rs#L314-L335)

**借鉴。** 借鉴推理的稀疏字符映射，给 ASCII 快路，按需保留非 ASCII 页或索引。

**条件。** 保持过滤、装饰、原始字节坐标及初始 ID 分配顺序。

**成本。** 可能节省初始化峰值，也可能因分支和间接访问增时。

**验证。** 同时测初始化时间和峰值 RSS，区分 ASCII、CJK、混合及大 alphabet。

### 3 初始 pair 稠密网格

**现状。** 现有 bounded 构建处理临时初始记录。

**借鉴。** 借鉴推理的小 ID 稠密 lookup，为初始 symbol 集合较小的 pair 提供直接 handle 索引。

**条件。** 稠密 pair 网格应按过滤和装饰后实际会发出的初始 symbol/token-ID 集合大小 A 做紧凑映射，用 A² 算空间。u32 handle 网格在 A=256 时为 256 KiB，A=65536 时达 16 GiB。词表大小或最大 external ID 都不能直接替代 A。现有 bounded 构建是临时结构；新增长期 pair-state 网格需另证 handle 稳定性、删除与 tombstone 后的引用安全，并覆盖 active-ID reuse 的回退。也不能未经核对就假定每个 owner 各有一份完整网格。[bounded 构建](https://github.com/Yikai-Liao/tokenizers/blob/8faaff79d859bfd6b2417cfe8c93ea2851c3aaca/tokenizers/tk-train/src/trainers/bpe/engine/initial_pairs/bounded.rs)

**成本。** A² 常驻空间、清零、映射及后续迁移成本。

**验证。** 记录 A、活跃 pair 密度、lookup 占比和内存；验证 tombstone、handle 生命周期及 reuse 回退。

### 4 Hot cold 候选组织

**现状。** 训练已有八叉堆、惰性上界修复、每个 owner 缓存四个候选的前缀和全局 leader。把初始候选改为 cold 有序流，会把 heapify 成本换为排序成本；旧优先级修复后仍需与 cold、hot 及其他前沿重新比较，不能从 cold 流直接认定下一个 winner。关键量是候选数、修复率、前沿切换和堆操作的真实成本。[pair index](https://github.com/Yikai-Liao/tokenizers/blob/8faaff79d859bfd6b2417cfe8c93ea2851c3aaca/tokenizers/tk-train/src/trainers/bpe/engine/pair_index.rs)

**借鉴。** 把已知初始候选作为 cold 流，后续更新保留动态 hot 结构。

**条件。** 每次惰性修复后重新比较全部前沿，保持计数及 pair tie-break 的精确次序；active-ID reuse 默认保留原队列路径，待另证迁移条件。

**成本。** 预先排序与现有 heapify 的差额、过期项扫描以及额外队列状态。

**验证。** 测初始化候选规模、修复率、前沿切换及堆独占时间，避免只看最终 pop 次数。

### 5 Accumulator entries 容量复用

**现状。** `with_directory` 复用 directory 时仍新建 entries Vec，`into_directory` 只交还 directory。可计量局部 entries 分配与容量增长，若显著，再尝试有上限的容量复用，避免峰值容量永久滞留。这比笼统建议“复用 scratch”更具体。[构造与回收](https://github.com/Yikai-Liao/tokenizers/blob/8faaff79d859bfd6b2417cfe8c93ea2851c3aaca/tokenizers/tk-train/src/trainers/bpe/engine/storage/id_accumulator.rs#L41-L104) [执行路径](https://github.com/Yikai-Liao/tokenizers/blob/8faaff79d859bfd6b2417cfe8c93ea2851c3aaca/tokenizers/tk-train/src/trainers/bpe/engine/execution.rs#L65-L95)

**借鉴。** 沿用推理可复用缓冲的思路，把 directory 与有界 entries 容量一起回收。

**条件。** 清空逻辑内容并保留 directory 索引一致性，防止跨任务残留。

**成本。** 保留容量会提高常驻内存，需设容量上限或回收策略。

**验证。** 统计 entries 分配次数、增长量、耗时和峰值/稳态内存，确认分配确实构成成本。

## 二 对推理算法的优化启发

### 1 Affix 预解析表

**现状。** 当前 `convert_affixed` 在 64 字节栈缓冲中拼接，随后哈希查找并映射内部 ID；没有逐字符堆分配。源码明确选择了以查询成本换常驻表空间的方案。[转换实现](https://github.com/Yikai-Liao/tokenizers/blob/8faaff79d859bfd6b2417cfe8c93ea2851c3aaca/tokenizers/tk-encode/src/models/bpe/convert.rs#L270-L334)

**借鉴。** 借鉴训练的预解析，把字符及首尾状态直接映射到内部 ID。

**条件。** 训练装饰表通过 plain ID 索引，plain 缺失时跳过；推理允许 plain 不存在但 decorated spelling 存在。新表应直接表达“字符 × 首尾状态 → 可选内部 ID”，独立构建各种形式，保留单字符词、空 affix、Unicode、missing-decoration 及 byte fallback/unk/跳过语义。当前 affix fallback 没有应用 `fuse_unk`，普通字符路径有；性能修改应保持基线行为，语义修复另行核对。

**成本。** 四张完整 Unicode u32 表合计 17 MiB，宜评估稀疏或分页表示，并计入构建时间及可能释放的 `to_internal` 映射。表只在 affixed 模型启用，也仍需证明实际转换成本足够高。

**验证。** 测 affixed 模型中缓存未命中的转换占比；覆盖 decorated-only、首尾组合、fallback 和未知字符序列。

### 2 多规则固定 rank 前缀

**现状。** 已有单规则 SAFE 批处理，min_rank_left/right 仅在建表时使用。

**借鉴。** 借鉴训练的保序独立规则前缀，一次扫描应用多条可认证规则。

**条件。** 推理已经计算 `min_rank_left/right`，并用 SAFE 位认证同一规则的多次出现。若一次扫描融合多个规则，设最大 rank 为 R，则每个 replacement 都须满足 `min(min_rank_left[p], min_rank_right[p]) > R`；扩展 R 时要重新约束前面所有产物。另须排除 crossed head/tail 冲突，AA 单独处理，并保证选择的是保序前缀。[SAFE 构建](https://github.com/Yikai-Liao/tokenizers/blob/8faaff79d859bfd6b2417cfe8c93ea2851c3aaca/tokenizers/tk-encode/src/models/bpe/tables.rs#L136-L181) [训练批选择](https://github.com/Yikai-Liao/tokenizers/blob/8faaff79d859bfd6b2417cfe8c93ea2851c3aaca/tokenizers/tk-train/src/trainers/bpe/engine/batch.rs#L13-L98)

仅逐规则 SAFE 不够：rank 1 的合并产生 rank 2 邻接时，不能把 rank 3 规则提前。训练依赖频率和新 ID 的证明也不能直接移植。运行时选前缀、成员查找和持久化元数据的成本，应与节省的扫描同时计量。

**成本。** 新增前缀选择、成员查询及元数据；静态分组还可能包含该词不存在的规则。

**验证。** 统计前缀实际宽度、选择耗时和减少的扫描数；覆盖新生低 rank 邻接、端点冲突及 AA。

### 3 Cold keys 稳定 radix 排序

**现状。** 已有 cold vector 加 hot heap，cold 使用比较排序。

**借鉴。** 借鉴训练稳定 radix，重点考察 cold 候选足够多的长词。

**条件。** 推理已有 cold vector 加 hot heap。初始 cold keys 按 entry index 递增进入，因此稳定地只排序 rank 就能保留同 rank 左到右次序；不稳定 rank-only 排序会破坏它。训练 radix 有每次调用 scratch 分配、经典 scatter/块置换切换及输入规模限制，迁移应适配推理的可复用 scratch，并按 cold-key 数选择算法。[cold sort](https://github.com/Yikai-Liao/tokenizers/blob/8faaff79d859bfd6b2417cfe8c93ea2851c3aaca/tokenizers/tk-encode/src/models/bpe/merge_hot_cold_queue.rs#L88-L146) [训练 radix](https://github.com/Yikai-Liao/tokenizers/blob/8faaff79d859bfd6b2417cfe8c93ea2851c3aaca/tokenizers/tk-train/src/trainers/bpe/engine/storage/radix.rs#L376-L448)

**成本。** scratch、逐趟读写与初始化；小词可能不抵这些固定开销。

**验证。** 按 cold-key 数测交叉点及排序独占时间，复用 scratch，并验证 equal-rank 左到右。

### 4 Entry 条件窄化

**现状。** 推理队列 Entry 保存 rank、三个 symbol 和两个 link。

**借鉴。** 借鉴训练按数据域选择窄记录的做法，保留宽记录后备路径。

**条件。** `Entry` 为六个 u32，共 24 字节，没有可直接消掉的 padding。仅把两个 link 改为 u16 可到 20 字节，Entry 空间减少约 16.7%；三个 symbol 字段也满足 u16 范围时，可达含对齐的 16 字节，减少约 33.3%。这些比例只针对 Entry。必须保留宽路径，并核对 link sentinel、全部可达内部 ID、dead rank 与无 merge 的占位字段。多个规则可能产生同一 token，不能从 product ID 无条件恢复 rank。[Entry 及邻接更新](https://github.com/Yikai-Liao/tokenizers/blob/8faaff79d859bfd6b2417cfe8c93ea2851c3aaca/tokenizers/tk-encode/src/models/bpe/merge_hot_cold_queue.rs#L200-L249)

**成本。** 窄宽分支、转换、布局和潜在额外指令；空间下降不保证吞吐改善。

**验证。** 验证边界与 sentinel，分别报告 Entry 字节、总 scratch、cache miss 和端到端耗时。

### 5 AA 连续段终态更新

**现状。** 推理队列按合并逐次重写邻居；训练已有 AA 非重叠选择与跨 chunk 奇偶处理。

**借鉴。** 对已认证安全的重复段，减少会立即失效的中间邻接查找和入队。

**条件。** 可借鉴训练的左到右非重叠选择，减少安全 AA 连续段内的瞬态邻接查找与入队。当前单词推理无需跨 chunk 奇偶传递；只有以后分块处理同一段时才需要该机制。最终仍须维护所有存活邻接，包括内部 P–P 以及奇数段的 P–A；只更新段的两个外端点会漏掉候选。若产物可立即形成更低 rank 的合并，整段延后更新需回退。[AA 选择](https://github.com/Yikai-Liao/tokenizers/blob/8faaff79d859bfd6b2417cfe8c93ea2851c3aaca/tokenizers/tk-train/src/trainers/bpe/engine/merge/prepare/aa.rs)

**成本。** 段识别及终态邻接维护的额外分支。

**验证。** 统计 AA 段长度、瞬态 lookup/入队量，覆盖奇偶长度、外部抢先合并和最终 P–P/P–A 候选。

### 6 有限跨度的 probe 重叠

**现状。** 推理按 span 顺序执行 cache probe、fold、merge 和 cache insert。

**借鉴。** 借鉴训练有限 lookahead/prefetch 环，提前计算少量后续 hash 或预取。

**条件。** 训练普通合并的 lookahead/prefetch 环可启发对少量后续 span 提前计算 hash 或预取。必须保留输出顺序和缓存修改语义；前面 span 的插入可能使后面预存的 insertion position 失效，需要重新验证。先测 cache miss、内存等待及依赖链，再决定是否值得增加状态。[训练预取](https://github.com/Yikai-Liao/tokenizers/blob/8faaff79d859bfd6b2417cfe8c93ea2851c3aaca/tokenizers/tk-train/src/trainers/bpe/engine/merge/prepare/ordinary.rs#L249-L277) [推理 probe 与插入](https://github.com/Yikai-Liao/tokenizers/blob/8faaff79d859bfd6b2417cfe8c93ea2851c3aaca/tokenizers/tk-encode/src/models/bpe/model.rs#L292-L383)

**成本。** 额外暂存、预取带宽、位置重验证；应限制 lookahead 深度。

**验证。** 先测 cache miss、内存等待和依赖链；覆盖重复 span、冲突替换及前序插入影响。

## 附录 共同验证与已有能力

双方已有线程资源或池、流式转换、编译期特化与小任务批处理。这些一般性方向不再作为新增建议。

先在目标模型和语料上取得阶段独占时间、缓存命中、冷路径覆盖率、分配量和峰值内存；再选择有可见成本的单项实验。正确性覆盖应包含 sparse external IDs、decorated-only 字符、未知字符、相同 rank 的左到右次序、AA 奇偶段、identity reuse 和各窄化边界。分别报告输出等价、局部指标与端到端变化，并计入加载时间和内存。本文给出可验证的条件及存储算术，未给出实测加速结论。

## 附录 适用条件与成本矩阵

| 迁移机制 | 适用工作负载 | 当前已有实现 | 正确性门槛 | 新增成本 | 决定是否实验的指标 |
| --- | --- | --- | --- | --- | --- |
| 推理式紧凑优先级用于训练 | 可证明计数和 ID 上界的 fresh 路径 | 训练已有紧凑 slot、分层优先级 | 全生命周期 ID 与计数上界；保持 tie-break | 模式分支、宽窄两套路径 | priority 内存占比、比较/搬移时间 |
| ASCII 加稀疏 Unicode 初始映射 | 小字母表、初始化内存受限 | 训练已有直接 Unicode 索引 | 原 UTF-8 位置、装饰与 ID 分配顺序 | 分支、额外间接访问 | 初始化耗时、峰值 RSS、字符分布 |
| 训练初始 pair 稠密网格 | 实际初始 symbol 集合小且 pair 较密 | 已有 bounded 临时构建 | handle 与 tombstone 生命周期、reuse 回退 | A² 空间、清零与迁移 | A、活跃密度、lookup 成本 |
| 推理 hot/cold 思路用于训练 | 初始候选多、后续修复较少 | 八叉堆、惰性上界修复、每个 owner 的四候选前缀与全局 leader | 修复后重新比较所有前沿 | 初始排序、扫描与过期项 | heapify/排序、修复率、堆时间 |
| 训练 entries 容量复用 | accumulator 频繁分配 | 已复用 directory | 清空内容、索引一致性 | 有界容量常驻 | 分配次数、耗时与稳态内存 |
| 训练 affix 预解析用于推理 | 带 affix 且缓存未命中的模型 | 栈缓冲拼接、词表查找 | decorated-only 字符、fallback、位置标志 | 建表时间与常驻表 | affix 转换独占时间、命中率 |
| 多规则固定 rank 前缀 | 同词存在多个可独立合并规则 | 单规则 SAFE 批处理 | 所有产物消费 rank 大于 R；端点冲突；AA 特判 | 前缀选择、成员检测、元数据 | 可合并前缀宽度、少扫轮数与选择成本 |
| 稳定 radix 排 cold keys | cold 候选足够多的长词 | cold 排序加 hot 堆 | 相同 rank 保持左到右 | scratch、多趟读写 | cold key 数、排序占比与交叉点 |
| 推理 Entry 窄化 | arena 与内部 ID 满足范围 | 六个 u32 字段 | sentinel、全部可达 ID、宽路径回退 | 扩展/截断、布局和分支 | Entry 字节、cache miss、转换成本 |
| AA 连续段终态更新 | 重复段多且可证明安全 | 训练有跨 chunk 奇偶选择 | 更低 rank 不抢先；所有最终邻接完整 | 段识别、边界维护 | AA 长度、瞬态 lookup/队列项占比 |
| 推理有限 lookahead | probe 内存等待明显 | 顺序 cache/fold/merge | 缓存突变、插入位置重验证、输出保序 | 暂存与预取带宽 | miss、等待、依赖链耗时 |

矩阵中的条件不构成性能优先级。推理还要先扣除 word cache 和已证明的 whole-word fold 命中；训练应区分初始化、selection、prepare、commit。只优化少量冷路径，整体收益上限也会很小。[推理调度及缓存路径](https://github.com/Yikai-Liao/tokenizers/blob/8faaff79d859bfd6b2417cfe8c93ea2851c3aaca/tokenizers/tk-encode/src/models/bpe/model.rs#L148-L171) [缓存与折叠](https://github.com/Yikai-Liao/tokenizers/blob/8faaff79d859bfd6b2417cfe8c93ea2851c3aaca/tokenizers/tk-encode/src/models/bpe/model.rs#L292-L383)

