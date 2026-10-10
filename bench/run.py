"""Runs an experiment: every variant x clip x repeat, safely and unattended.

    uv run python bench/run.py bench/configs/e1_vad_window.toml
    uv run python bench/run.py bench/configs/e1_vad_window.toml --limit 20   # pilot
    uv run python bench/run.py --report results/e1_vad_window                # rebuild the report

Safety, so a night run can't go wrong quietly:
  checkpoints  every clip-run is appended to runs.jsonl at once; rerunning resumes
  interleaving clips run in blocks, and the variants take turns on each block in a
               rotating order, so provider drift hits every variant equally
  budget       real usage (tokens, characters, audio seconds) is read from each session
               and priced; the run stops before a provider's cap is reached
  health       if more than 25% of the last 20 clip-runs failed, the run stops
"""

import argparse
import asyncio
import json
import logging
import statistics
import time
import tomllib
from collections import defaultdict
from dataclasses import replace
from pathlib import Path

from harness import Harness, ThreadInferenceExecutor, load_clips

from first_word.pipeline import PipelineConfig

RESULTS = Path(__file__).parent.parent / "results"
BLOCK_SIZE = 10
HEALTH_WINDOW, HEALTH_MAX_BAD = 20, 0.25

# list prices (USD), October 2026. Check them against the provider pages before a big run.
PRICES = {
    "stt_per_min": {"nova-3": 0.0048, "flux-general-en": 0.0065},
    "tts_per_1k_chars": {"aura-2": 0.030},
    "llm_per_m_tokens": {"gpt-4.1-mini": (0.40, 1.60), "gpt-4.1-nano": (0.10, 0.40)},
}
# Neither provider can bill beyond these: the Deepgram credit has no card attached and the
# OpenAI balance is prepaid with auto-recharge off. The caps only reserve some credit.
DEFAULT_BUDGET = {"deepgram": 150.0, "openai": 4.2}

# Session usage undercounts what providers bill (the pilot's dashboards showed ~4.3x for
# Deepgram, mostly TTS characters, and ~2x for OpenAI). Estimates are scaled by these
# factors so the budget caps track real spending, with a margin.
CALIBRATION = {"deepgram": 4.5, "openai": 2.2}


def load_experiment(path: Path) -> dict:
    exp = tomllib.loads(path.read_text())
    exp.setdefault("repeats", 3)
    exp.setdefault("offsets", [0.5, 1.5])
    exp.setdefault("holdout", False)
    exp["variants"] = {name: replace(PipelineConfig(), **overrides)
                       for name, overrides in exp["variants"].items()}
    return exp


def make_plan(exp: dict, clips: dict) -> list[dict]:
    """Ordered clip-runs: repeat -> block of clips -> variants in rotating order."""
    chosen = [c for c in clips.values()
              if c.set in exp["sets"] and (exp["holdout"] or not c.holdout)]
    names = list(exp["variants"])
    blocks = [chosen[i : i + BLOCK_SIZE] for i in range(0, len(chosen), BLOCK_SIZE)]
    plan = []
    for rep in range(exp["repeats"]):
        for b, block in enumerate(blocks):
            k = (rep * len(blocks) + b) % len(names)
            for variant in names[k:] + names[:k]:
                for clip in block:
                    offsets = exp["offsets"] if clip.set in ("S5", "S6") else [None]
                    for offset in offsets:
                        plan.append({"variant": variant, "clip": clip.id, "repeat": rep,
                                     "offset_s": offset, "block": f"{rep}-{b}-{variant}"})
    return plan


def key(row: dict) -> tuple:
    return (row["variant"], row["clip"], row["repeat"], row["offset_s"])


def cost(usage) -> dict:
    spent = {"deepgram": 0.0, "openai": 0.0}
    for u in usage.model_usage if usage else []:
        model = getattr(u, "model", "")
        if u.type == "stt_usage":
            rate = next((r for m, r in PRICES["stt_per_min"].items() if m in model), 0.0065)
            spent["deepgram"] += u.audio_duration / 60 * rate
        elif u.type == "tts_usage":
            spent["deepgram"] += u.characters_count / 1000 * PRICES["tts_per_1k_chars"]["aura-2"]
        elif u.type == "llm_usage":
            rin, rout = next((r for m, r in PRICES["llm_per_m_tokens"].items() if m in model), (0.40, 1.60))
            spent["openai"] += (u.input_tokens * rin + u.output_tokens * rout) / 1e6
    return {provider: usd * CALIBRATION[provider] for provider, usd in spent.items()}


