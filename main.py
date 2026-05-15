from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from agent import chat, chat_with_history, chat_with_history_image, reset_history, daily_briefing, sync_full, sync_week, sync_delta
from whisper_client import transcribe_audio
from tts_client import text_to_speech
import os
import logging
import httpx
import base64

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")

HELP_TEXT = """🤖 *AgenteCTO — Comandos y funciones*

━━━━━━━━━━━━━━━━━━━
📋 *COMANDOS*
━━━━━━━━━━━━━━━━━━━
/briefing — Resumen del día (1:1s, OKRs, alertas)
/sync — Sincroniza última entrada de cada página de Notion
/sync_week — Sincroniza últimas 3 entradas por página
/sync_full — Sincroniza todo el historial de Notion
/reset — Borra el historial de conversación
/help — Esta ayuda

━━━━━━━━━━━━━━━━━━━
📝 *REGISTRAR EN NOTION*
━━━━━━━━━━━━━━━━━━━
1:1 de hoy:
"registrá el 1:1 de hoy con [persona]: tema1, tema2"

Nota general (Mis Notas):
"toma nota sobre [tema]: detalle1, detalle2"
"registrame en Notion una nota con [tema]: ..."

Tarea pendiente:
"registrá tarea: [descripción]"
"anotá pendiente: [descripción]"

━━━━━━━━━━━━━━━━━━━
📖 *LEER DE NOTION*
━━━━━━━━━━━━━━━━━━━
"leeme el 1:1 de [persona]"
"leeme las tareas pendientes"
"resumen de 1:1 de la semana"
"qué temas hablamos con [persona]?"

━━━━━━━━━━━━━━━━━━━
🎙️ *VOZ*
━━━━━━━━━━━━━━━━━━━
Mandá un audio → el agente lo transcribe y responde
"leeme con voz [pregunta]" → responde con audio
"leelo con voz" → ídem

━━━━━━━━━━━━━━━━━━━
🧠 *MEMORIA PERSISTENTE*
━━━━━━━━━━━━━━━━━━━
"recordá que [hecho importante]"
→ Se guarda y recuerda aunque hagas /reset

━━━━━━━━━━━━━━━━━━━
📸 *IMAGEN*
━━━━━━━━━━━━━━━━━━━
Mandá un screenshot del board de Azure DevOps
→ El agente analiza el estado de features y OKRs

━━━━━━━━━━━━━━━━━━━
🗂️ *PREPARAR REUNIONES*
━━━━━━━━━━━━━━━━━━━
"preparame el 1:1 con [persona]"
→ Agenda con contexto real de Notion

"generame un update para [stakeholder]"
→ Resumen ejecutivo para Diego M, Pablo E o Carly"""
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

async def send_telegram_voice(chat_id: str, audio_bytes: bytes):
    """Envía un mensaje de voz a Telegram."""
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(
            f"{TELEGRAM_API}/sendVoice",
            data={"chat_id": chat_id},
            files={"voice": ("response.mp3", audio_bytes, "audio/mpeg")}
        )
        logger.info(f"Telegram sendVoice response: {r.status_code}")

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

        # Comando /help
        if text.lower() == "/help":
            await send_telegram_message(chat_id, HELP_TEXT)
            return {"ok": True}

        # Comandos de sincronización con Notion
        if text.lower() == "/sync_full":
            await send_telegram_message(chat_id, "🔄 Sincronizando todo el historial de Notion... puede tardar unos segundos.")
            response = sync_full(chat_id)
            await send_telegram_message(chat_id, response)
            return {"ok": True}

        if text.lower() == "/sync_week":
            await send_telegram_message(chat_id, "🔄 Sincronizando últimas reuniones de la semana...")
            response = sync_week(chat_id)
            await send_telegram_message(chat_id, response)
            return {"ok": True}

        if text.lower() == "/sync":
            await send_telegram_message(chat_id, "🔄 Sincronizando última entrada de cada página...")
            response = sync_delta(chat_id)
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

            voice_keywords = ["leeme con voz", "respondeme con voz", "decime con voz", "leelo con voz"]
            wants_voice = any(k in transcribed.lower() for k in voice_keywords)
            clean_transcribed = transcribed
            for k in voice_keywords:
                clean_transcribed = clean_transcribed.lower().replace(k, "").strip(" :,")
            if not clean_transcribed:
                clean_transcribed = transcribed

            response = chat_with_history(chat_id, clean_transcribed)

            if wants_voice:
                try:
                    audio_bytes = await text_to_speech(response)
                    await send_telegram_voice(chat_id, audio_bytes)
                except Exception as e:
                    logger.error(f"Error en TTS: {e}")
                    await send_telegram_message(chat_id, response)
            else:
                await send_telegram_message(chat_id, response)
            return {"ok": True}

        # Mensaje de texto normal
        if text:
            # Detectar si pide respuesta por voz
            voice_keywords = ["leeme con voz", "respondeme con voz", "decime con voz", "leelo con voz"]
            wants_voice = any(k in text.lower() for k in voice_keywords)

            # Limpiar el keyword del mensaje antes de procesarlo
            clean_text = text
            for k in voice_keywords:
                clean_text = clean_text.lower().replace(k, "").strip(" :,")
            if not clean_text:
                clean_text = text

            response = chat_with_history(chat_id, clean_text)

            if wants_voice:
                try:
                    audio_bytes = await text_to_speech(response)
                    await send_telegram_voice(chat_id, audio_bytes)
                except Exception as e:
                    logger.error(f"Error en TTS: {e}")
                    await send_telegram_message(chat_id, response)
            else:
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
