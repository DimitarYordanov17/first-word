"""Generate the synthetic eval set from scripts.csv.

Each row is spoken by a TTS "caller" voice and saved as a 16 kHz mono wav,
matching the natural recordings. S2 rows contain a "|" where an exact pause
is spliced in, once per length in PAUSES_MS. S4 rows get a long trailing silence.

Writes audio/<id>.wav plus manifest.csv (one row per clip, with its pause length).

    uv run python bench/generate_synthetic.py          # generate missing clips
    uv run python bench/generate_synthetic.py --force  # regenerate everything
"""

import argparse
import asyncio
import csv
import wave
from pathlib import Path

import numpy as np
from dotenv import load_dotenv
from livekit.agents.utils import http_context
from livekit.plugins import deepgram

load_dotenv(".env.local")

SET_DIR = Path(__file__).parent / "sets" / "synthetic"
SCRIPTS = SET_DIR / "scripts.csv"
MANIFEST = SET_DIR / "manifest.csv"
AUDIO_DIR = SET_DIR / "audio"

CALLER_VOICE = "aura-2-apollo-en"  # different from the agent's voice
SAMPLE_RATE = 16000
PAUSES_MS = [200, 300, 400, 500, 600, 800, 1000]
LEAD_S, TRAIL_S, S4_TRAIL_S = 0.5, 0.6, 3.0


async def speak(tts: deepgram.TTS, text: str) -> np.ndarray:
    frames = [ev.frame async for ev in tts.synthesize(text)]
    audio = np.concatenate([np.frombuffer(f.data, dtype=np.int16) for f in frames])
    return trim(audio)


def trim(audio: np.ndarray, frame: int = 160) -> np.ndarray:
    """Cut the TTS's own leading/trailing silence so spliced pauses are exact."""
    levels = [np.abs(audio[i : i + frame]).mean() for i in range(0, len(audio), frame)]
    threshold = max(levels) * 0.02
    voiced = [i for i, v in enumerate(levels) if v > threshold]
    return audio[voiced[0] * frame : (voiced[-1] + 1) * frame]


def measured_gap_ms(path: Path, frame: int = 160) -> int:
    """Longest silence inside the speech: the pause the agent will actually hear."""
    with wave.open(str(path)) as w:
        audio = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
    voiced = np.array([np.abs(audio[i : i + frame]).mean() for i in range(0, len(audio), frame)])
    voiced = voiced > voiced.max() * 0.02
    inside = voiced[np.argmax(voiced) : len(voiced) - np.argmax(voiced[::-1])]
    longest = run = 0
    for v in inside:
        run = 0 if v else run + 1
        longest = max(longest, run)
    return longest * frame * 1000 // SAMPLE_RATE


def silence(seconds: float) -> np.ndarray:
    return np.zeros(int(seconds * SAMPLE_RATE), dtype=np.int16)


def save(path: Path, audio: np.ndarray) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(audio.tobytes())


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="regenerate existing clips")
    args = parser.parse_args()

    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    rows = list(csv.DictReader(SCRIPTS.open()))
    manifest = []

    async with http_context.open():
        tts = deepgram.TTS(model=CALLER_VOICE, sample_rate=SAMPLE_RATE)

        for row in rows:
            if row["set"] == "S2":
                variants = [(f"{row['id']}_p{ms}", ms) for ms in PAUSES_MS]
            else:
                variants = [(row["id"], None)]
            todo = args.force or any(not (AUDIO_DIR / f"{cid}.wav").exists() for cid, _ in variants)

            if todo and row["set"] == "S2":
                before, after = (part.strip() for part in row["text"].split("|"))
                # "..." keeps the first half sounding unfinished, like a real hesitation
                first, second = await speak(tts, before + "..."), await speak(tts, after)
            elif todo:
                whole = await speak(tts, row["text"])

            for clip_id, pause_ms in variants:
                if todo:
                    trail = S4_TRAIL_S if row["set"] == "S4" else TRAIL_S
                    body = [first, silence(pause_ms / 1000), second] if pause_ms else [whole]
                    save(AUDIO_DIR / f"{clip_id}.wav", np.concatenate([silence(LEAD_S), *body, silence(trail)]))
                    print(f"generated {clip_id}")
                manifest.append({
                    "id": clip_id,
                    "source_id": row["id"],
                    "set": row["set"],
                    "text": row["text"].replace(" | ", "... "),
                    "pause_ms": pause_ms or "",
                    "measured_pause_ms": measured_gap_ms(AUDIO_DIR / f"{clip_id}.wav") if pause_ms else "",
                    "expected": row["expected"],
                })

        await tts.aclose()

    with MANIFEST.open("w", newline="") as f:
        writer = csv.DictWriter(f, list(manifest[0]))
        writer.writeheader()
        writer.writerows(manifest)
    print(f"{len(manifest)} clips in {MANIFEST}")


if __name__ == "__main__":
    asyncio.run(main())
