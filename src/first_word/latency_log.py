"""Per-turn latency logging to CSV.

A turn = one user message followed by the agent's reply. LiveKit attaches
latency metrics to each ChatMessage: the user message carries the
end-of-turn and transcription delays, the assistant message carries
LLM/TTS timings and the end-to-end latency (user stops speaking -> agent
starts speaking).
"""

import csv
import time
from pathlib import Path

from livekit.agents.llm import ChatMessage

METRICS_DIR = Path("metrics")

METRIC_FIELDS = [
    "user_text",
    "agent_text",
    "end_of_turn_delay",
    "transcription_delay",
    "llm_ttft",
    "llm_ttfs",
    "tts_ttfb",
    "e2e_latency",
    "interrupted",
]


class LatencyLogger:
    def __init__(self, config: dict, room: str) -> None:
        self.config = config
        self.fields = ["ts", "room", "turn", *config, *METRIC_FIELDS]
        self.room = room
        self.turn = 0
        self.pending_user: ChatMessage | None = None
        METRICS_DIR.mkdir(exist_ok=True)
        self.path = METRICS_DIR / f"turns-{time.strftime('%Y%m%d-%H%M%S')}.csv"
        with self.path.open("w", newline="") as f:
            csv.DictWriter(f, self.fields).writeheader()

    def on_item(self, item) -> None:
        if not isinstance(item, ChatMessage):
            return
        if item.role == "user":
            self.pending_user = item
        elif item.role == "assistant":
            self._write(self.pending_user, item)
            self.pending_user = None

    def _write(self, user: ChatMessage | None, agent: ChatMessage) -> None:
        um = user.metrics if user else {}
        am = agent.metrics
        self.turn += 1
        row = {
            "ts": round(time.time(), 3),
            "room": self.room,
            "turn": self.turn,
            **self.config,
            "user_text": (user.text_content or "") if user else "",
            "agent_text": agent.text_content or "",
            "end_of_turn_delay": _ms(um.get("end_of_turn_delay")),
            "transcription_delay": _ms(um.get("transcription_delay")),
            "llm_ttft": _ms(am.get("llm_node_ttft")),
            "llm_ttfs": _ms(am.get("llm_node_ttfs")),
            "tts_ttfb": _ms(am.get("tts_node_ttfb")),
            "e2e_latency": _ms(am.get("e2e_latency")),
            "interrupted": agent.interrupted,
        }
        with self.path.open("a", newline="") as f:
            csv.DictWriter(f, self.fields).writerow(row)


def _ms(seconds: float | None) -> int | str:
    return "" if seconds is None else round(seconds * 1000)
