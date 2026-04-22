import os
import httpx

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
}

def _get_rich_text(block: dict) -> str:
    btype = block.get("type", "")
    content = block.get(btype, {})
    rich_text = content.get("rich_text", [])
    return "".join([t.get("plain_text", "") for t in rich_text])

def _fetch_children(block_id: str, client: httpx.Client, depth: int = 0, max_depth: int = 3) -> list[str]:
    """Recursivamente trae el contenido de un bloque y sus hijos."""
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
    except Exception:
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

    return lines

def get_notion_notes(person: str, max_toggles: int = 5) -> str:
    """
    Trae las notas de reuniones de una persona desde Notion.
    Lee bloques toggle recursivamente para capturar el contenido anidado.
    Limita a los últimos max_toggles toggles para no saturar el contexto.
    """
    person_key = person.lower().strip()
    page_id = NOTION_PAGES.get(person_key)

    if not page_id:
        return f"No encontré página de Notion para '{person}'."

    try:
        with httpx.Client(timeout=15) as client:
            # Traer bloques de primer nivel
            r = client.get(
                f"{NOTION_API}/blocks/{page_id}/children",
                headers=HEADERS,
                params={"page_size": 50}
            )
            r.raise_for_status()
            top_blocks = r.json().get("results", [])

            # Filtrar solo toggles (que son las entradas de reuniones)
            toggle_blocks = [b for b in top_blocks if b.get("type") == "toggle"]

            # Tomar los últimos N toggles (más recientes)
            recent_toggles = toggle_blocks[-max_toggles:]

            if not recent_toggles:
                # Si no hay toggles, leer los bloques normales
                lines = []
                for block in top_blocks[:50]:
                    text = _get_rich_text(block)
                    if text.strip():
                        lines.append(text)
                if not lines:
                    return f"La página de {person} no tiene contenido legible."
                return f"📋 Notas de {person}:\n\n" + "\n".join(lines)

            # Leer cada toggle con sus hijos
            all_lines = []
            for toggle in recent_toggles:
                title = _get_rich_text(toggle)
                all_lines.append(f"\n📅 {title}")
                if toggle.get("has_children"):
                    children_lines = _fetch_children(toggle["id"], client, depth=1)
                    all_lines.extend(children_lines)

            return f"📋 Últimas {len(recent_toggles)} reuniones con {person}:\n" + "\n".join(all_lines)

    except httpx.HTTPStatusError as e:
        return f"Error al acceder a Notion para '{person}': {e.response.status_code}"
    except Exception as e:
        return f"Error inesperado al leer Notion: {str(e)}"
