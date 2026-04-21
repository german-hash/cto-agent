import os
import httpx
from datetime import datetime

NOTION_TOKEN = os.environ.get("NOTION_TOKEN")
NOTION_API = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"

HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Notion-Version": NOTION_VERSION,
    "Content-Type": "application/json"
}

# Mapa de persona -> page ID
NOTION_PAGES = {
    "pablito": "027d54e4877744e38a775a0ce06e8d4c",
    "pablo c": "027d54e4877744e38a775a0ce06e8d4c",
    "tec lead": "285b7a3f36a98065bf3cd79aa55ebd89",
    "zorro": "285b7a3f36a98065bf3cd79aa55ebd89",
    "saez": "285b7a3f36a98065bf3cd79aa55ebd89",
    "her": "0759b73520e74ef8a099873182cb0b63",
    "nonides": "d15383c7362745769125e0b881c9af85",
    "gallo": "e942c31173d244b49ff0b2634665bc63",
    "carli": "26b69c7edc83498f8e734bfa8ff0bfb4",
    "carly": "26b69c7edc83498f8e734bfa8ff0bfb4",
    "pablo e": "4236b83290814a92a77ab06b494c3bc5",
    "diego m": "06c580a5496d4532afc5b315d82c0e1a",
    "marin": "06c580a5496d4532afc5b315d82c0e1a",
    "gonza": "6e048b24cbcf4b12b1cad726f31e6eca",
}

def _extract_text(block: dict) -> str:
    """Extrae texto plano de un bloque de Notion."""
    btype = block.get("type", "")
    content = block.get(btype, {})
    rich_text = content.get("rich_text", [])
    text = "".join([t.get("plain_text", "") for t in rich_text])

    if btype in ("bulleted_list_item", "numbered_list_item"):
        return f"• {text}"
    elif btype == "toggle":
        return f"\n📅 {text}"
    elif btype.startswith("heading"):
        return f"\n**{text}**"
    return text

def get_notion_notes(person: str, max_blocks: int = 80) -> str:
    """
    Trae las notas de reuniones de una persona desde Notion.
    Retorna texto formateado con las últimas reuniones.
    """
    person_key = person.lower().strip()
    page_id = NOTION_PAGES.get(person_key)

    if not page_id:
        return f"No encontré página de Notion para '{person}'. Personas disponibles: {', '.join(set(NOTION_PAGES.keys()))}"

    try:
        with httpx.Client() as client:
            r = client.get(
                f"{NOTION_API}/blocks/{page_id}/children",
                headers=HEADERS,
                params={"page_size": max_blocks}
            )
            r.raise_for_status()
            blocks = r.json().get("results", [])

        lines = []
        for block in blocks:
            text = _extract_text(block)
            if text.strip():
                lines.append(text)

        if not lines:
            return f"La página de {person} está vacía o no tiene contenido legible."

        return f"📋 Notas de reuniones con {person}:\n\n" + "\n".join(lines)

    except httpx.HTTPStatusError as e:
        return f"Error al acceder a Notion para '{person}': {e.response.status_code} - {e.response.text}"
    except Exception as e:
        return f"Error inesperado al leer Notion: {str(e)}"
