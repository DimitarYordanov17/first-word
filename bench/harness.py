"""Plays eval clips into a configured voice pipeline and measures what happens.

No room, no WebRTC: a fake "microphone" streams the clip (then silence) in real
time into the session, and a fake "speaker" timestamps the agent's audio. One
warm session serves many clips; the chat history is reset between clips so every
clip is measured on its own.

Two kinds of clips:
  latency clips (S1-S4): the clip plays; each agent reply is cut as soon as its
      first audio arrives (only the timing matters). Records the LiveKit metrics
      and whether a turn was committed before the caller finished (a cut-off).
  overlap clips (S5, S6): the setup question plays, the agent starts answering,
      and the clip is played over it OFFSET seconds after its first audio.
      Records whether and how fast the agent stopped.

    uv run python bench/harness.py s1_01 s2_01_p800 s5_01   # quick check on the baseline
"""

import asyncio
import csv
import time
import wave
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from dotenv import load_dotenv
from livekit import rtc
from livekit.agents import AgentSession, ConversationItemAddedEvent, llm
from livekit.agents.inference_runner import _InferenceRunner
from livekit.agents.testing import fake_job_context
from livekit.agents.utils import http_context
from livekit.agents.voice import io

from first_word.agent import Receptionist
from first_word.pipeline import PipelineConfig, build_session

load_dotenv(".env.local")

BENCH = Path(__file__).parent
SAMPLE_RATE = 16000
FRAME = SAMPLE_RATE // 100  # 10 ms
REPLY_TIMEOUT_S = 6.0  # how long to wait for a reply after the caller's speech ends
OVERLAP_WATCH_S = 4.0  # how long to watch the agent after playing an overlap clip


# the natural manifest uses category names; map them onto the synthetic set codes
CATEGORY_TO_SET = {"clean": "S1", "pause": "S2", "short": "S3", "interrupt": "S5",
                   "backchannel": "S6", "tool": "S7"}


@dataclass(frozen=True)
class Clip:
    id: str
    set: str
    expected: str
    audio: np.ndarray
    speech_end_s: float  # when the caller's last word ends, relative to clip start
    pause_ms: str = ""
    measured_pause_ms: str = ""
    holdout: bool = False

    @property
    def duration_s(self) -> float:
        return len(self.audio) / SAMPLE_RATE


def load_clips(set_name: str) -> dict[str, Clip]:
    """Load a set's manifest and audio. set_name is "synthetic" or "natural"."""
    set_dir = BENCH / "sets" / set_name
    clips = {}
    for row in csv.DictReader((set_dir / "manifest.csv").open()):
        with wave.open(str(set_dir / "audio" / f"{row['id']}.wav")) as w:
            assert w.getframerate() == SAMPLE_RATE and w.getnchannels() == 1
            audio = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
        clips[row["id"]] = Clip(
            id=row["id"],
            set=row.get("set") or CATEGORY_TO_SET[row["category"]],
            expected=row["expected"],
            audio=audio,
            speech_end_s=_speech_end(audio),
            pause_ms=row.get("pause_ms", ""),
            measured_pause_ms=row.get("measured_pause_ms", ""),
            holdout=row.get("holdout") == "yes",
        )
    return clips


def _speech_end(audio: np.ndarray) -> float:
    levels = np.array([np.abs(audio[i : i + FRAME]).mean() for i in range(0, len(audio), FRAME)])
    voiced = np.nonzero(levels > levels.max() * 0.05)[0]
    return (voiced[-1] + 1) * FRAME / SAMPLE_RATE


class ThreadInferenceExecutor:
    """Runs local models (the text turn detector) in a thread. In a real worker they
    run in a separate shared process; a thread keeps the event loop free the same way."""

    def __init__(self) -> None:
        self._runners: dict[str, _InferenceRunner] = {}

    async def preload(self) -> None:
        """Load every local model up front. Loading on the first prediction takes longer
        than the turn detector's timeout, which silently falls back to max_delay."""
        for method, runner_cls in _InferenceRunner.registered_runners.items():
            runner = runner_cls()
            await asyncio.to_thread(runner.initialize)
            self._runners[method] = runner

    async def do_inference(self, method: str, data: bytes) -> bytes | None:
        return await asyncio.to_thread(self._runners[method].run, data)


