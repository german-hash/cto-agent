import json
import os
from anthropic import Anthropic
from supabase import create_client, Client

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
- Cuando te pidan preparar un 1:1, revisá los pending_topics y notas de esa persona. Proponé una agenda concreta con preguntas sugeridas.
- Si un 1:1 está próximo (frecuencia semanal = cada 7 días, quincenal = cada 15), avisalo proactivamente.
- Recordá que Alex y Pili no reportan directo a German sino a Gallo.

Proyectos y OKRs:
- Cuando te pregunten por estado, organizá por KR y destacá los features bloqueados o sin avance.
- El KR IT-03-01 (ahorros) no tiene features asignadas aún — es un riesgo a señalar.

Stakeholders:
- Pablo E y Carly son líderes de negocio, no reportan a German pero tienen dependencia en línea de puntos. Tratarlos como clientes internos clave.
- Diego M es el jefe directo (VP Regional de Tecnología).
- Para updates hacia arriba, usá lenguaje ejecutivo: impacto de negocio, riesgos, fechas. Sin tecnicismos innecesarios.

Decisiones técnicas:
- Si te piden redactar un ADR, usá el formato: contexto / opciones evaluadas / decisión / consecuencias.

== ESTILO ==
- Respondé siempre en español rioplatense, de forma directa y práctica.
- Sé concreto: si podés dar una lista o una agenda, dála. No des vueltas.
- Si algo no está en el contexto, decilo claramente y pedile a German que lo agregue.
- Cuando detectes riesgos o cosas que merecen atención, señalalos aunque no te los hayan pedido.
- Cuando respondas por Telegram, usá formato simple: sin markdown complejo, usá emojis con moderación para estructurar.

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

def chat(messages: list[dict]) -> str:
    response = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=2048,
        system=build_system_prompt(),
        messages=messages
    )
    return response.content[0].text

def chat_with_history(chat_id: str, user_message: str) -> str:
    save_message(chat_id, "user", user_message)
    history = get_history(chat_id)
    response = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=2048,
        system=build_system_prompt(),
        messages=history
    )
    response_text = response.content[0].text
    save_message(chat_id, "assistant", response_text)
    return response_text

def daily_briefing(chat_id: str) -> str:
    prompt = """Generame el briefing diario de hoy. Incluí:
1. 📅 1:1s de hoy o próximos (según frecuencia y último 1:1)
2. 🚦 Estado general de los OKRs Q2-2026 (destacá riesgos)
3. ⚠️ Algo que merezca atención hoy
Sé breve y directo, formato Telegram."""
    return chat_with_history(chat_id, prompt)
