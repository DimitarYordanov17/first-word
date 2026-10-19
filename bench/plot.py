"""Draws results/findings.png from the runs.jsonl files of the full run.

    uv run python bench/plot.py
"""

import json
import statistics
from collections import defaultdict
from pathlib import Path

import matplotlib.pyplot as plt

RESULTS = Path(__file__).parent.parent / "results"
SYNTHETIC, NATURAL = "#8b5cf6", "#f59e0b"
LATENCY_EXPERIMENTS = ["e1_vad_window", "e2_turn_detector", "e3_endpointing", "e4_preemptive",
                       "e5_preemptive_tts", "e7_flux", "e8_llm", "e9_prompt"]


def load(name):
    by_variant = defaultdict(list)
    for line in open(RESULTS / name / "runs.jsonl"):
        row = json.loads(line)
        by_variant[row["variant"]].append(row)
    return by_variant


def median(rows, key, sets=("S1", "S3")):
    values = [r[key] for r in rows if r["set"] in sets and isinstance(r.get(key), (int, float))]
    return statistics.median(values)


def cut_off_rate(rows):
    pauses = [r for r in rows if r["set"] == "S2"]
    return sum(r["cut_off"] for r in pauses), len(pauses)


def stop_rate(rows, clip_set):
    runs = [r for r in rows if r["set"] == clip_set and r.get("valid")]
    return 100 * sum(r["stopped"] for r in runs) / len(runs)


def both(name):
    return [(load(name), SYNTHETIC), (load("natural_" + name), NATURAL)]


def latency_change(ax):
    levers = [
        ("Preemptive generation off", "e4_preemptive", "preemptive_off"),
        ("Flux instead of nova-3", "e7_flux", "flux"),
        ("Audio turn detector", "e2_turn_detector", "audio"),
        ("VAD silence 0.3 s", "e1_vad_window", "vad_0_3"),
        ("Dynamic endpointing", "e3_endpointing", "dynamic"),
        ("Preemptive TTS on", "e5_preemptive_tts", "preemptive_tts_on"),
        ("Short first sentence prompt", "e9_prompt", "short_first"),
        ("gpt-4.1-nano instead of mini", "e8_llm", "gpt_4_1_nano"),
    ]
    for y, (label, name, variant) in enumerate(reversed(levers)):
        for offset, (runs, color) in zip((0.18, -0.18), both(name)):
            change = median(runs[variant], "e2e_latency") - median(runs["baseline"], "e2e_latency")
            ax.barh(y + offset, change, height=0.34, color=color)
            ax.text(change + (8 if change >= 0 else -8), y + offset, f"{change:+.0f}", va="center",
                    ha="left" if change >= 0 else "right", fontsize=9, color="#6b7280")
    ax.set_yticks(range(len(levers)), [label for label, *_ in reversed(levers)])
    ax.axvline(0, color="black", lw=1)
    ax.set_xlim(-260, 400)
    ax.set_xlabel("change in median e2e latency vs baseline (ms), right is slower")
    ax.set_title("Only preemptive generation clearly matters", loc="left", weight="bold")


def cut_offs(ax):
    detectors = [("Text model\n(baseline)", "baseline"), ("Audio model", "audio"),
                 ("Audio model,\nits own delays", "audio_own_defaults"), ("VAD only", "none")]
    for i, (_, variant) in enumerate(detectors):
        for offset, (runs, color) in zip((-0.2, 0.2), both("e2_turn_detector")):
            cut, total = cut_off_rate(runs[variant])
            ax.bar(i + offset, 100 * cut / total, width=0.38, color=color)
            ax.text(i + offset, 100 * cut / total + 2, f"{cut}/{total}", ha="center", fontsize=9, color="#6b7280")
    ax.set_xticks(range(len(detectors)), [label for label, _ in detectors])
    ax.set_ylim(0, 110)
    ax.set_ylabel("% of mid-sentence pauses cut off")
    ax.set_title("Every turn detector cuts off real pauses far more often", loc="left", weight="bold")


def stages(ax):
    keys = [("Speech-to-text", "transcription_delay"), ("End-of-turn wait", "end_of_turn_delay"),
            ("LLM first token", "llm_ttft"), ("TTS first byte", "tts_ttfb")]
    pools = [(sum((load(prefix + n)["baseline"] for n in LATENCY_EXPERIMENTS), []), color)
             for prefix, color in (("", SYNTHETIC), ("natural_", NATURAL))]
    for i, (_, key) in enumerate(keys):
        for offset, (rows, color) in zip((-0.2, 0.2), pools):
            value = median(rows, key)
            ax.bar(i + offset, value, width=0.38, color=color)
            ax.text(i + offset, value + 12, f"{value:.0f}", ha="center", fontsize=9, color="#6b7280")
    ax.set_xticks(range(len(keys)), [label for label, _ in keys])
    ax.set_ylim(0, 800)
    ax.set_ylabel("median ms, baseline")
    total = median(pools[0][0], "e2e_latency")
    ax.set_title(f"Where the time goes (stages overlap, e2e ≈ {total:.0f} ms)", loc="left", weight="bold")


def interruptions(ax):
    groups = [("Real interruption\n(should stop)", "S5"), ("Backchannel \"mm-hm\"\n(should keep talking)", "S6")]
    modes = [("adaptive", "baseline"), ("vad", "vad_mode")]
    ticks, labels = [], []
    for g, (_, clip_set) in enumerate(groups):
        for m, (mode, variant) in enumerate(modes):
            x = g * 2.6 + m
            for offset, (runs, color) in zip((-0.2, 0.2), both("e6_interruption")):
                rate = stop_rate(runs[variant], clip_set)
                ax.bar(x + offset, rate, width=0.38, color=color)
                ax.text(x + offset, rate + 2, f"{rate:.0f}%", ha="center", fontsize=9, color="#6b7280")
            ticks.append(x)
            labels.append(mode)
        ax.text(g * 2.6 + 0.5, -24, groups[g][0], ha="center", weight="bold")
    ax.set_xticks(ticks, labels)
    ax.set_ylim(0, 110)
    ax.set_ylabel("% of runs where the agent stopped talking")
    ax.set_title("VAD interruption mode stops for backchannels", loc="left", weight="bold")


plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False})
fig, axes = plt.subplots(2, 2, figsize=(16, 11))
latency_change(axes[0][0])
cut_offs(axes[0][1])
stages(axes[1][0])
interruptions(axes[1][1])
for ax in axes.flat:
    ax.grid(axis="x" if ax is axes[0][0] else "y", color="#e5e7eb")
    ax.set_axisbelow(True)
fig.legend(handles=[plt.Rectangle((0, 0), 1, 1, color=SYNTHETIC), plt.Rectangle((0, 0), 1, 1, color=NATURAL)],
           labels=["synthetic caller (TTS)", "real caller (my recordings)"], loc="upper center", ncol=2, frameon=False)
fig.tight_layout(rect=(0, 0.02, 1, 0.96), h_pad=4, w_pad=3)
fig.savefig(RESULTS / "findings.png", dpi=130)
print(RESULTS / "findings.png")
