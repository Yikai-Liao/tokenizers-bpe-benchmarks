"""Four-panel throughput and memory figures for measured or synthetic data.

The two throughput figures compare Feed + Train and Train-only core scaling.
The memory figure compares RSS against distinct Feed strings across corpus types.
These are quantitative grids; corpus panels stratify the same comparison. Keep
secondary metrics in the CSV so that each figure retains one question.
"""

import importlib.util
import hashlib
import json
import math
from pathlib import Path


METHODS = {
    "baseline": ("HF main", "#57606A", "o"),
    "hf-pr2348": ("HF PR #2348", "#0072B2", "s"),
    "fork-main": ("Fork main", "#D55E00", "^"),
    "fork-yttm": ("Fork YTTM", "#009E73", "D"),
}
CASES = {
    "code-bytelevel": "Code / ByteLevel",
    "english-bytelevel": "English / ByteLevel",
    "chinese-bytelevel": "Chinese / ByteLevel",
    "chinese-whitespace": "Chinese / Whitespace",
}


def _alignment(fig, target):
    helper = Path(__file__).resolve().parents[1] / ".agents/skills/nature-figure/scripts/audit_panel_alignment.py"
    if not helper.exists():
        raise RuntimeError(f"figure alignment helper is missing: {helper}")
    spec = importlib.util.spec_from_file_location("panel_alignment", helper)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.require_matplotlib_panel_alignment(
        fig, json_out=str(target) + ".alignment.json", strict=True,
        require_panel_labels=True,
    )


def _audit_pdf(target):
    """Preserve rendered QA and block delivery on a geometry or glyph failure."""
    import subprocess
    import sys
    helpers = Path(__file__).resolve().parents[1] / ".agents/skills/nature-figure/scripts"
    with Path(str(target) + ".text-audit.json").open("w") as stream:
        subprocess.run([sys.executable, str(helpers / "audit_pdf_text.py"),
                        str(target) + ".pdf", "--json"], check=True, stdout=stream)
    subprocess.run([sys.executable, str(helpers / "audit_figure_collisions.py"),
                    str(target) + ".pdf", "--json-out", str(target) + ".collision-audit.json"],
                   check=True, stdout=subprocess.DEVNULL)


