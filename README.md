# first-word

A latency study of a voice agent built on [LiveKit Agents](https://docs.livekit.io/agents/): where the time goes between the caller going silent and the agent's first word, and which settings move it.

Early work in progress.

## Running locally

Requires [uv](https://docs.astral.sh/uv/) and a LiveKit Cloud project.

```
cp .env.example .env.local   # fill in your LiveKit credentials
uv sync
uv run python src/first_word/agent.py download-files
uv run python src/first_word/agent.py console
```
