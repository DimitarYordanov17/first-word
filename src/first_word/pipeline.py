"""Builds the voice pipeline from one config, shared by the live agent and the bench.

Every setting the latency study varies is spelled out here, including the ones
that match LiveKit's defaults, so a run's config fully describes what was measured.
"""

from dataclasses import asdict, dataclass
from typing import Literal

from livekit.agents import AgentSession, inference
from livekit.plugins import deepgram, openai, silero
from livekit.plugins.turn_detector.multilingual import MultilingualModel


@dataclass(frozen=True)
class PipelineConfig:
    # providers, called directly with our own keys
    stt_model: str = "nova-3"
    llm_model: str = "gpt-4.1-mini"
    tts_model: str = "aura-2-andromeda-en"
    language: str = "en-US"
    # Flux only: how confident Flux must be before sending an early ("preflight")
    # transcript that preemptive generation can start on
    flux_eager_eot: float = 0.5

    # VAD: silence needed before "end of speech"
    vad_min_silence: float = 0.55

    # turn detection: "text" = local transcript model (deprecated plugin),
    # "audio" = LiveKit's newer audio model (cloud, local fallback), "none" = VAD only
    turn_detector: Literal["text", "audio", "none"] = "text"

    # endpointing: how long to wait after the user stops before committing the turn
    endpointing_mode: Literal["fixed", "dynamic"] = "fixed"
    min_delay: float = 0.5
    max_delay: float = 3.0

    # start work before the turn is committed
    preemptive_generation: bool = True
    preemptive_tts: bool = False

    # interruptions while the agent speaks: "adaptive" = LiveKit's cloud model, "vad" = duration rule
    interruption_mode: Literal["adaptive", "vad"] = "adaptive"

    # agent prompt: "default" or "short_first" (opens every reply with a 1-3 word sentence)
    prompt: Literal["default", "short_first"] = "default"

    def as_dict(self) -> dict:
        return asdict(self)


def _stt(cfg: PipelineConfig):
    if cfg.stt_model.startswith("flux"):
        return deepgram.STTv2(model=cfg.stt_model, eager_eot_threshold=cfg.flux_eager_eot)
    return deepgram.STT(model=cfg.stt_model, language=cfg.language)


def build_session(cfg: PipelineConfig) -> AgentSession:
    # only the selected detector gets instantiated
    detector = {
        "text": MultilingualModel,
        "audio": inference.TurnDetector,
        "none": "vad",  # explicit VAD-only mode; None would let LiveKit auto-select
    }[cfg.turn_detector]
    turn_detection = detector() if callable(detector) else detector

    return AgentSession(
        stt=_stt(cfg),
        llm=openai.LLM(model=cfg.llm_model),
        tts=deepgram.TTS(model=cfg.tts_model),
        vad=silero.VAD.load(min_silence_duration=cfg.vad_min_silence),
        turn_handling={
            "turn_detection": turn_detection,
            "endpointing": {
                "mode": cfg.endpointing_mode,
                "min_delay": cfg.min_delay,
                "max_delay": cfg.max_delay,
            },
            "preemptive_generation": {
                "enabled": cfg.preemptive_generation,
                "preemptive_tts": cfg.preemptive_tts,
            },
            "interruption": {"mode": cfg.interruption_mode},
        },
    )
