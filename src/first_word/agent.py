from dotenv import load_dotenv
from livekit.agents import (
    Agent,
    AgentServer,
    AgentSession,
    ConversationItemAddedEvent,
    JobContext,
    cli,
)
from livekit.plugins import silero
from livekit.plugins.turn_detector.multilingual import MultilingualModel

from first_word.latency_log import LatencyLogger

load_dotenv(".env.local")

# LiveKit Inference model ids
STT_MODEL = "deepgram/nova-3"
LLM_MODEL = "openai/gpt-4.1-mini"
TTS_MODEL = "cartesia/sonic-3"

INSTRUCTIONS = """You are the phone receptionist for a small property management company.
You help callers with questions about rental listings and booking viewings.
Keep replies short and conversational: one or two sentences, no lists, no markdown.
"""


class Receptionist(Agent):
    def __init__(self) -> None:
        super().__init__(instructions=INSTRUCTIONS)


server = AgentServer()


@server.rtc_session()
async def entrypoint(ctx: JobContext):
    session = AgentSession(
        stt=STT_MODEL,
        llm=LLM_MODEL,
        tts=TTS_MODEL,
        vad=silero.VAD.load(),
        turn_handling={"turn_detection": MultilingualModel()},
    )

    latency = LatencyLogger(
        config={"stt": STT_MODEL, "llm": LLM_MODEL, "tts": TTS_MODEL},
        room=ctx.room.name,
    )

    @session.on("conversation_item_added")
    def _on_item(ev: ConversationItemAddedEvent):
        latency.on_item(ev.item)

    await session.start(agent=Receptionist(), room=ctx.room)
    await session.generate_reply(instructions="Greet the caller and ask how you can help.")


if __name__ == "__main__":
    cli.run_app(server)
