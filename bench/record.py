"""Record the natural eval set, one prompt at a time.

Reads bench/sets/natural/manifest.csv and saves each clip to
bench/sets/natural/audio/<id>.wav (16 kHz, mono, 16-bit). Clips that
already exist are skipped, so you can stop and resume any time.

    uv run python bench/record.py            # record missing clips
    uv run python bench/record.py --redo 02 03  # re-record specific clips
"""

import argparse
import csv
import subprocess
from pathlib import Path

SET_DIR = Path(__file__).parent / "sets" / "natural"
MANIFEST = SET_DIR / "manifest.csv"
AUDIO_DIR = SET_DIR / "audio"


def record(path: Path) -> None:
    input("  [Enter] start recording ")
    proc = subprocess.Popen(
        ["arecord", "-q", "-f", "S16_LE", "-r", "16000", "-c", "1", str(path)]
    )
    input("  ● recording... [Enter] stop ")
    proc.terminate()
    proc.wait()


def play(path: Path) -> None:
    subprocess.run(["aplay", "-q", str(path)])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--redo", nargs="+", help="ids of clips to re-record")
    args = parser.parse_args()

    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    rows = list(csv.DictReader(MANIFEST.open()))
    todo = [r for r in rows if r["id"] in args.redo] if args.redo else [
        r for r in rows if not (AUDIO_DIR / f"{r['id']}.wav").exists()
    ]
    print(f"{len(rows) - len(todo)}/{len(rows)} recorded, {len(todo)} to go\n")

    for n, row in enumerate(todo, 1):
        path = AUDIO_DIR / f"{row['id']}.wav"
        print(f"[{n}/{len(todo)}]  id {row['id']} · {row['category']}")
        print(f"  say:  \"{row['text']}\"")
        if row["note"]:
            print(f"  how:  {row['note']}")
        while True:
            record(path)
            choice = input("  [Enter] keep · [p] play · [r] redo · [q] quit ").strip().lower()
            while choice == "p":
                play(path)
                choice = input("  [Enter] keep · [p] play · [r] redo · [q] quit ").strip().lower()
            if choice == "r":
                continue
            if choice == "q":
                print("stopped (this clip was kept), run again to continue")
                return
            break
        print()

    print("all done")


if __name__ == "__main__":
    main()