def total_spent() -> dict:
    """Spending across ALL experiments, so the caps hold for a whole night of runs."""
    spent = defaultdict(float)
    for usage_file in RESULTS.glob("*/usage.jsonl"):
        for line in usage_file.open():
            for provider, usd in json.loads(line)["usd"].items():
                spent[provider] += usd
    return spent


def is_bad(row: dict) -> bool:
    if row.get("error"):
        return True
    if row["set"] in ("S5", "S6"):
        return not row.get("valid")
    return row["set"] in ("S1", "S3") and not row.get("replied")


async def run(config_path: Path, limit: int | None, budget: dict) -> None:
    exp = load_experiment(config_path)
    clips = load_clips(exp["dataset"])
    setup = load_clips("synthetic")["setup_01"]
    out = RESULTS / exp["name"]
    out.mkdir(parents=True, exist_ok=True)
    (out / "experiment.toml").write_text(config_path.read_text())
    runs_path, usage_path = out / "runs.jsonl", out / "usage.jsonl"

    done = {key(json.loads(line)) for line in runs_path.open()} if runs_path.exists() else set()
    plan = [p for p in make_plan(exp, clips) if key(p) not in done]
    if limit:
        plan = plan[:limit]
    log(out, f"{exp['name']}: {len(done)} done, {len(plan)} to run, "
             f"spent so far (all experiments) {dict(total_spent()) or 0}")

    executor = ThreadInferenceExecutor()
    await executor.preload()
    recent: list[bool] = []
    blocks = defaultdict(list)
    for p in plan:
        blocks[p["block"]].append(p)

    stop = ""
    for block_id, items in blocks.items():
        variant = items[0]["variant"]
        cfg = exp["variants"][variant]
        harness = Harness(cfg, setup, executor)
        try:
            async with harness:
                for p in items:
                    row = await harness.run(clips[p["clip"]], offset_s=p["offset_s"] or 0.5)
                    row.update({"variant": variant, "repeat": p["repeat"], "offset_s": p["offset_s"],
                                "ts": round(time.time(), 3), **{f"cfg_{k}": v for k, v in cfg.as_dict().items()}})
                    with runs_path.open("a") as f:
                        f.write(json.dumps(row) + "\n")
                    recent = (recent + [is_bad(row)])[-HEALTH_WINDOW:]
                    log(out, f"[{block_id}] {p['clip']:<14} {summary(row)}")
                    if len(recent) == HEALTH_WINDOW and sum(recent) / HEALTH_WINDOW > HEALTH_MAX_BAD:
                        stop = f"{sum(recent)}/{HEALTH_WINDOW} recent clip-runs failed"
                        break
        except Exception as e:
            log(out, f"block {block_id} crashed: {type(e).__name__}: {e}")
        with usage_path.open("a") as f:
            f.write(json.dumps({"block": block_id, "usd": cost(harness.usage)}) + "\n")
        spent = total_spent()
        over = [p for p, cap in budget.items() if spent[p] >= cap * 0.9]
        if over:
            stop = f"budget nearly used for {over}"
        if stop:
            log(out, f"STOP: {stop}")
            break

    finish(out)


def summary(row: dict) -> str:
    if row.get("error"):
        return f"ERROR {row['error'][:80]}"
    if row["set"] in ("S5", "S6"):
        return (f"offset {row['offset_s']}s stopped={row.get('stopped')} "
                f"after={row.get('stop_after_ms')}ms" if row.get("valid") else f"invalid: {row.get('note')}")
    return (f"cut_off={row.get('cut_off')} eot={row.get('end_of_turn_delay')} "
            f"e2e={row.get('e2e_latency')} '{row.get('user_text', '')[:40]}'")


def log(out: Path, msg: str) -> None:
    line = f"{time.strftime('%H:%M:%S')} {msg}"
    print(line, flush=True)
    with (out / "runner.log").open("a") as f:
        f.write(line + "\n")


