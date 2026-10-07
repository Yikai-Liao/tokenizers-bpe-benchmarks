"""Physical CPU allocation and explicit Linux NUMA policy."""

import os
import subprocess
from pathlib import Path


def topology():
    text = subprocess.check_output(["lscpu", "-p=CPU,CORE,SOCKET,NODE"], text=True)
    return [tuple(map(int, line.split(","))) for line in text.splitlines()
            if line and not line.startswith("#")]


def select_cpus(count, cpu_set=None, node=None):
    allowed = os.sched_getaffinity(0)
    rows = topology()
    if cpu_set is not None:
        if (not cpu_set or any(type(c) is not int for c in cpu_set)
                or len(set(cpu_set)) != len(cpu_set) or not set(cpu_set) <= allowed):
            raise ValueError("CPU set must be unique and within available affinity")
        if len(cpu_set) < count:
            raise ValueError("workers must fit the CPU set")
        chosen = [r for c in cpu_set for r in rows if r[0] == c]
        if len({(r[1], r[2]) for r in chosen}) != len(cpu_set):
            raise ValueError("suite CPU set must use distinct physical cores")
        if node is not None and any(r[3] != node for r in chosen):
            raise ValueError("CPU set does not belong to the selected NUMA node")
        return list(cpu_set)
    # Prefer one socket/node. Fail rather than silently spread a bind experiment.
    nodes = [node] if node is not None else sorted({r[3] for r in rows})
    for candidate in nodes:
        seen, cpus = set(), []
        for cpu, core, socket, numa in rows:
            if cpu in allowed and numa == candidate and (core, socket) not in seen:
                seen.add((core, socket))
                cpus.append(cpu)
        if len(cpus) >= count:
            return cpus[:count]
    if node is not None:
        raise ValueError(f"NUMA node {node} has fewer than {count} allowed physical cores")
    seen, cpus = set(), []
    for cpu, core, socket, _ in rows:
        if cpu in allowed and (core, socket) not in seen:
            seen.add((core, socket))
            cpus.append(cpu)
    if len(cpus) < count:
        raise ValueError(f"need {count} distinct allowed physical cores, found {len(cpus)}")
    return cpus[:count]


def validate_numa(value, cpus):
    if set(value) - {"policy", "nodes"}:
        raise ValueError("unknown NUMA option")
    policy = value.get("policy", "default")
    nodes = value.get("nodes", [])
    if policy not in ("default", "bind", "interleave"):
        raise ValueError("NUMA policy must be default, bind or interleave")
    if policy == "default":
        if nodes:
            raise ValueError("default NUMA policy cannot specify nodes")
        return dict(policy=policy, nodes=[])
    if not nodes or any(type(n) is not int or n < 0 for n in nodes) or len(set(nodes)) != len(nodes):
        raise ValueError("NUMA nodes must be nonempty, unique nonnegative integers")
    rows = topology()
    if not set(nodes) <= {r[3] for r in rows}:
        raise ValueError("unknown NUMA node")
    if policy == "bind" and any(r[3] not in nodes for r in rows if r[0] in cpus):
        raise ValueError("bind CPU set must belong to selected NUMA nodes")
    # Probe the syscall before starting an experiment; Docker seccomp may deny it.
    subprocess.run(numa_prefix(dict(policy=policy, nodes=nodes)) + ["true"], check=True,
                   stdout=subprocess.DEVNULL)
    return dict(policy=policy, nodes=nodes)


def numa_prefix(value):
    if value.get("policy", "default") == "default":
        return []
    flag = "--membind" if value["policy"] == "bind" else "--interleave"
    return ["numactl", f"{flag}={','.join(map(str, value['nodes']))}"]


def cgroup_memory(root=Path("/sys/fs/cgroup")):
    """Read the visible v2 hierarchy, including parent limits when available."""
    group = next((line.split(":", 2)[2] for line in Path("/proc/self/cgroup").read_text().splitlines()
                  if line.startswith("0::")), "/")
    folder = root / group.lstrip("/")
    if not (folder / "memory.current").exists():
        folder = root  # cgroup namespace roots, as used by Docker
    result = []
    while folder == root or root in folder.parents:
        try:
            limit = (folder / "memory.max").read_text().strip()
            result.append(dict(path=str(folder), limit=None if limit == "max" else int(limit),
                               current=int((folder / "memory.current").read_text())))
        except FileNotFoundError:
            pass
        if folder == root:
            break
        folder = folder.parent
    return result
