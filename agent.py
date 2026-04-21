import json
import os
from anthropic import Anthropic
from supabase import create_client, Client
from notion_client import get_notion_notes

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
- Cuando te pidan preparar un 1:1, SIEMPRE usá la tool get_notion_notes para traer las notas reales de esa persona antes de armar la agenda.
- Proponé agenda concreta con preguntas sugeridas basadas en las notas reales.
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

TOOLS = [
    {
        "name": "get_notion_notes",
        "description": "Trae las notas de reuniones de una persona desde Notion. Usá esta tool siempre que necesites preparar un 1:1 o consultar el historial de reuniones con alguien.",
        "input_schema": {
            "type": "object",
            "properties": {
                "person": {
                    "type": "string",
                    "description": "Nombre de la persona. Valores válidos: pablito, tec lead, zorro, saez, her, nonides, gallo, carli, carly, pablo e, diego m, marin, gonza"
                }
            },
            "required": ["person"]
        }
    }
]

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

def process_tool_call(tool_name: str, tool_input: dict) -> str:
    if tool_name == "get_notion_notes":
        return get_notion_notes(tool_input["person"])
    return f"Tool '{tool_name}' no reconocida."

def chat(messages: list[dict]) -> str:
    """Chat sin persistencia (endpoint REST original)."""
    response = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=2048,
        system=build_system_prompt(),
        tools=TOOLS,
        messages=messages
    )
    # Procesar tool use si es necesario
    while response.stop_reason == "tool_use":
        tool_use = next(b for b in response.content if b.type == "tool_use")
        tool_result = process_tool_call(tool_use.name, tool_use.input)
        messages = messages + [
            {"role": "assistant", "content": response.content},
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": tool_use.id, "content": tool_result}]}
        ]
        response = client.messages.create(
            model="claude-opus-4-5",
            max_tokens=2048,
            system=build_system_prompt(),
            tools=TOOLS,
            messages=messages
        )
    text_block = next((b for b in response.content if hasattr(b, "text")), None)
    return text_block.text if text_block else "Sin respuesta."

def chat_with_history(chat_id: str, user_message: str) -> str:
    """Chat con historial persistido en Supabase y tool use."""
    save_message(chat_id, "user", user_message)
    messages = get_history(chat_id)

    response = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=2048,
        system=build_system_prompt(),
        tools=TOOLS,
        messages=messages
    )

    # Agentic loop para tool use
    while response.stop_reason == "tool_use":
        tool_use = next(b for b in response.content if b.type == "tool_use")
        tool_result = process_tool_call(tool_use.name, tool_use.input)

        # Serializar content para Supabase
        assistant_content = json.dumps([b.model_dump() for b in response.content], ensure_ascii=False)
        save_message(chat_id, "assistant", assistant_content)
        save_message(chat_id, "user", json.dumps([{
            "type": "tool_result",
            "tool_use_id": tool_use.id,
            "content": tool_result
        }], ensure_ascii=False))

        messages = get_history(chat_id)
        response = client.messages.create(
            model="claude-opus-4-5",
            max_tokens=2048,
            system=build_system_prompt(),
            tools=TOOLS,
            messages=messages
        )

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
