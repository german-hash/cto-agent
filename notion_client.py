import os
import httpx
import logging

logger = logging.getLogger(__name__)

NOTION_TOKEN = os.environ.get("NOTION_TOKEN")
NOTION_API = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"

HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Notion-Version": NOTION_VERSION,
    "Content-Type": "application/json"
}

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
    "reunion dce": "bdaf76e99dc5438cb65bb951958a7e83",
    "dce": "bdaf76e99dc5438cb65bb951958a7e83",
}

def _get_rich_text(block: dict) -> str:
    btype = block.get("type", "")
    content = block.get(btype, {})
    rich_text = content.get("rich_text", [])
    return "".join([t.get("plain_text", "") for t in rich_text])

def _fetch_children(block_id: str, client: httpx.Client, depth: int = 0, max_depth: int = 4) -> list[str]:
    if depth > max_depth:
        return []
    lines = []
    try:
        r = client.get(
            f"{NOTION_API}/blocks/{block_id}/children",
            headers=HEADERS,
            params={"page_size": 100}
        )
        r.raise_for_status()
        blocks = r.json().get("results", [])
    except Exception as e:
        logger.error(f"Error fetching children of {block_id}: {e}")
        return []

    indent = "  " * depth
    for block in blocks:
        btype = block.get("type", "")
        text = _get_rich_text(block)
        has_children = block.get("has_children", False)

        if btype == "toggle":
            if text:
                lines.append(f"\n{indent}📅 {text}")
            if has_children:
                lines.extend(_fetch_children(block["id"], client, depth + 1, max_depth))
        elif btype in ("bulleted_list_item", "numbered_list_item"):
            if text:
                lines.append(f"{indent}• {text}")
            if has_children:
                lines.extend(_fetch_children(block["id"], client, depth + 1, max_depth))
        elif btype.startswith("heading"):
            if text:
                lines.append(f"\n{indent}**{text}**")
        elif btype == "paragraph":
            if text:
                lines.append(f"{indent}{text}")
            if has_children:
                lines.extend(_fetch_children(block["id"], client, depth + 1, max_depth))
        elif btype == "quote":
            if text:
                lines.append(f"{indent}> {text}")
        elif btype == "child_page":
            title = block.get("child_page", {}).get("title", "")
            if title:
                lines.append(f"\n{indent}📄 {title}")
                if has_children:
                    lines.extend(_fetch_children(block["id"], client, depth + 1, max_depth))

    return lines

def get_notion_notes(person: str, max_toggles: int = 5) -> str:
    person_key = person.lower().strip()
    page_id = NOTION_PAGES.get(person_key)

    if not page_id:
        return f"No encontré página de Notion para '{person}'."

    try:
        with httpx.Client(timeout=20) as client:
            r = client.get(
                f"{NOTION_API}/blocks/{page_id}/children",
                headers=HEADERS,
                params={"page_size": 50}
            )
            r.raise_for_status()
            top_blocks = r.json().get("results", [])

            # DEBUG: loguear tipos de bloques
            block_summary = [(b.get("type"), _get_rich_text(b)[:50], b.get("has_children")) for b in top_blocks]
            logger.info(f"Notion blocks for {person}: {block_summary}")

            all_lines = []
            toggle_count = 0

            for block in top_blocks:
                btype = block.get("type", "")
                text = _get_rich_text(block)
                has_children = block.get("has_children", False)

                if btype == "toggle":
                    if toggle_count >= max_toggles:
                        continue
                    toggle_count += 1
                    all_lines.append(f"\n📅 {text}")
                    if has_children:
                        all_lines.extend(_fetch_children(block["id"], client, depth=1))

                elif btype == "child_page":
                    # Algunas páginas usan child_pages en lugar de toggles
                    if toggle_count >= max_toggles:
                        continue
                    toggle_count += 1
                    title = block.get("child_page", {}).get("title", text)
                    all_lines.append(f"\n📄 {title}")
                    if has_children:
                        all_lines.extend(_fetch_children(block["id"], client, depth=1))

                else:
                    # Bloques normales (headings, paragraphs, bullets)
                    if text.strip():
                        all_lines.append(text)
                    if has_children:
                        all_lines.extend(_fetch_children(block["id"], client, depth=1))

            if not all_lines:
                return f"La página de {person} no tiene contenido legible."

            return f"📋 Notas de reuniones con {person}:\n" + "\n".join(all_lines)

    except httpx.HTTPStatusError as e:
        return f"Error al acceder a Notion para '{person}': {e.response.status_code} - {e.response.text}"
    except Exception as e:
        return f"Error inesperado al leer Notion: {str(e)}"

