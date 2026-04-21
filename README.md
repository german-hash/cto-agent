# CTO Agent

Agente conversacional para gestión de rol CTO. Basado en FastAPI + Anthropic SDK.

## Estructura

```
cto-agent/
├── main.py          # FastAPI app
├── agent.py         # Lógica del agente + system prompt
├── context.json     # Memoria editable (equipo, proyectos, stakeholders)
├── requirements.txt
└── .env             # Solo para desarrollo local
```

## Setup local

```bash
pip install -r requirements.txt
cp .env.example .env  # agregar ANTHROPIC_API_KEY
uvicorn main:app --reload
```

## Deploy en Render

1. Crear nuevo **Web Service** en Render
2. Conectar el repo de GitHub
3. Configurar:
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `uvicorn main:app --host 0.0.0.0 --port $PORT`
4. Agregar variable de entorno: `ANTHROPIC_API_KEY`
5. Subir el `context.json` al repo (o usar Render Disk si querés que persista editable)

## Endpoints

| Método | Endpoint | Descripción |
|--------|----------|-------------|
| POST | `/chat` | Enviar mensaje al agente |
| DELETE | `/chat/reset` | Resetear historial de conversación |
| GET | `/context/summary` | Ver resumen del contexto cargado |
| GET | `/health` | Health check |

## Uso

```bash
# Chatear con el agente
curl -X POST https://tu-app.onrender.com/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "preparame el 1:1 con Her de esta semana"}'

# Resetear conversación
curl -X DELETE https://tu-app.onrender.com/chat/reset

# Ver contexto
curl https://tu-app.onrender.com/context/summary
```

## Actualizar el contexto

Editá `context.json` directamente y hacé push al repo. Render redeploya automáticamente.

Campos clave a mantener actualizados:
- `team[].last_1on1` → después de cada reunión
- `team[].pending_topics` → temas que querés tratar
- `team[].notes` → novedades del equipo
- `okrs_q2_2026[].features[].status` → avance del roadmap
- `open_decisions` → ADRs pendientes
- `next_events` → reuniones importantes próximas
