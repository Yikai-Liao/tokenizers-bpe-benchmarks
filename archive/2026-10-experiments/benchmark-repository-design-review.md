# BPE 独立 benchmark 仓库审计与设计建议

日期：2026-10-06  
审计仓库：`Yikai-Liao/tokenizers-bpe-benchmarks`  
审计提交：`e2aa31fcad211bc5578c1196d4be472b398ecaa4`

本文给出目标文件结构、测量协议、构建与输入身份、结果格式、续跑规则和迁移步骤。审计通过只读源码检查完成，没有运行 benchmark、编译 Rust 或检查二进制源码压缩包。问题描述给出静态可达的触发条件，不据此断言已归档历史结果受到影响。

## 1 目标与核心决策

仓库承担三个具体任务：比较 BPE 训练实现，检查多线程扩展表现，为上游 PR 提供可复现证据。

采用以下设计：

1. 一个 Python CLI，负责准备输入、构建、进程监督、实验记录和报告。
2. 一个 Rust runner，提供 `core` 和 `pipeline` 两种测量模式。
3. 每个被测版本单独构建 runner，使用同一个 job/result 协议。
4. 输入、构建产物和实验计划使用不可变身份；续跑只复用身份完全相符的结果。
5. 正确性失败永久保留在实验报告中，后续重试不能抹掉。
6. 历史实验和临时优化 patch 移入归档，日常评测代码独立于归档。

第一阶段支持当前使用的 Linux 环境、Rust BPE trainer、明确的 CPU affinity 和 worker 数。保持依赖和接口规模小，按真实版本差异添加少量 adapter。

## 2 当前实现中值得保留的部分

- 每个样本使用独立进程，具备超时和内存保护。
- 两臂交替顺序、多臂轮换等控制已经存在。
- 配对比值在 block 内计算，再求中位数。
- 模型比较保留完整 vocabulary ID 和完整 merges 顺序。
- 训练计时结束于模型结果返回，JSON 输出位于计时之外。
- 文档区分训练边界、进程 HWM 和全进程 RSS 采样，也说明测量波动的局限。

迁移时复用这些实现和测试，重点修复身份校验、失败持久化和入口混杂。

## 3 审计发现与处理要求

### 3.1 当前 frontend 绕过公共 feed

根目录 builder 选择的 runner 自己串行读取、预分词和计数，然后直接调用 `do_train(&words)`。因此现有 `feed_seconds` 表示公共的串行前端成本，无法测量你正在推进的 `Trainer::feed` 并行优化。

处理：保留它作为受控训练内核评测；增加真实公共 feed 的 pipeline 模式。现有历史数据标明 `common_serial_frontend`，继续保留其准确边界。

