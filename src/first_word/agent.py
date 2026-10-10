from dotenv import load_dotenv
from livekit.agents import (
    Agent,
    AgentServer,
    ConversationItemAddedEvent,
    JobContext,
    cli,
)

from first_word.latency_log import LatencyLogger
from first_word.pipeline import PipelineConfig, build_session

load_dotenv(".env.local")

CONFIG = PipelineConfig()

INSTRUCTIONS = """You are the phone receptionist for a small property management company.
You help callers with questions about rental listings and booking viewings.
Keep replies short and conversational: one or two sentences, no lists, no markdown.
"""

# TTS can only start once the first sentence is complete, so a short opener
# ("Sure.") lets the agent start speaking sooner
SHORT_FIRST_SENTENCE = """
Always start your reply with a very short first sentence of one to three words,
such as "Sure.", "Good question." or "Let me see.", then continue.
"""

PROMPTS = {"default": INSTRUCTIONS, "short_first": INSTRUCTIONS + SHORT_FIRST_SENTENCE}


class Receptionist(Agent):
    def __init__(self, prompt: str = "default") -> None:
        super().__init__(instructions=PROMPTS[prompt])


server = AgentServer()


@server.rtc_session()
async def entrypoint(ctx: JobContext):
    session = build_session(CONFIG)
    latency = LatencyLogger(config=CONFIG.as_dict(), room=ctx.room.name)

    @session.on("conversation_item_added")
    def _on_item(ev: ConversationItemAddedEvent):
        latency.on_item(ev.item)

    await session.start(agent=Receptionist(CONFIG.prompt), room=ctx.room)
    await session.generate_reply(instructions="Greet the caller and ask how you can help.")


if __name__ == "__main__":
    cli.run_app(server)
