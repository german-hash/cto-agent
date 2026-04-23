import os
import httpx

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")

async def text_to_speech(text: str, voice: str = "alloy") -> bytes:
    """Convierte texto a audio usando OpenAI TTS. Devuelve bytes del MP3."""
    # Limpiar markdown para que suene bien
    import re
    clean = re.sub(r'\*\*(.+?)\*\*', r'\1', text)  # bold
    clean = re.sub(r'\*(.+?)\*', r'\1', clean)       # italic
    clean = re.sub(r'#{1,3}\s', '', clean)            # headers
    clean = re.sub(r'---+', '', clean)                # separadores
    clean = re.sub(r'•', '-', clean)                  # bullets

    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(
            "https://api.openai.com/v1/audio/speech",
            headers={
                "Authorization": f"Bearer {OPENAI_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": "tts-1",
                "input": clean[:4096],  # límite de TTS
                "voice": voice          # alloy, echo, fable, onyx, nova, shimmer
            }
        )
        r.raise_for_status()
        return r.content
