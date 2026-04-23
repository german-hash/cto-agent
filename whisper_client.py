import os
import httpx

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")

async def transcribe_audio(audio_bytes: bytes, filename: str = "audio.ogg") -> str:
    """Transcribe audio usando OpenAI Whisper API."""
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(
            "https://api.openai.com/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
            files={"file": (filename, audio_bytes, "audio/ogg")},
            data={"model": "whisper-1", "language": "es"}
        )
        r.raise_for_status()
        return r.json().get("text", "")