def finish(out: Path) -> None:
    write_report(out)
    log(out, f"done. spent (all experiments) {dict(total_spent())}. report: {out / 'report.md'}")


def pct(values: list[float], q: float) -> str:
    if not values:
        return "-"
    values = sorted(values)
    return str(round(values[min(len(values) - 1, int(q * len(values)))]))


def write_report(out: Path) -> None:
    """A first look for the morning. The real analysis lives in analyze.py."""
    rows = [json.loads(line) for line in (out / "runs.jsonl").open()] if (out / "runs.jsonl").exists() else []
    by_variant = defaultdict(list)
    for r in rows:
        by_variant[r["variant"]].append(r)

    lines = [f"# {out.name}", "", f"{len(rows)} clip-runs, "
             f"{sum(bool(r.get('error')) for r in rows)} errors", ""]
    lines += ["| variant | S1+S3 e2e p50 / p95 | S1+S3 end-of-turn p50 | S2 cut-off rate | "
              "S4 end-of-turn p50 | S5 stopped | S5 stop p50 | S6 false stops |",
              "|---|---|---|---|---|---|---|---|"]
    for variant, rs in by_variant.items():
        ok = [r for r in rs if not r.get("error")]
        lat = [r for r in ok if r["set"] in ("S1", "S3") and r.get("e2e_latency") != ""]
        e2e = [r["e2e_latency"] for r in lat if isinstance(r.get("e2e_latency"), int)]
        eot = [r["end_of_turn_delay"] for r in lat if isinstance(r.get("end_of_turn_delay"), int)]
        s2 = [r for r in ok if r["set"] == "S2"]
        s4 = [r["end_of_turn_delay"] for r in ok if r["set"] == "S4" and isinstance(r.get("end_of_turn_delay"), int)]
        s5 = [r for r in ok if r["set"] == "S5" and r.get("valid")]
        s6 = [r for r in ok if r["set"] == "S6" and r.get("valid")]
        stops = [r["stop_after_ms"] for r in s5 if isinstance(r.get("stop_after_ms"), int)]
        rate = lambda xs, f: f"{sum(map(f, xs))}/{len(xs)}" if xs else "-"
        lines.append(f"| {variant} | {pct(e2e, .5)} / {pct(e2e, .95)} | {pct(eot, .5)} | "
                     f"{rate(s2, lambda r: r.get('cut_off'))} | {pct(s4, .5)} | "
                     f"{rate(s5, lambda r: r.get('stopped'))} | {pct(stops, .5)} | "
                     f"{rate(s6, lambda r: r.get('stopped'))} |")

    s2_rows = [r for r in rows if r["set"] == "S2" and not r.get("error") and r.get("pause_ms")]
    if s2_rows:
        pauses = sorted({int(r["pause_ms"]) for r in s2_rows})
        lines += ["", "## S2 cut-off rate by pause length", "",
                  "| variant | " + " | ".join(f"{p} ms" for p in pauses) + " |",
                  "|---|" + "---|" * len(pauses)]
        for variant in by_variant:
            cells = []
            for p in pauses:
                xs = [r for r in s2_rows if r["variant"] == variant and int(r["pause_ms"]) == p]
                cells.append(f"{sum(bool(r.get('cut_off')) for r in xs)}/{len(xs)}" if xs else "-")
            lines.append(f"| {variant} | " + " | ".join(cells) + " |")
    (out / "report.md").write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    parser = argparse.ArgumentParser()
    parser.add_argument("config", nargs="?", type=Path)
    parser.add_argument("--limit", type=int, help="run at most N clip-runs (pilot)")
    parser.add_argument("--report", type=Path, help="only rebuild report.md for a results folder")
    parser.add_argument("--budget-openai", type=float, default=DEFAULT_BUDGET["openai"])
    parser.add_argument("--budget-deepgram", type=float, default=DEFAULT_BUDGET["deepgram"])
    args = parser.parse_args()
    if args.report:
        write_report(args.report)
    else:
        asyncio.run(run(args.config, args.limit,
                        {"openai": args.budget_openai, "deepgram": args.budget_deepgram}))