def render(folder, time_rows, growth_rows, *, cases=None, methods=None, mock=False,
           input_mib=512, vocabulary=100000, repetitions=3, cores=int(8),
           soft_target_gib=16, feed_axis=True, baseline_label="HF main", filename_prefix="",
           timing="pipeline", memory_reference_rows=None):
    """Render actual points only; min/max whiskers describe observed repetitions.

    ``time_rows`` contain case, arm, workers and pipeline/train_samples_seconds.
    ``timing`` selects Feed + Train or Train-only samples and paired speedups.
    ``growth_rows`` contain case, arm, input_bytes, peak_rss_bytes and optional
    feed_unique_utf8_bytes. An incomplete curve ends at its last observed point.
    The caller must select one shared Feed or raw-input axis for all growth rows.
    Optional memory references use RSS medians from the throughput matrix at the
    growth core count; labels compare those medians at the same input size.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D
    from matplotlib import font_manager, ft2font
    from matplotlib.ticker import FixedLocator, FuncFormatter, MaxNLocator

    cases = cases or CASES
    methods = methods or METHODS
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    style = dict(METHODS)
    style.update(methods)
    plt.rcParams.update({
        "font.family": "sans-serif", "font.sans-serif": ["Liberation Sans"], "font.size": 8,
        "axes.labelsize": 8, "axes.titlesize": 9, "axes.linewidth": 0.7,
        "axes.spines.top": False, "axes.spines.right": False,
        "xtick.labelsize": 7, "ytick.labelsize": 7,
        "legend.fontsize": 8, "legend.frameon": False,
        "svg.fonttype": "none", "pdf.fonttype": 42,
        "savefig.facecolor": "white",
    })
    # Require the exact packaged Arial-compatible files rather than silently
    # falling back to a host-dependent font family or distribution version.
    font_dir = Path(__file__).resolve().parents[1] / "assets/fonts"
    font_manager.fontManager.ttflist = [font for font in font_manager.fontManager.ttflist
                                       if font.name != "Liberation Sans"]
    fonts = []
    for weight, filename in (("normal", "LiberationSans-Regular.ttf"), ("bold", "LiberationSans-Bold.ttf")):
        path = font_dir / filename
        font_manager.fontManager.addfont(str(path))
        resolved = Path(font_manager.findfont(font_manager.FontProperties(family="Liberation Sans", weight=weight),
                                             fallback_to_default=False))
        if resolved.resolve() != path.resolve():
            raise RuntimeError(f"unexpected plot font for {weight}: {resolved}")
        if not ft2font.FT2Font(str(resolved)).get_char_index(ord("×")):
            raise RuntimeError("plot font is missing the multiplication glyph")
        fonts.append(dict(weight=weight, filename=filename,
                          sha256=hashlib.sha256(resolved.read_bytes()).hexdigest()))
    (folder / "fonts.json").write_text(json.dumps(dict(family="Liberation Sans", fonts=fonts), indent=2) + "\n")

    def canvas(title, subtitle, footer):
        columns = min(2, len(cases))
        rows = math.ceil(len(cases) / columns)
        fig, axes = plt.subplots(rows, columns, figsize=(7.2, 1.8 + rows * 2.1), squeeze=False)
        fig.subplots_adjust(left=0.11, right=0.89, bottom=0.18, top=0.76,
                            wspace=0.60, hspace=0.50)
        fig.text(0.11, 0.965, title, fontsize=12, fontweight="bold", va="top")
        fig.text(0.11, 0.92, subtitle, fontsize=8, color="#57606A", va="top")
        if mock:
            fig.text(0.11, 0.878, "SYNTHETIC DATA  /  STYLE PREVIEW ONLY",
                     fontsize=7, color="#8C4D04", va="top")
        handles = [Line2D([], [], color=color, marker=marker, markersize=4,
                          linewidth=1.3, label=name)
                   for name, color, marker in methods.values()]
        fig.legend(handles=handles, loc="upper left", bbox_to_anchor=(0.098, 0.855),
                   ncol=4, columnspacing=1.4, handlelength=2.0, handletextpad=0.6)
        fig.text(0.11, 0.044, footer, fontsize=7, color="#57606A", va="bottom")
        for index, (ax, (case, title)) in enumerate(zip(axes.flat, cases.items())):
            ax.text(-0.18, 1.09, chr(97 + index), transform=ax.transAxes,
                    fontsize=10, fontweight="bold", va="bottom")
            ax.set_title(title, loc="left", pad=9)
            ax.grid(axis="y", color="#DDE1E5", linewidth=0.5)
            ax.set_axisbelow(True)
        for ax in list(axes.flat)[len(cases):]:
            ax.set_visible(False)
        return fig, axes

    def save(fig, name):
        target = folder / name
        fig.canvas.draw()
        _alignment(fig, target)
        fig.savefig(str(target) + ".png", dpi=600)
        fig.savefig(str(target) + ".svg")
        fig.savefig(str(target) + ".pdf")
        _audit_pdf(target)
        plt.close(fig)

    def right_labels(ax, endpoints, high):
        ordered = sorted(endpoints)
        gap = high * min(0.10, 0.80 / max(1, len(ordered)))
        positions = []
        for value, *_ in ordered:
            positions.append(max(value, positions[-1] + gap if positions else high * 0.06))
        for index in range(len(positions) - 1, -1, -1):
            ceiling = high * 0.94 if index == len(positions) - 1 else positions[index + 1] - gap
            positions[index] = min(positions[index], ceiling)
        for (value, color, label, x), label_y in zip(ordered, positions):
            ax.annotate(label, xy=(x, value), xytext=(1.04, label_y / high),
                        textcoords="axes fraction", annotation_clip=False,
                        color=color, fontsize=8, va="center", fontweight="bold",
                        arrowprops=dict(arrowstyle="-", color=color, lw=0.5))

    if timing not in ("pipeline", "train"):
        raise ValueError("timing must be pipeline or train")
    sample_field = f"{timing}_samples_seconds"
    ratio_field = "paired_speedup_over_baseline" if timing == "pipeline" else "paired_train_speedup_over_baseline"
    stage = "Feed + Train" if timing == "pipeline" else "Train only"
    if any(r[sample_field] for r in time_rows):
        title = f"BPE throughput: {stage}"
        footer = ("Points: median of three runs; whiskers: observed min-max. Higher throughput is better."
                  if repetitions == 3 else
                  f"Points: median of {repetitions} runs; whiskers: observed min-max. Higher throughput is better.")
        footer += f"\nEndpoint labels: speedup vs {baseline_label} at the same core count. Y limits vary by panel."
        sizes = {r.get("input_bytes", input_mib * 2**20) >> 20 for r in time_rows}
        input_label = f"{input_mib:,} MiB per corpus" if len(sizes) == 1 else "Input size varies by corpus"
        fig, axes = canvas(title, f"{input_label}  |  Target vocabulary size {vocabulary:,}", footer)
        max_cores = max(r["workers"] for r in time_rows)
        xleft = 0
        xright = max_cores + 0.6

        for ax, case in zip(axes.flat, cases):
            observed = [r.get("input_bytes", input_mib * 2**20) / 2**20 / value
                        for r in time_rows if r["case"] == case
                        for value in r[sample_field] if value > 0]
            high = max(observed, default=1) * 1.18
            endpoints = []
            for arm, (name, color, marker) in methods.items():
                selected = sorted((r for r in time_rows if r["case"] == case and r["arm"] == arm
                                   and r[sample_field]), key=lambda r: r["workers"])
                if not selected:
                    continue
                import statistics
                xs = [r["workers"] for r in selected]
                volumes = [r.get("input_bytes", input_mib * 2**20) / 2**20 for r in selected]
                ys = [volume / statistics.median(r[sample_field])
                      for volume, r in zip(volumes, selected)]
                errors = [[y - volume / max(r[sample_field]) for y, volume, r in zip(ys, volumes, selected)],
                          [volume / min(r[sample_field]) - y for y, volume, r in zip(ys, volumes, selected)]]
                ax.errorbar(xs, ys, yerr=errors, color=color, marker=marker,
                            markersize=4, linewidth=1.3, elinewidth=0.7, capsize=2)
                ratio = selected[-1].get(ratio_field)
                if ratio is not None:
                    endpoints.append((ys[-1], color, f"{ratio:.1f}×", xs[-1]))
            right_labels(ax, endpoints, high)
            ax.set_xlim(xleft, xright)
            ax.set_ylim(0, high)
            ax.yaxis.set_major_locator(MaxNLocator(nbins=5))
            ax.set_xticks(sorted({0} | {r["workers"] for r in time_rows}))
            ax.set_xlabel("Cores")
            ax.set_ylabel("Throughput (MiB/s)")
        save(fig, filename_prefix + "core-scaling")

    if growth_rows:
        axis_field = "feed_unique_utf8_bytes" if feed_axis else "input_bytes"
        observed = [r[axis_field] / 2**20 for r in growth_rows if r.get(axis_field, 0) > 0]
        if not observed:
            raise ValueError("growth figure requires measured positive x values")
        footer = ("Fresh growth points: single runs. Reused throughput points: medians."
                  if memory_reference_rows else "One run per size.")
        footer += " Target line shown when in range."
        footer += ("\nFeed size sums UTF-8 bytes of distinct pre-tokenized strings; excludes their frequencies."
                   if feed_axis else "\nNested raw-text prefixes.")
        footer += "\nLinear axes; X and Y limits vary by panel. Curves stop at the last completed size."
        if memory_reference_rows:
            footer += f"\nVertical marker: reused throughput RSS medians. Labels: peak RSS as % of {baseline_label} at that input."
        fig, axes = canvas("BPE memory growth", f"{cores} cores  |  Target vocabulary size {vocabulary:,}  |  Soft target {soft_target_gib:g} GiB", footer)
        for ax, case in zip(axes.flat, cases):
            observed = [r[axis_field] / 2**20 for r in growth_rows
                        if r["case"] == case and r.get(axis_field, 0) > 0]
            xhigh = max(observed, default=1) * 1.08
            peaks = [r["peak_rss_bytes"] / 2**30 for r in growth_rows
                     if r["case"] == case and r.get(axis_field, 0) > 0]
            upper = max(peaks, default=1) * 1.08
            yticks = list(MaxNLocator(nbins=5, steps=[1, 2, 2.5, 5, 10]).tick_values(0, upper))
            ymax = yticks[-1]
            if 0 < soft_target_gib <= ymax:
                step = yticks[1] - yticks[0]
                yticks = sorted([tick for tick in yticks if abs(tick - soft_target_gib) > step * 0.45]
                                + [soft_target_gib])
                ax.axhline(soft_target_gib, color="#8C4D04", linewidth=1.4, linestyle=(0, (4, 3)))
            for arm, (name, color, marker) in methods.items():
                selected = sorted((r for r in growth_rows if r["case"] == case and r["arm"] == arm
                                   and r.get(axis_field, 0) > 0), key=lambda r: r["input_bytes"])
                ax.plot([r[axis_field] / 2**20 for r in selected],
                        [r["peak_rss_bytes"] / 2**30 for r in selected],
                        color=color, marker=marker, markersize=4, linewidth=1.3)
            references = [r for r in memory_reference_rows or [] if r["case"] == case]
            baseline = next((r for r in references if r["arm"] == "baseline"), None)
            if baseline and baseline["peak_rss_bytes"] > 0:
                reference_x = baseline[axis_field] / 2**20
                ax.vlines(reference_x, 0, ymax * 0.86, color="#8A929B", linewidth=0.8,
                          linestyles=(0, (2, 3)))
                ax.text(reference_x + xhigh * 0.02, ymax * 0.94,
                        f"{baseline['input_bytes'] / 2**20:.3g} MiB raw text", fontsize=7,
                        color="#57606A", va="center")
                annotations = []
                for row in references:
                    if row["arm"] == "baseline":
                        continue
                    color = methods[row["arm"]][1]
                    percentage = 100 * row["peak_rss_bytes"] / baseline["peak_rss_bytes"]
                    label = f"{percentage:.0f}%"
                    annotations.append((row["peak_rss_bytes"] / 2**30, color, label,
                                        row[axis_field] / 2**20))
                right_labels(ax, annotations, ymax)
            ax.set_xlim(0, xhigh)
            ax.set_ylim(0, ymax)
            ax.yaxis.set_major_locator(FixedLocator(yticks))
            ax.xaxis.set_major_locator(MaxNLocator(nbins=5))
            ax.xaxis.set_major_formatter(FuncFormatter(lambda value, _: f"{value:g}"))
            ax.set_xlabel("Distinct Feed strings (MiB)" if feed_axis else "Input text (MiB)")
            ax.set_ylabel("Peak RSS (GiB)")
            for tick, value in zip(ax.get_yticklabels(), ax.get_yticks()):
                if math.isclose(value, soft_target_gib):
                    tick.set_fontweight("bold")
                    tick.set_fontsize(10)
                    tick.set_color("#8C4D04")
        save(fig, "memory-growth")