# Page ID para tareas
TAREAS_PAGE_ID = "34bb7a3f36a98017996de0cceeefb82f"

def add_note_to_person(person: str, topics: list[str], author: str = "yo") -> str:
    """
    Agrega una entrada de reunión a la página de una persona en Notion.
    Formato: toggle con fecha → heading con autor → bullets con temas.
    """
    person_key = person.lower().strip()
    page_id = NOTION_PAGES.get(person_key)

    if not page_id:
        return f"No encontré página de Notion para '{person}'."

    from datetime import datetime
    today = datetime.now().strftime("%-d de %B de %Y")

    # Armar children: heading + bullets
    children = [
        {
            "object": "block",
            "type": "heading_3",
            "heading_3": {
                "rich_text": [{"type": "text", "text": {"content": author}}]
            }
        }
    ]
    for topic in topics:
        if topic.strip():
            children.append({
                "object": "block",
                "type": "bulleted_list_item",
                "bulleted_list_item": {
                    "rich_text": [{"type": "text", "text": {"content": topic.strip()}}]
                }
            })

    blocks = [
        {
            "object": "block",
            "type": "toggle",
            "toggle": {
                "rich_text": [{"type": "text", "text": {"content": f"@{today}"}}],
                "children": children
            }
        }
    ]

    try:
        with httpx.Client(timeout=15) as client:
            r = client.patch(
                f"{NOTION_API}/blocks/{page_id}/children",
                headers=HEADERS,
                json={"children": blocks}
            )
            r.raise_for_status()
        topics_str = "\n".join([f"• {t}" for t in topics])
        return f"✅ Reunión registrada en la página de {person} ({today}):\n{topics_str}"
    except Exception as e:
        return f"Error al escribir en Notion: {str(e)}"

def add_task(task: str, person: str = "") -> str:
    """Agrega una tarea a la página de Tareas CTO Agent."""
    from datetime import datetime
    today = datetime.now().strftime("%d/%m/%Y")

    text = f"[{today}] {task}"
    if person:
        text += f" — {person}"

    blocks = [
        {
            "object": "block",
            "type": "to_do",
            "to_do": {
                "rich_text": [{"type": "text", "text": {"content": text}}],
                "checked": False
            }
        }
    ]

    try:
        with httpx.Client(timeout=15) as client:
            r = client.patch(
                f"{NOTION_API}/blocks/{TAREAS_PAGE_ID}/children",
                headers=HEADERS,
                json={"children": blocks}
            )
            r.raise_for_status()
        return f"✅ Tarea agregada: {text}"
    except Exception as e:
        return f"Error al escribir tarea en Notion: {str(e)}"


def get_tasks() -> str:
    """Lee las tareas pendientes de la página Tareas CTO Agent."""
    try:
        with httpx.Client(timeout=15) as client:
            lines = _fetch_children(TAREAS_PAGE_ID, client, depth=0)
        if not lines:
            return "No hay tareas registradas en Tareas CTO Agent."
        return "📋 Tareas CTO Agent:\n" + "\n".join(lines)
    except Exception as e:
        return f"Error al leer tareas: {str(e)}"
