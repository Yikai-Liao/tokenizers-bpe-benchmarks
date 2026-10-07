"""Create small deterministic Docker fixtures; these are workflow checks, not performance evidence."""

import argparse
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--workers", nargs="+", type=int, default=[1, 4])
    args = parser.parse_args()
    out = args.out.resolve()
    for name in ("data", "config", "results"):
        (out / name).mkdir(parents=True, exist_ok=True)
    for name, line in dict(en="alpha beta gamma delta epsilon\n",
                           zh="中文 测试 训练 分词 内存 增长 速度 对比\n",
                           code="def tokenize(text):\n    return text.split()  # tokens\n").items():
        data = line.encode()
        count = (4 << 20) // len(data) + 1
        (out / "data" / f"{name}.txt").write_bytes(data * count)
    workers = str(args.workers)
    text = f'''schema_version = 1
name = "docker-smoke"
[execution]
workers = {workers}
repetitions = 3
warmups = 0
min_available_gib = 0.1
max_process_rss_gib = 1
timeout_seconds = 180
plots = true
[small]
enabled = true
size_mib = 1
[trainer]
vocab_size = 300
min_frequency = 2
[growth]
workers = {max(args.workers)}
repetitions = 1
start_mib = 1
max_mib = 4
rss_target_gib = 0.5
[[cases]]
name = "en-bytelevel"
path = "/data/en.txt"
size_mib = 1
pretokenizer = "bytelevel_regex"
[[cases]]
name = "zh-whitespace"
path = "/data/zh.txt"
size_mib = 1
pretokenizer = "whitespace"
growth = true
[[cases]]
name = "zh-bytelevel"
path = "/data/zh.txt"
size_mib = 1
pretokenizer = "bytelevel_regex"
growth = true
[[cases]]
name = "code-bytelevel"
path = "/data/code.txt"
size_mib = 1
pretokenizer = "bytelevel_regex"
'''
    (out / "config" / "suite.toml").write_text(text)


if __name__ == "__main__":
    main()