class FakeMic(io.AudioInput):
    """Streams 10 ms frames in real time: queued clip audio, otherwise silence,
    exactly like a microphone that never stops."""

    def __init__(self) -> None:
        super().__init__(label="FakeMic")
        self._out: asyncio.Queue[rtc.AudioFrame] = asyncio.Queue()
        self._pending = np.zeros(0, dtype=np.int16)
        self._task = asyncio.create_task(self._run())

    def play(self, audio: np.ndarray) -> float:
        """Queue a clip; returns the wall-clock time its first sample enters the pipeline."""
        delay = len(self._pending) / SAMPLE_RATE
        self._pending = np.concatenate([self._pending, audio])
        return time.time() + delay

    async def _run(self) -> None:
        next_t = time.perf_counter()
        while True:
            chunk, self._pending = self._pending[:FRAME], self._pending[FRAME:]
            if len(chunk) < FRAME:
                chunk = np.concatenate([chunk, np.zeros(FRAME - len(chunk), dtype=np.int16)])
            await self._out.put(rtc.AudioFrame(chunk.tobytes(), SAMPLE_RATE, 1, FRAME))
            next_t += 0.01
            await asyncio.sleep(max(0.0, next_t - time.perf_counter()))

    async def __anext__(self) -> rtc.AudioFrame:
        return await self._out.get()

    async def aclose(self) -> None:
        self._task.cancel()


class FakeSpeaker(io.AudioOutput):
    """Accepts the agent's audio, "plays" it in real time, and timestamps what happens."""

    def __init__(self) -> None:
        super().__init__(label="FakeSpeaker", next_in_chain=None, sample_rate=None,
                         capabilities=io.AudioOutputCapabilities(pause=True))
        self.events: list[tuple[str, float]] = []
        self._start: float | None = None
        self._pushed = 0.0
        self._paused_total = 0.0
        self._paused_at: float | None = None
        self._finish_task: asyncio.Task | None = None

    async def capture_frame(self, frame: rtc.AudioFrame) -> None:
        await super().capture_frame(frame)
        if self._start is None:
            self._start = time.time()
            self.events.append(("first_audio", self._start))
            self.on_playback_started(created_at=self._start)
        self._pushed += frame.duration

    def _position(self) -> float:
        if self._start is None:
            return 0.0
        paused_now = time.time() - self._paused_at if self._paused_at else 0.0
        return min(self._pushed, time.time() - self._start - self._paused_total - paused_now)

    def flush(self) -> None:
        super().flush()
        if self._start is not None:
            self._finish_task = asyncio.create_task(self._finish_when_played())

    async def _finish_when_played(self) -> None:
        while self._position() < self._pushed:
            await asyncio.sleep(0.01)
        self._end(interrupted=False)

    def clear_buffer(self) -> None:
        if self._start is not None:
            self.events.append(("cleared", time.time()))
            if self._finish_task:
                self._finish_task.cancel()
            self._end(interrupted=True)

    def pause(self) -> None:
        super().pause()
        self._paused_at = time.time()
        self.events.append(("paused", self._paused_at))

    def resume(self) -> None:
        super().resume()
        if self._paused_at:
            self._paused_total += time.time() - self._paused_at
            self._paused_at = None
        self.events.append(("resumed", time.time()))

    def _end(self, interrupted: bool) -> None:
        position = self._position()
        self.events.append(("finished", time.time()))
        self._start, self._pushed, self._paused_total, self._paused_at = None, 0.0, 0.0, None
        self.on_playback_finished(playback_position=position, interrupted=interrupted)


