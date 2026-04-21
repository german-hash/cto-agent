from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from agent import chat

app = FastAPI(title="CTO Agent", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Historial en memoria (se resetea si el servidor se reinicia)
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

    conversation_history.append({
        "role": "user",
        "content": req.message
    })

    response_text = chat(conversation_history)

    conversation_history.append({
        "role": "assistant",
        "content": response_text
    })

    return MessageResponse(
        response=response_text,
        history_length=len(conversation_history)
    )

@app.delete("/chat/reset")
def reset_conversation():
    conversation_history.clear()
    return {"status": "ok", "message": "Conversación reseteada"}

@app.get("/context/summary")
def context_summary():
    """Devuelve un resumen del contexto cargado (útil para verificar que todo esté bien)"""
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
