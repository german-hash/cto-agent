import json
import os
import re
from anthropic import Anthropic
from supabase import create_client, Client
from notion_client import get_notion_notes, add_note_to_person, add_task, NOTION_PAGES

client = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

SYSTEM_PROMPT_TEMPLATE = """Sos el asistente personal de German Guerriero, CTO de Tecnología Digital en GoldenArch (McDonald's Argentina).

Tu rol es ayudarlo a gestionar su equipo, proyectos, decisiones técnicas y comunicación con stakeholders.

== ESTRUCTURA DEL ÁREA ==
German tiene a cargo dos sub-áreas:
- Plataformas Digitales: app mobile propia de ecommerce QSR (equipos de Back, Front, QA, Soporte, Infra)
- Flex: hub de pedidos y catálogos (Flex Digital + Menu Editor)

== TU FORMA DE OPERAR ==

1:1s y equipo:
- Cuando te pidan preparar un 1:1, usá las notas de Notion que se inyectan en el mensaje para armar una agenda concreta y relevante.
- Proponé agenda con preguntas sugeridas basadas en los temas reales de las últimas reuniones.
- Recordá que Alex y Pili no reportan directo a German sino a Gallo.

Proyectos y OKRs:
- Cuando te pregunten por estado, organizá por KR y destacá los features bloqueados o sin avance.
- El KR IT-03-01 (ahorros) no tiene features asignadas aún — es un riesgo a señalar.

Stakeholders:
- Pablo E y Carly son líderes de negocio, no reportan a German pero tienen dependencia en línea de puntos.
- Diego M es el jefe directo (VP Regional de Tecnología).
- Para updates hacia arriba, usá lenguaje ejecutivo: impacto de negocio, riesgos, fechas.

Decisiones técnicas:
- Si te piden redactar un ADR, usá el formato: contexto / opciones evaluadas / decisión / consecuencias.

== ESTILO ==
- Respondé siempre en español rioplatense, de forma directa y práctica.
- Sé concreto: si podés dar una lista o una agenda, dála.
- Si algo no está en el contexto, decilo claramente.
- Cuando detectes riesgos, señalalos aunque no te los hayan pedido.
- Cuando respondas por Telegram, usá formato simple sin markdown complejo.

== CONTEXTO ACTUAL ==
{context}
"""

def load_context(path: str = "context.json") -> str:
    with open(path, "r", encoding="utf-8") as f:
        return json.dumps(json.load(f), ensure_ascii=False, indent=2)

def build_system_prompt() -> str:
    context = load_context()
    return SYSTEM_PROMPT_TEMPLATE.format(context=context)

def get_history(chat_id: str, limit: int = 20) -> list[dict]:
    result = supabase.table("conversation_history") \
        .select("role, content") \
        .eq("chat_id", chat_id) \
        .order("created_at", desc=False) \
        .limit(limit) \
        .execute()
    return [{"role": r["role"], "content": r["content"]} for r in result.data]

def save_message(chat_id: str, role: str, content: str):
    supabase.table("conversation_history").insert({
        "chat_id": chat_id,
        "role": role,
        "content": content
    }).execute()

def reset_history(chat_id: str):
    supabase.table("conversation_history") \
        .delete() \
        .eq("chat_id", chat_id) \
        .execute()

def detect_person_in_message(message: str) -> str | None:
    """Detecta si el mensaje menciona a alguien del equipo."""
    message_lower = message.lower()
    for key in NOTION_PAGES.keys():
        if key in message_lower:
            return key
    return None

def enrich_message_with_notion(message: str) -> str:
    """Si el mensaje es sobre un 1:1, inyecta las notas de Notion."""
    keywords_1on1 = ["1:1", "one on one", "reunion", "reunión", "preparame", "preparar"]
    is_1on1 = any(k in message.lower() for k in keywords_1on1)

    if not is_1on1:
        return message

    person = detect_person_in_message(message)
    if not person:
        return message

    notes = get_notion_notes(person)
    return f"{message}\n\n[Notas de Notion para {person}]\n{notes}"