class Harness:
    """One warm session for one config. Use as `async with Harness(cfg) as h:`."""

    def __init__(self, cfg: PipelineConfig, setup_clip: Clip,
                 executor: ThreadInferenceExecutor | None = None) -> None:
        self.cfg = cfg
        self.setup_clip = setup_clip
        self.executor = executor  # pass a preloaded one to share the model across sessions
        self.usage = None  # the session's model usage, filled in on exit

    async def __aenter__(self) -> "Harness":
        if self.executor is None:
            self.executor = ThreadInferenceExecutor()
            await self.executor.preload()
        self._job = fake_job_context(inference_executor=self.executor)
        self._job.__enter__()
        self._http = http_context.open()  # the HTTP session a real worker would provide
        await self._http.__aenter__()
        self.mic, self.speaker = FakeMic(), FakeSpeaker()
        self.session: AgentSession = build_session(self.cfg)
        self.session.input.audio = self.mic
        self.session.output.audio = self.speaker
        self.items: list[ConversationItemAddedEvent] = []
        self.session.on("conversation_item_added", self.items.append)
        self.agent = Receptionist(self.cfg.prompt)
        await self.session.start(agent=self.agent, record=False)
        # warm-up: opens the provider connections so the first measured clip isn't a cold start
        await self._run_latency(self.setup_clip)
        return self

    async def __aexit__(self, *exc) -> None:
        self.usage = self.session.usage
        await self.session.aclose()
        await self.mic.aclose()
        await self._http.__aexit__(*exc)
        self._job.__exit__(*exc)

    async def run(self, clip: Clip, offset_s: float = 0.5) -> dict:
        try:
            if clip.set in ("S5", "S6") or clip.expected in ("stop", "continue"):
                result = await self._run_overlap(clip, offset_s)
            else:
                result = await self._run_latency(clip)
            result["error"] = ""
        except Exception as e:  # recorded, never silently dropped
            result = {"error": f"{type(e).__name__}: {e}"}
        await self._reset()
        return {"clip": clip.id, "set": clip.set, "expected": clip.expected,
                "pause_ms": clip.pause_ms, "measured_pause_ms": clip.measured_pause_ms,
                **result}

    async def _run_latency(self, clip: Clip) -> dict:
        self.items.clear()
        self.speaker.events.clear()
        start = self.mic.play(clip.audio)
        speech_end = start + clip.speech_end_s

        # cut every reply at its first audio; stop once a reply came after the caller finished
        deadline = speech_end + REPLY_TIMEOUT_S
        replied_after_end = False
        while time.time() < deadline and not replied_after_end:
            await asyncio.sleep(0.02)
            if self._first_audio_times() and self.speaker._start is not None:
                self.session.interrupt(force=True)
            replied_after_end = any(t >= speech_end for t in self._first_audio_times())
        await asyncio.sleep(0.5)  # let the cut reply land in the history with its metrics

        users = [ev for ev in self.items if ev.item.role == "user"]
        agents = [ev for ev in self.items if ev.item.role == "assistant"]
        early = [ev for ev in users if ev.created_at < speech_end]
        last_user = users[-1].item if users else None
        reply = agents[-1].item if agents else None
        um, am = (last_user.metrics if last_user else {}), (reply.metrics if reply else {})
        first_audio = [t for t in self._first_audio_times() if t >= speech_end]
        return {
            "cut_off": bool(early) or any(t < speech_end for t in self._first_audio_times()),
            "user_turns": len(users),
            "replied": bool(first_audio),
            "first_audio_after_end_ms": _ms(first_audio[0] - speech_end) if first_audio else "",
            "user_text": last_user.text_content if last_user else "",
            "end_of_turn_delay": _ms(um.get("end_of_turn_delay")),
            "transcription_delay": _ms(um.get("transcription_delay")),
            "llm_ttft": _ms(am.get("llm_node_ttft")),
            "llm_ttfs": _ms(am.get("llm_node_ttfs")),
            "tts_ttfb": _ms(am.get("tts_node_ttfb")),
            "e2e_latency": _ms(am.get("e2e_latency")),
        }

    async def _run_overlap(self, clip: Clip, offset_s: float) -> dict:
        self.items.clear()
        self.speaker.events.clear()
        setup_start = self.mic.play(self.setup_clip.audio)
        deadline = setup_start + self.setup_clip.speech_end_s + REPLY_TIMEOUT_S
        while not self._first_audio_times():
            if time.time() > deadline:
                return {"valid": False, "note": "agent never answered the setup question"}
            await asyncio.sleep(0.02)

        reply_start = self._first_audio_times()[0]
        await asyncio.sleep(max(0.0, reply_start + offset_s - time.time()))
        if self.speaker._start is None:
            return {"valid": False, "note": f"agent finished before {offset_s}s"}

        overlap_start = self.mic.play(clip.audio)
        await asyncio.sleep(clip.duration_s + OVERLAP_WATCH_S)

        after = [(name, t) for name, t in self.speaker.events if t >= overlap_start]
        cleared = [t for name, t in after if name == "cleared"]
        finished_naturally = any(name == "finished" for name, t in after) and not cleared
        self.session.interrupt(force=True)
        return {
            "valid": True,
            "offset_s": offset_s,
            "stopped": bool(cleared),
            "stop_after_ms": _ms(cleared[0] - overlap_start) if cleared else "",
            "paused": any(name == "paused" for name, _ in after),
            "resumed": any(name == "resumed" for name, _ in after),
            "finished_naturally": finished_naturally,
        }

    def _first_audio_times(self) -> list[float]:
        return [t for name, t in self.speaker.events if name == "first_audio"]

    async def _reset(self) -> None:
        if self.speaker._start is not None:
            self.session.interrupt(force=True)
        await asyncio.sleep(1.5)  # let late transcripts from this clip arrive
        self.session.clear_user_turn()  # drop them so they can't leak into the next clip
        await self.agent.update_chat_ctx(llm.ChatContext.empty())
        self.items.clear()


def _ms(seconds: float | None) -> int | str:
    return "" if seconds is None else round(seconds * 1000)


async def _demo(clip_ids: list[str]) -> None:
    clips = load_clips("synthetic")
    async with Harness(PipelineConfig(), clips["setup_01"]) as h:
        for cid in clip_ids:
            print(await h.run(clips[cid]))


if __name__ == "__main__":
    import sys

    asyncio.run(_demo(sys.argv[1:] or ["s1_01"]))
