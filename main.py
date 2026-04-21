from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from agent import chat, chat_with_history, reset_history, daily_briefing
import os
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

app = FastAPI(title="CTO Agent", version="2.0.0")

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
    return {"status": "ok", "message": "Conversación reseteada"}

@app.get("/context/summary")
def context_summary():
    import json
    with open("context.json", "r", encoding="utf-8") as f:
        ctx = json.load(f)
    return {
        "team_count": len(ctx.get("team", [])),
        "stakeholders": [s["name"] for s in ctx.get("stakeholders", [])],
        "my_reports": [s["name"] for s in ctx.get("my_1on1s", [])],
        "okrs": [kr["kr_id"] for kr in ctx.get("okrs_q2_2026", [])],
        "open_decisions": len(ctx.get("open_decisions", [])),
    }

import httpx

async def send_telegram_message(chat_id: str, text: str):
    async with httpx.AsyncClient() as client:
        r = await client.post(f"{TELEGRAM_API}/sendMessage", json={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML"
        })
        logger.info(f"Telegram sendMessage response: {r.status_code} {r.text}")

@app.post("/telegram/webhook")
async def telegram_webhook(request: Request):
    try:
        data = await request.json()
        logger.info(f"Webhook payload: {data}")

        message = data.get("message", {})
        chat_id = str(message.get("chat", {}).get("id", ""))
        text = message.get("text", "").strip()

        logger.info(f"chat_id={chat_id} text={text}")

        if not chat_id or not text:
            return {"ok": True}

        if text == "/reset":
            reset_history(chat_id)
            await send_telegram_message(chat_id, "🗑️ Historial borrado. Empezamos de cero.")
            return {"ok": True}

        if text == "/briefing":
            response = daily_briefing(chat_id)
            await send_telegram_message(chat_id, response)
            return {"ok": True}

        response = chat_with_history(chat_id, text)
        logger.info(f"Agent response: {response[:100]}")
        await send_telegram_message(chat_id, response)
        return {"ok": True}

    except Exception as e:
        logger.error(f"Error en webhook: {e}", exc_info=True)
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