def chat(messages: list[dict]) -> str:
    """Chat sin persistencia (endpoint REST original)."""
    response = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=2048,
        system=build_system_prompt(),
        messages=messages
    )
    text_block = next((b for b in response.content if hasattr(b, "text")), None)
    return text_block.text if text_block else "Sin respuesta."

def chat_with_history(chat_id: str, user_message: str) -> str:
    """Chat con historial persistido en Supabase, con enriquecimiento de Notion."""
    # Detectar intención de escritura en Notion
    write_result = handle_write_intent(user_message)
    if write_result:
        save_message(chat_id, "user", user_message)
        save_message(chat_id, "assistant", write_result)
        return write_result

    # Enriquecer con Notion si aplica
    enriched_message = enrich_message_with_notion(user_message)

    save_message(chat_id, "user", enriched_message)
    messages = get_history(chat_id)

    response = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=2048,
        system=build_system_prompt(),
        messages=messages
    )

    if not response.content:
        raise ValueError("Respuesta vacía de Anthropic")

    text_block = next((b for b in response.content if hasattr(b, "text")), None)
    response_text = text_block.text if text_block else "Sin respuesta."
    save_message(chat_id, "assistant", response_text)
    return response_text

def daily_briefing(chat_id: str) -> str:
    prompt = """Generame el briefing diario de hoy. Incluí:
1. 📅 1:1s de hoy o próximos (según frecuencia y último 1:1)
2. 🚦 Estado general de los OKRs Q2-2026 (destacá riesgos)
3. ⚠️ Algo que merezca atención hoy
Sé breve y directo, formato Telegram."""
    return chat_with_history(chat_id, prompt)

async def chat_with_history_image(chat_id: str, user_message: str, image_b64: str) -> str:
    """Chat con imagen — manda la imagen a Claude con visión."""
    # Guardar el mensaje del usuario en historial
    save_message(chat_id, "user", f"[imagen] {user_message}")

    # Armar mensaje con imagen para Claude
    messages = get_history(chat_id)

    # Reemplazar el último mensaje con el contenido multimodal
    image_message = {
        "role": "user",
        "content": [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/jpeg",
                    "data": image_b64
                }
            },
            {
                "type": "text",
                "text": user_message
            }
        ]
    }

    # Historial previo + mensaje con imagen
    messages_with_image = messages[:-1] + [image_message]

    response = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=2048,
        system=build_system_prompt(),
        messages=messages_with_image
    )

    if not response.content:
        raise ValueError("Respuesta vacía de Anthropic")

    text_block = next((b for b in response.content if hasattr(b, "text")), None)
    response_text = text_block.text if text_block else "Sin respuesta."
    save_message(chat_id, "assistant", response_text)
    return response_text

def handle_write_intent(message: str) -> str | None:
    """
    Detecta si el mensaje es una intención de escritura en Notion.
    Retorna el resultado de la acción o None si no aplica.
    """
    msg = message.lower()

    keywords_write = ["anotá", "anota", "registrá", "registra", "guardá", "guarda", "agregá", "agrega", "escribí", "escribi", "tomá nota", "toma nota"]
    is_write = any(k in msg for k in keywords_write)

    if not is_write:
        return None

    keywords_task = ["tarea", "pendiente", "to do", "todo", "hacer"]
    is_task = any(k in msg for k in keywords_task)

    person = detect_person_in_message(message)

    if is_task:
        # Extraer el contenido de la tarea — todo después del keyword de escritura
        for k in keywords_write:
            if k in msg:
                idx = msg.index(k) + len(k)
                task_text = message[idx:].strip(" :,-")
                return add_task(task_text, person or "")
        return add_task(message, person or "")

    if person:
        # Es una nota para una persona
        for k in keywords_write:
            if k in msg:
                idx = msg.index(k) + len(k)
                note_text = message[idx:].strip(" :,-")
                return add_note_to_person(person, note_text)
        return add_note_to_person(person, message)

    return None
