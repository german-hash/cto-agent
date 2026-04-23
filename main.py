from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from agent import chat, chat_with_history, chat_with_history_image, reset_history, daily_briefing
from whisper_client import transcribe_audio
import os
import logging
import httpx
import base64

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

app = FastAPI(title="CTO Agent", version="3.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

conversation_history: list[dict] = []

class MessageRequest(BaseModel):
    message: str

class MessageResponse(BaseModel):
    response: str
    history_length: int

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/chat", response_model=MessageResponse)
def chat_endpoint(req: MessageRequest):
    if not req.message.strip():
        raise HTTPException(status_code=400, detail="El mensaje no puede estar vacío")
    conversation_history.append({"role": "user", "content": req.message})
    response_text = chat(conversation_history)
    conversation_history.append({"role": "assistant", "content": response_text})
    return MessageResponse(response=response_text, history_length=len(conversation_history))

@app.delete("/chat/reset")
def reset_conversation():
    conversation_history.clear()
    return {"status": "ok"}

@app.get("/context/summary")
def context_summary():
    import json
    with open("context.json", "r", encoding="utf-8") as f:
        ctx = json.load(f)
    return {
        "team_count": len(ctx.get("team", [])),
        "stakeholders": [s["name"] for s in ctx.get("stakeholders", [])],
        "okrs": [kr["kr_id"] for kr in ctx.get("okrs_q2_2026", [])],
    }

async def send_telegram_message(chat_id: str, text: str):
    async with httpx.AsyncClient() as client:
        r = await client.post(f"{TELEGRAM_API}/sendMessage", json={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML"
        })
        logger.info(f"Telegram sendMessage response: {r.status_code} {r.text[:200]}")

async def download_telegram_photo(file_id: str) -> bytes:
    """Descarga una foto de Telegram y devuelve los bytes."""
    async with httpx.AsyncClient() as client:
        # Obtener file path
        r = await client.get(f"{TELEGRAM_API}/getFile", params={"file_id": file_id})
        r.raise_for_status()
        file_path = r.json()["result"]["file_path"]

        # Descargar el archivo
        file_url = f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{file_path}"
        r = await client.get(file_url)
        r.raise_for_status()
        return r.content

@app.post("/telegram/webhook")
async def telegram_webhook(request: Request):
    chat_id = ""
    try:
        data = await request.json()
        logger.info(f"Webhook payload keys: {list(data.get('message', {}).keys())}")

        message = data.get("message", {})
        chat_id = str(message.get("chat", {}).get("id", ""))
        text = message.get("text", "").strip()
        photos = message.get("photo", [])
        caption = message.get("caption", "").strip()

        if not chat_id:
            return {"ok": True}

        # Comando /reset (case insensitive)
        if text.lower() == "/reset":
            reset_history(chat_id)
            await send_telegram_message(chat_id, "🗑️ Historial borrado. Empezamos de cero.")
            return {"ok": True}

        # Comando /briefing
        if text.lower() == "/briefing":
            response = daily_briefing(chat_id)
            await send_telegram_message(chat_id, response)
            return {"ok": True}

        # Mensaje con imagen
        if photos:
            await send_telegram_message(chat_id, "📷 Recibí la imagen, analizándola...")

            # Tomar la foto de mayor resolución
            best_photo = max(photos, key=lambda p: p.get("file_size", 0))
            image_bytes = await download_telegram_photo(best_photo["file_id"])
            image_b64 = base64.b64encode(image_bytes).decode("utf-8")

            # Armar prompt con la imagen
            user_prompt = caption if caption else "Analizá esta imagen del board de Azure DevOps y decime el estado actual de los features y OKRs. Actualizá tu contexto con lo que ves."

            response = await chat_with_history_image(chat_id, user_prompt, image_b64)
            await send_telegram_message(chat_id, response)
            return {"ok": True}


        # Mensaje de voz
        voice = message.get("voice") or message.get("audio")
        if voice:
            await send_telegram_message(chat_id, "🎙️ Escuché tu mensaje, transcribiendo...")
            audio_bytes = await download_telegram_photo(voice["file_id"])
            transcribed = await transcribe_audio(audio_bytes, "audio.ogg")
            logger.info(f"Transcripción: {transcribed}")
            if not transcribed.strip():
                await send_telegram_message(chat_id, "⚠️ No pude entender el audio. Intentá de nuevo.")
                return {"ok": True}
            await send_telegram_message(chat_id, f"📝 Entendí: {transcribed}")
            response = chat_with_history(chat_id, transcribed)
            await send_telegram_message(chat_id, response)
            return {"ok": True}

        # Mensaje de texto normal
        if text:
            response = chat_with_history(chat_id, text)
            await send_telegram_message(chat_id, response)
            return {"ok": True}

        return {"ok": True}

    except Exception as e:
        logger.error(f"Error en webhook: {e}", exc_info=True)
        if chat_id:
            await send_telegram_message(chat_id, "⚠️ Hubo un error procesando tu mensaje. Intentá de nuevo.")
        return {"ok": True}

@app.post("/telegram/briefing")
async def trigger_briefing(request: Request):
    data = await request.json()
    chat_id = str(data.get("chat_id", ""))
    if not chat_id:
        raise HTTPException(status_code=400, detail="chat_id requerido")
    response = daily_briefing(chat_id)
    await send_telegram_message(chat_id, response)
    return {"ok": True, "message": "Briefing enviado"}
