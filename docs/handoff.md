# Handoff — Cabina Studio / MetaLabIA

> Fecha: 2026-10-26 · Build `c672f92` + fixes F10 · Responsable: equipo MetaLabIA.

## 1. Inventario

| Qué | Dónde |
|---|---|
| Studio | https://studio.metalabia.com |
| Board | https://board.metalabia.com (Basic Auth) |
| API docs | https://studio.metalabia.com/api/docs |
| EasyPanel | proyecto `ollama`, servicios `openmontage-studio` y `openmontage-board` |
| Servidor | Hostinger VPS 2 vCPU / 8 GB / 100 GB, IP `69.62.100.243` |
| Datos | `/opt/openmontage` → `/state` (projects, db, backups, music_library, piper) |
| Repo | https://github.com/MetalabSA/OpenMontage, rama `cabina` |
| Secretos locales | `.secrets/studio-api.txt`, `.secrets/board-basic-auth.txt` (no commitear) |

## 2. Accesos

- **Cuenta admin:** `admin@metalabia.com`; contraseña en `.secrets/studio-api.txt` (rotada en F10).
- **API token:** en el mismo archivo. Se usa como `Authorization: Bearer om_...`.
- **Board:** usuario `cabina`, password en `.secrets/board-basic-auth.txt`.
- **EasyPanel MCP:** URL `http://69.62.100.243:3000/api/mcp` + API key (rotar antes de compartir).

## 3. Operación diaria

```bash
# salud
curl -s https://studio.metalabia.com/api/health | jq

# métricas
curl -s -H "Authorization: Bearer $TOKEN" \
  https://studio.metalabia.com/api/admin/metrics | jq

# backup manual + verificación
curl -s -X POST -H "Authorization: Bearer $TOKEN" \
  https://studio.metalabia.com/api/admin/backups | jq
curl -s -X POST -H "Authorization: Bearer $TOKEN" \
  https://studio.metalabia.com/api/admin/backups/<name>/verify | jq

# E2E de un proyecto
OM_API_TOKEN=... python scripts/qa_e2e.py --slug <slug>
```

- Logs: EasyPanel → `openmontage-studio` → Logs (JSON por request con `request_id`).
- Reinicio: EasyPanel → Restart (los jobs en curso quedan `failed` y se relanzan).
- Deploy: push a `cabina` + EasyPanel → Deploy (o MCP `deployAppService`).

## 4. Pendientes de lanzamiento (manuales)

| Ítem | Responsable | Cómo |
|---|---|---|
| Rotar API key EasyPanel | Leo | Settings → API keys → regenerar; actualizar MCP |
| Rotar clave DeepSeek | Leo | platform.deepseek.com → nueva key; `PUT /api/settings` o env + redeploy |
| Webhook de alertas real | Leo | Ops → alertas → URL Slack/Discord → Probar |
| Restore real | Leo | ventana de mantenimiento; runbook `backups.md` §4 |
| Rollback cronometrado | Leo | runbook `operations.md` §4.1 |
| Uptime externo | Leo | Better Stack/UptimeRobot → `/api/health` |
| E2E animation/cinematic | equipo | `scripts/qa_e2e.py` con proyectos de prueba |

## 5. Incidentes frecuentes

| Síntoma | Primer chequeo | Acción |
|---|---|---|
| 502/504 en studio | EasyPanel logs, `/api/health` | restart; si persiste, rollback |
| Jobs trabados | `GET /jobs?status=running` | cancelar y relanzar; revisar log |
| Disco > 80% | `/api/admin/storage` | retención real o ampliar volumen |
| Costo alto | `/api/admin/metrics` | ajustar mapa de modelos/presupuesto |
| Board 400 | `BACKLOT_ALLOWED_HOSTS` | agregar dominio y redeploy |
| Login falla | rate limit (10/15 min) | esperar o reiniciar API |

## 6. Propiedad y continuidad

- Código y docs en el repo; rama `cabina` es la de producción.
- Los datos viven en el VPS; backup diario + retención 7.
- Si se pierde el VPS: crear uno nuevo, clonar repo, montar volumen desde backup, `docker build`, deploy, verify.