来源：[runner](https://github.com/Yikai-Liao/tokenizers-bpe-benchmarks/blob/e2aa31fcad211bc5578c1196d4be472b398ecaa4/bpe-suite/multicore-runner/src/main.rs#L129-L244)。

### 3.2 探索缓存可进入正式回归

runner 读取继承的 `TK_WORD_COUNTS_CACHE` 等变量，缓存只检查路径、文件大小、split 和版本。同一路径换成同样大小的新文本后，旧词频仍可能被接受。两臂使用同一旧缓存时，模型比较仍可通过，而 protocol 记录的是新文本 hash。

处理：正式运行从显式 job 选择模式；pipeline 禁用词频缓存。core 的准备输入用内容 hash 和预处理身份验证。清理或拒绝影响行为但未声明的探索变量，并验证 runner 返回的实际模式。

来源：[缓存判断](https://github.com/Yikai-Liao/tokenizers-bpe-benchmarks/blob/e2aa31fcad211bc5578c1196d4be472b398ecaa4/bpe-suite/multicore-runner/src/main.rs#L129-L161)、[环境传递](https://github.com/Yikai-Liao/tokenizers-bpe-benchmarks/blob/e2aa31fcad211bc5578c1196d4be472b398ecaa4/regression.py#L63-L75)。

### 3.3 旧入口可能给旧结果写上新身份

旧 suite 的 prepare 保留已存在的 sources，却覆盖 prepared.json。随后配置检查会接受新 manifest，run 还会跳过旧 block。复用输出目录并改变 revision 或 workers，可造成新计划与旧源码、旧测量混合。

处理：prepare 在写入前检查既有身份。发生差异就拒绝复用，创建新实验目录。scaling 使用同一检查。

来源：[prepare](https://github.com/Yikai-Liao/tokenizers-bpe-benchmarks/blob/e2aa31fcad211bc5578c1196d4be472b398ecaa4/bpe-suite/suite.py#L50-L122)、[结果复用](https://github.com/Yikai-Liao/tokenizers-bpe-benchmarks/blob/e2aa31fcad211bc5578c1196d4be472b398ecaa4/bpe-suite/suite.py#L266-L289)。

### 3.4 模型不一致可能漏出汇总

execute 写出单次 mismatch 后抛异常，调用者来不及写 block.json。report 只扫描 block.json；续跑又把未完成目录归为 interrupted 并跳过。结果是正确性失败在局部文件中存在，却没有进入汇总失败清单。

处理：由 supervisor 持久化每次 attempt 和失败事件，统计 block 完整性与报告失败分别实现。

来源：[抛异常](https://github.com/Yikai-Liao/tokenizers-bpe-benchmarks/blob/e2aa31fcad211bc5578c1196d4be472b398ecaa4/bpe-suite/suite.py#L219-L229)、[block 与 report](https://github.com/Yikai-Liao/tokenizers-bpe-benchmarks/blob/e2aa31fcad211bc5578c1196d4be472b398ecaa4/bpe-suite/suite.py#L276-L324)。

### 3.5 CPU 配置校验缺失

regression 允许空 cpu_set，也允许 workers 大于可分配 CPU 数。切片会静默缩短 affinity，空列表还会关闭 taskset。这样可能将四 worker 固定在一个 CPU，或完全失去固定。

处理：默认要求非空 CPU 集，且每个 workers 满足 `1 <= workers <= len(cpu_set)`。记录实际 affinity 和 CPU 拓扑；区分逻辑 CPU、物理核心和 SMT。

来源：[配置校验与切片](https://github.com/Yikai-Liao/tokenizers-bpe-benchmarks/blob/e2aa31fcad211bc5578c1196d4be472b398ecaa4/regression.py#L43-L64)。

### 3.6 构建与语料 provenance 不完整

当前 build-provenance 主要 hash 两个 crate 下的 Rust 文件，遗漏 runner、manifest、lock、其他本地依赖和 vendored Rayon 等输入。语料准备会接受已有 raw shard，将其实际 hash 与固定 URL 一起记录，却通常未与预期 hash 核对。

处理：记录完整构建输入身份；所有可复用原始 shard 都必须验证预期内容身份。记录一个实际 hash 只说明用了什么文件，不能自动证明该文件来自所声称的数据版本。

来源：[构建记录](https://github.com/Yikai-Liao/tokenizers-bpe-benchmarks/blob/e2aa31fcad211bc5578c1196d4be472b398ecaa4/build_runner.py#L35-L50)、[语料缓存](https://github.com/Yikai-Liao/tokenizers-bpe-benchmarks/blob/e2aa31fcad211bc5578c1196d4be472b398ecaa4/prepare_gb_corpus.py#L38-L48)。

### 3.7 文档与证据版本需要对齐

README 指向的候选是 `8176f5e`；目前引擎讨论基线是 `d857cfee`。指定 simplification 目录可见的是构建、测试日志和语料 manifests，尚未看到对应 protocol、samples 与性能 summary。源码压缩包可能支持独立复现，但本次未检查其字节内容。

处理：每份结论链接精确实验 ID 和源码。明确区分 retained baseline、simplification 回归、上游对比和正式最终版本。

## 4 目标文件结构

```text
tokenizers-bpe-benchmarks/
├── README.md
├── LICENSE
├── pyproject.toml
├── bench/
│   ├── __init__.py
│   ├── __main__.py
│   ├── config.py
│   ├── inputs.py
│   ├── builds.py
│   ├── runs.py
│   └── reports.py
├── runner/
│   ├── Cargo.toml
│   └── src/
│       ├── main.rs
│       ├── protocol.rs
│       ├── core.rs
│       ├── pipeline.rs
│       ├── model_output.rs
│       └── adapters/
│           └── tk_train_v1.rs
├── locks/
│   └── <build-profile>/Cargo.lock
├── experiments/
│   ├── core-small.json
│   ├── pipeline-small.json
│   └── scaling.json
├── datasets/
│   ├── README.md
│   └── wikipedia-zh.json
├── tests/
│   ├── fixtures/
│   ├── test_inputs.py
│   ├── test_build_identity.py
│   ├── test_resume.py
│   ├── test_failures.py
│   ├── test_reports.py
│   └── test_protocol.py
├── results/
│   └── <published-experiment-id>/
├── archive/
│   └── 2026-10-experiments/
└── .github/workflows/check.yml
```

本地 `.bench/` 保存下载缓存、源码快照、构建缓存和工作实验目录，加入 gitignore。`results/` 只发布经过选择且可复核的记录，避免把所有临时大文件放进默认阅读路径。

初期 adapters 只有一个实现即可。出现真实 API 差异时添加薄适配文件，并让配置显式选择。避免为了假设中的兼容需求提前建立插件注册系统。

## 5 各模块的职责

### Python

- `config.py`：解析和检查配置，展开默认值，生成规范化计划。
- `inputs.py`：下载验证、语料加工、词频准备、输入 hash 与 manifest。
- `builds.py`：固定 revision、准备 runner manifest 和 lock、构建、保存完整 provenance。
- `runs.py`：单一实验写入者；安排 paired blocks、启动子进程、监控资源、记录 attempts、处理续跑。
- `reports.py`：只读原始记录，生成正确性、失败、耗时和扩展性汇总。
- `__main__.py`：薄命令入口。

### Rust

- `protocol.rs`：job/result 的结构与版本。
- `core.rs`：装载受控词频输入后测量公共 do_train。
- `pipeline.rs`：使用被测版本真实公共 feed 和训练入口。
- `model_output.rs`：计时之外输出 canonical vocabulary IDs 与 ordered merges。
- `adapters/`：API 形状转换，显式报告不支持的选项。

adapter 不实现自己的 BPE，也不静默丢弃 prefix、suffix、max_token_length 等配置。

## 6 两种测量模式

| 项目 | core | pipeline |
| --- | --- | --- |
| 主要问题 | 训练算法本身快多少、占多少资源 | 公共 feed 与完整训练流程表现如何 |
| 输入 | 固定 weighted words 与重建规则 | 固定原始文本及预处理语义 |
| 计时起点 | 准备好的词频 map 交给 do_train 前 | 开始消费输入并执行公共 feed 前 |
| 计时终点 | do_train 返回完整 vocab/merges | 公共训练入口返回约定结果 |
| 预处理计时 | 单独记录，排除于 core 训练耗时 | 纳入 feed/整体耗时 |
| 词频缓存 | 允许显式、按身份验证的 prepared input | 禁止通过词频缓存绕过公共 feed |
| 最终模型输出 | 计时之外 | 计时之外 |

### core 细节

复用现有词频准备逻辑，但准备产物具有稳定格式版本，记录文本 hash、preprocessing 配置、准备工具 revision 和输出 hash。固定词条重建顺序以及所需的 hash-map seed，避免容器遍历差异混入算法比较。

将 prepared input 装入内存、验证和重建 map 放在计时前。报告保留加载耗时，训练主指标始于 do_train。进程 HWM 仍可能包括输入装载，因此名字必须准确。

### pipeline 细节

通过真实公共 `feed` 调用完成预处理和词频累积，再调用公共训练方法。lazy iterator 的文件读取成本计入 feed 边界；如果预加载文本，必须独立标注这种输入模式和加载成本。

至少返回 feed 耗时、训练入口耗时和整体耗时。若模型构建另有阶段，单列字段；无法测量的阶段标记 unavailable，不能填零。serialization 和验证位于主计时之外。

core 和 pipeline 可以使用相同文本来源，但两者只有在预处理和输入语义相同的情况下才要求产生相同模型。跨版本比较必须先明确语义契约。

## 7 配置示例

以下是目标协议示例，不代表现有仓库已经支持这些字段。

```json
{
  "schema_version": 1,
  "name": "bpe-core-zh-small",
  "mode": "core",
  "arms": {
    "baseline": {
      "repository": "https://github.com/huggingface/tokenizers",
      "revision": "bbccb0513ff9afda385ca5c85c66eddb1318cfc7",
      "adapter": "tk_train_v1",
      "lock_profile": "baseline"
    },
    "candidate": {
      "repository": "https://github.com/Yikai-Liao/tokenizers",
      "revision": "d857cfeecc659449550c6f5ff37438c6d0ebffd5",
      "adapter": "tk_train_v1",
      "lock_profile": "candidate"
    }
  },
  "input_manifest": "datasets/wikipedia-zh.json",
  "cases": [{
    "name": "zh-256m-whitespace",
    "size_mib": 256,
    "pretokenizer": "whitespace",
    "trainer": {
      "vocab_size": 100000,
      "min_frequency": 2,
      "prefix": null,
      "suffix": null,
      "max_token_length": null
    }
  }],
  "execution": {
    "workers": [1, 2, 4, 8],
    "cpu_set": [0, 2, 4, 6, 8, 10, 12, 14],
    "warmups_per_cell": 1,
    "paired_blocks": 5,
    "order": "balanced-alternating",
    "timeout_seconds": 600,
    "min_available_gib": 3,
    "max_process_rss_gib": 12
  },
  "build": {
    "profile": "release",
    "rustflags": "-C target-cpu=native",
    "dependency_policy": "recorded-per-arm"
  },
  "comparison": "exact-model"
}
```

CPU 列表只是例子，必须根据机器 topology 填写。线程数代表 worker 数；物理核心数从映射另行报告。正式计划保存展开后的全部默认值和解析后的 commit SHA。

## 8 构建身份与依赖政策

每个 arm 的 build identity 至少包含：

- 目标 commit/tree；使用本地修改时保存完整可重建快照和 dirty 状态。
- benchmark revision、runner 和 adapter 内容 hash。
- 生成的 Cargo.toml、实际 Cargo.lock、features 和所有 build flags。
- rustc/Cargo 版本、target、链接相关环境。
- 全部本地依赖及 vendored dependency 的内容身份。
- binary hash；使用 native CPU 编译时记录 CPU 特征。

独立 runner crate 需要自己的 dependency lock。不能假设复制目标库的 lock 就完整固定了 runner 的依赖图。为每个支持的 build profile 准备并保存 runner lock，正式构建使用 `--locked`；不兼容时明确失败并准备新的 profile。

保留两个清楚标注的实验类别：

1. **各版本实际依赖图**：记录每个 arm 的真实依赖闭包，用于描述版本整体表现。
2. **受控共同依赖图**：在确实兼容时固定共同依赖，研究训练实现差异。

旧实验将 HF/peer BPE 移入 Full 的 skeleton，属于第二类中的移植对照。其 smoke native 对照不能自动证明所有大输入和配置完全等价。报告必须写明移植范围，native timings 与 ported timings 分开列。

## 9 输入身份与缓存

原始数据 manifest 保存 dataset revision、配置、shard URL、预期 hash 和许可信息。已有缓存命中也检查预期 hash，失败后停止或重新下载。

加工输入记录：原始内容身份、准备工具 revision、过滤和归一化规则、顺序、目标大小、实际字节数、条目数及输出 hash。Wikipedia 连续前缀明确标注为有序切片，较小规模是嵌套前缀，不能当成多个独立抽样数据集。

prepared word counts 的身份由原始输入内容及 preprocessing 语义共同决定。路径仅用于定位文件。每次复用必须校验内容身份，且校验发生在主计时之前。

正式子进程只接收经构造的环境。保留必要系统变量和显式声明的测量设置；拒绝或清除影响算法、缓存、线程和分配器行为的未声明变量。需要测试 vendored Rayon 的设置时，把它写入该 arm 的已记录 profile。

## 10 实验目录与不可变计划

```text
.bench/runs/<experiment-id>/
├── spec.json
├── environment.json
├── events.jsonl
├── builds/
│   ├── baseline.json
│   └── candidate.json
├── attempts/
│   └── <attempt-id>/
│       ├── job.json
│       ├── result.json
│       ├── stdout.log
│       ├── stderr.log
│       └── model.json
└── report/
    ├── summary.json
    ├── comparisons.csv
    └── REPORT.md
```

`spec.json` 在实验开始后不可覆盖。experiment identity 包含有效配置、构建身份、输入身份、adapter/protocol/comparator 版本、配对顺序及静态执行条件。工作目录等定位信息可以独立记录，避免搬路径无故改变语义身份。

同一输出目录遇到身份差异时 fail closed。动态 host load、可用内存和采样值进入 attempt 记录；它们不是每次产生新 ID 的理由。续跑需要再次核对机器、affinity、二进制和输入条件。

## 11 状态与续跑协议

Python supervisor 是状态记录的唯一写入者。Rust 子进程只输出自身结果和日志。

每次 attempt 有唯一 ID。启动前记录 planned/running，完成后记录以下终态之一：

- ok
- model_mismatch
- resource_guard
- timeout
- process_error
- invalid_output
- interrupted

记录前一次 attempt 后，重试分配新 ID；不覆盖旧日志和失败。进程被杀死时无法依靠 Rust 自行 flush，因此 supervisor 必须保存 exit code、signal、stderr 和已取得的资源信息。

退出码 137 等只能说明进程被 kill；没有系统/cgroup 证据时不要直接标记 OOM。恢复时将失去子进程且没有终态的 running attempt 标记 interrupted。

正确性 mismatch 使实验保持可见的 correctness_failed 状态。可按明确操作进行诊断性重试，但成功重试不能清除历史 mismatch 或自动把实验提升为有效性能结论。

report 无论是否存在完整 block，都读取所有 attempts。完成的配对样本用于性能统计，全部失败另行汇总。避免因统计排除而隐藏失败。

## 12 测量与配对统计

每个 timed attempt 使用新进程。warmup 次数、每个 case/worker 的配对次数和执行顺序提前固定。两臂用平衡 AB/BA，多臂用记录种子的平衡调度；保存实际执行顺序。

同一 block 的各 arm 使用相同输入、配置和 CPU 分配。只对所有要求的 arms 均有效的 block 计算配对比值。报告同时给出尝试 block 数、完整 block 数、排除数和排除原因，避免只展示幸存样本。

建议结果至少包含：

- 各 arm 各 worker 的原始 wall/CPU 时间和 process HWM。
- 同 worker 下 baseline/candidate 的配对比值及其中位数。
- 每个 arm 自身的 T1/Tp 与 parallel efficiency。
- 观察到的 min/max 或其他明确统计区间。
- 失败、timeout、resource guard 和 correctness 状态。

区间含义按实际统计方法命名。预先固定重复次数，避免跑到出现有利结果才停止。性能结论限定于当前输入、机器与边界。

## 13 runner 结果协议

以下字段表示建议方向，具体数值仅为结构示例：

```json
{
  "protocol_version": 1,
  "attempt_id": "block-03-zh256-w4-candidate-01",
  "build_id": "<content hash>",
  "input_id": "<content hash>",
  "mode": "pipeline",
  "workers_requested": 4,
  "effective_affinity": [0, 2, 4, 6],
  "timing_boundary": "public-feed-and-train-before-serialization",
  "metrics": {
    "feed_seconds": 1.0,
    "train_seconds": 2.0,
    "pipeline_seconds": 3.1,
    "train_cpu_seconds": 6.0,
    "process_hwm_kib_before_validation": 123456
  },
  "output": {
    "model_path": "model.json",
    "actual_vocab": 100000,
    "actual_merges": 90000
  }
}
```

supervisor 验证 protocol、attempt/build/input 身份、实际模式、有限非负数值、必要字段和模型文件，然后写自己的持久化 result。stdout 可以只输出一个结构化结果，诊断文本写 stderr。

HWM 是进程自启动以来到读取时的峰值，不能标为增量训练内存。supervisor 全进程采样 RSS 还可能包含序列化阶段，应单列指标。若需要严格的阶段峰值，另设计采样协议，并说明采样分辨率。

## 14 正确性验证

保留完整 vocabulary 字符串与 ID 映射，以及完整 merges 的 rank 顺序。canonicalization 只消除无语义的表现差异，例如 JSON 对象键顺序；不能重新分配 token ID 或排序 merges 来制造一致。

每次 timed run 都在计时后生成并检查结果。保留一个可复核的 canonical model 或可访问的内容寻址引用；不一致时保留双方模型和首个差异说明。

core 可额外比较 prepared word-count fingerprint。pipeline 如果内部词频不可访问，就以已固定预处理语义、输入身份和模型输出为验证边界，明确无法检查内部 map。

某些配置存在初始化顺序或历史语义差异。先重复 reference 自身验证稳定性；不能通过削弱比较来掩盖差异。若 exact-model 条件在该配置不成立，报告独立的语义不匹配，并暂停相应性能结论。

若以后支持 special tokens，将配置和输出中相关信息纳入比较。当前 job 不提供 special tokens，这项属于扩展要求。

## 15 测试设计

### Python 协议与监督测试

- 同路径、同大小、不同文本的缓存必须失效。
- raw shard 缓存 hash 不符必须拒绝。
- revision、binary、input、trainer 或 CPU 配置变化时拒绝复用实验。
- 第一个 block 成功、第二个模型 mismatch 后，报告仍包含失败。
- mismatch 重试成功后，历史失败仍保留。
- runner 无输出、非法 JSON、NaN、缺字段、崩溃、timeout、signal 均落入持久终态。
- supervisor 中断后恢复能识别 orphaned running attempt。
- 空 cpu_set、重复 CPU、不可用 CPU、worker 超过 CPU 数均被拒绝。
- 失败 block 排除与失败报告独立。
- AB/BA 调度及配对比值计算有固定小样本断言。

### Rust 与集成测试

- 小型确定性输入测试两个模式的协议和输出。
- 检查指定 adapter 实际调用公共 feed。
- 验证 ByteLevel、whitespace、无 split、affix 和边界配置的明确语义。
- 同配置跨 worker 比较完整模型。
- 测量模式变更不会由环境变量静默触发。

CI 跑快速 correctness 和监督协议测试。大语料、多核扩展和性能门槛在明确机器上手动执行，避免共享 CI 噪声成为主要性能证据。

## 16 现有文件迁移表

| 当前文件或目录 | 目标位置或处理 | 保留内容 |
| --- | --- | --- |
| `regression.py` | `bench/runs.py` 与 `reports.py` | 配对调度和统计，补齐身份及失败协议 |
| `build_runner.py` | `bench/builds.py` | 独立构建入口，扩展完整 provenance 和 lock policy |
| `prepare_gb_corpus.py` | `bench/inputs.py` | pinned corpus recipe，补全部缓存 hash 校验 |
| `bpe-suite/multicore-runner/src/main.rs` | `runner/src/` | 训练计时和 canonical output，拆出显式 core/pipeline |
| `bpe-suite/suite.py` | 提取通用监督逻辑，其余归档 | taskset、timeout、RSS、完整模型比较 |
| `bpe-suite/scaling.py` | 合并为同一 execution 配置 | worker sweep，不另维护第二套 runner 状态机 |
| `bpe-suite/variants.py`、templates、实验 patch | `archive/2026-10-experiments/` | 完整历史及来源 |
| `history/vendor/rayon-core` | 随历史 baseline 归档 | 原许可证和可复现内容 |
| 历史 results | 归档，保留原 manifest | 原始数据与历史结论，不改写成新实验 |
| `source-snapshots/` | 保留为历史复现资产 | 固定 archive hash 和源码身份说明 |
| 当前测试 | `tests/`，按职责组织 | 原断言并补本审计发现的集成缺口 |
| 根 README | 改为日常使用入口 | 两种模式、准备/构建/运行/报告、已发布证据 |

活跃模块不得 import archive。迁移初期可以保留旧入口作为明确标注的历史复现命令；它不应继续充当新入口的隐式依赖。

## 17 实施顺序和完成条件

1. **先修可信度问题**：缓存模式隔离、不可变实验身份、完整失败记录、CPU 参数校验。为每项问题加最小回归测试。
2. **提取通用模块**：保留现有已验证测量逻辑，将活跃代码与历史实验分开。
3. **确定 runner 协议**：现有 do_train 路径成为 core；增加真实公共 feed 的 pipeline。
4. **完善构建与输入 provenance**：固定每个 build profile 的完整 runner lock，记录本地依赖闭包和内容身份。
5. **迁移报告和测试**：新 report 能从原始 attempts 重建；小型双版本实验检查全流程。
6. **准备最终 PR 证据**：对最新代码 revision 运行已声明的矩阵，发布可访问的复现材料。

首版完成条件：第三方能从 README 指定两个 revision、一个有身份的输入和一组 workers，得到可核对的模型、样本、失败记录和配对汇总；改变身份时不能误用旧结果。

tokbench 接入放在这个小仓库稳定之后。保留清晰的 job/result 协议和 corpus provenance，询问维护者希望接入的训练边界，再做必要适配。

## 18 文档交付边界

本文件是新增设计建议，先前的引擎设计及写作增补文档保持不变。上述命令、目录和 JSON 为建议接口，尚未在仓库实现。本次没有确认旧测量已被审计问题污染，也没有声明当前主分支能通过所有新设计的验证。
