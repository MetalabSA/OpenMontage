# Contrato de API v1 — Cabina Studio

> **Estado:** congelado para F3. Fuente de verdad machine-readable: [`openapi.json`](openapi.json).
> **Base URL:** `https://studio.metalabia.com/api` · **Versión:** `1.0.0` · **Última actualización:** 2026-10-25

Este documento define el contrato entre el front (SPA) y el backend (FastAPI) de Cabina Studio
sobre el motor de OpenMontage. El backend **no reimplementa** la lógica creativa: gestiona
proyectos, cola de jobs, gates, artefactos y costos, y delega cada stage al agente.

---

## 1. Convenciones

| Tema | Regla |
|---|---|
| Formato | JSON UTF-8 (`application/json`), excepto media (`application/octet-stream`) y SSE (`text/event-stream`) |
| Fechas | ISO 8601 en **UTC** con sufijo `Z` (`2026-10-25T22:05:32Z`) |
| IDs | Strings opacos; prefijos por tipo: `prj_`, `job_`, `msg_`, `evt_`, `ast_`, `rnd_` |
| Nombres | `snake_case` en JSON; `kebab-case` en slugs |
| Dinero | USD como número decimal (`0.0432`), nunca string |
| Nulos | Los campos opcionales se omiten o van en `null`, nunca como `""` |
| Tamaño | Requests ≤ 1 MB; uploads van por multipart en un endpoint aparte (F6) |
| Compatibilidad | Cambios aditivos dentro de `/api`; breaking → `/api/v2` |

### Errores

Todas las respuestas de error usan el mismo sobre:

```json
{
  "error": {
    "code": "gate_not_pending",
    "message": "Stage 'script' is not awaiting human approval",
    "details": { "stage": "script", "status": "completed" },
    "request_id": "req_01J9..."
  }
}
```

| HTTP | Códigos |
|---|---|
| 400 | `invalid_request`, `invalid_cursor`, `invalid_scope` |
| 401 | `unauthorized`, `session_expired`, `invalid_token` |
| 403 | `forbidden`, `role_required`, `path_escapes_project` |
| 404 | `not_found`, `project_not_found`, `job_not_found`, `artifact_not_found`, `scene_not_found` |
| 409 | `slug_exists`, `job_already_running`, `gate_not_pending`, `already_approved`, `cannot_undo_approved` |
| 422 | `validation_failed`, `artifact_invalid`, `unsupported_stage`, `missing_reason` |
| 429 | `rate_limited` (incluye `Retry-After`) |
| 500 | `internal_error` |
| 502/504 | `provider_unavailable`, `upstream_timeout` |

### Paginación

Listados por cursor: `?limit=20&cursor=<opaque>`. Respuesta:

```json
{ "data": [ ... ], "next_cursor": "eyJpZCI6..." }
```

`next_cursor: null` indica fin. El cursor es opaco; el cliente no debe interpretarlo.

### Idempotencia

`POST /api/projects`, `POST /api/jobs` y `POST /api/projects/{slug}/chat` aceptan
`Idempotency-Key` (8–128 chars). Repetir la misma key devuelve el recurso original con
`200`/`202` y el header `Idempotent-Replayed: true`. Las keys se guardan 24 h.

### Rate limits

| Scope | Límite |
|---|---|
| Lecturas por token | 120 req/min |
| Jobs por proyecto | 10/hora |
| Mensajes de chat | 30/min |
| Logins fallidos por IP | 10/15 min |

Headers: `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset` (epoch).

---

## 2. Autenticación y roles

Hay **dos capas**:

1. **Borde (EasyPanel):** HTTP Basic Auth en el dominio. No es la autenticación de la app,
   solo la primera barrera.
2. **Aplicación:**
   - **Cookie de sesión** `oms_session` (HttpOnly, Secure, SameSite=Lax) para la SPA.
     Con cookie, las mutaciones requieren `X-CSRF-Token` (devuelto en login y `/auth/me`).
   - **Bearer token** `Authorization: Bearer om_...` para automatización/CLI.
     Los tokens se guardan hasheados (Argon2id) y muestran solo prefijo.

| Rol | Puede |
|---|---|
| `viewer` | Leer proyectos, artefactos, assets, renders, costos. No muta nada |
| `producer` | Todo lo de viewer + crear proyectos/jobs, chatear, aprobar/rechazar gates, regenerar escenas, undo |
| `admin` | Todo lo de producer + settings, claves, usuarios, retención |

`GET /api/auth/me` devuelve el usuario y `csrf_token`. `POST /api/auth/login` crea la sesión.
`POST /api/auth/logout` la destruye.

---

## 3. Máquinas de estado

### 3.1 Job

```
             ┌──────────── cancel ────────────┐
             ▼                                │
 queued ──▶ running ──▶ awaiting_human ──▶ running ──▶ succeeded
             │                │                         │
             ├──▶ failed ◀────┘                         │
             └──▶ cancelled ◀───────────────────────────┘
```

| Estado | Significado |
|---|---|
| `queued` | En cola, aún no tomado por el worker |
| `running` | El agente está ejecutando el stage |
| `awaiting_human` | Terminó el stage y espera aprobación (solo stages con gate) |
| `succeeded` | Artefacto válido y checkpoint escrito |
| `failed` | Error no recuperable o presupuesto agotado; `error` explica |
| `cancelled` | Cancelado por el usuario o por timeout global |

Reglas:

- **Un job activo por proyecto** (`running`/`awaiting_human`). Un segundo POST devuelve
  `409 job_already_running` con el `job_id` activo en `details`.
- La cola global es FIFO; el worker procesa **de a uno** (2 vCPU).
- `POST /api/jobs/{id}/cancel` marca `cancel_requested` y envía SIGTERM; el estado pasa a
  `cancelled` cuando el proceso muere (≤ 10 s).
- Todo job registra `engine`, `model` y costo real; el modelo efectivo se agrega al
  `decision_log` del proyecto.

### 3.2 Producción (derivada de checkpoints)

| Estado | Condición |
|---|---|
| `draft` | Sin checkpoints |
| `in_progress` | Hay stages en curso o completados, sin gate pendiente |
| `awaiting_human` | Algún checkpoint con `status: awaiting_human` |
| `composing` | Stage `compose` en ejecución |
| `ready` | `render_report` válido + MP4 final presente |
| `failed` | Último checkpoint `failed` y ningún job activo |
| `archived` | Borrado lógico |

El estado **no se escribe a mano**: se deriva de `checkpoint_<stage>.json` y del filesystem.

### 3.3 Stage

`pending → in_progress → completed | awaiting_human | failed`; `skipped` solo si el pipeline
no incluye el stage. El stage es `gate: true` si el manifest tiene
`human_approval_default: true` (es binding: no se re-juzga en runtime).

---

## 4. Catálogo de endpoints (27)

| Método | Ruta | Rol | Propósito |
|---|---|---|---|
| GET | `/api/health` | público | Liveness, cola, disco, runtimes |
| POST | `/api/auth/login` | público | Crear sesión |
| POST | `/api/auth/logout` | auth | Cerrar sesión |
| GET | `/api/auth/me` | auth | Usuario + CSRF |
| GET | `/api/providers` | viewer | Menú de capacidades del registry |
| GET | `/api/pipelines` | viewer | Pipelines, stages y gates |
| GET | `/api/projects` | viewer | Listar producciones |
| POST | `/api/projects` | producer | Crear producción (`init_project`) |
| GET | `/api/projects/{slug}` | viewer | Ficha de producción |
| DELETE | `/api/projects/{slug}` | producer | Archivar (soft delete) |
| GET | `/api/projects/{slug}/board` | viewer | Estado agregado del workspace |
| GET | `/api/projects/{slug}/artifacts/{name}` | viewer | Artefacto validado (+ `raw`) |
| GET | `/api/projects/{slug}/checkpoints` | viewer | Checkpoints e historial |
| POST | `/api/projects/{slug}/gates/{stage}/approve` | producer | Aprobar gate |
| POST | `/api/projects/{slug}/gates/{stage}/reject` | producer | Rechazar con feedback |
| GET | `/api/projects/{slug}/assets` | viewer | Assets con procedencia/costo |
| GET | `/api/projects/{slug}/renders` | viewer | MP4 disponibles |
| GET | `/api/projects/{slug}/media/{path}` | viewer | Servir archivo del proyecto |
| POST | `/api/projects/{slug}/scenes/{scene}/regenerate` | producer | Regenerar una escena |
| POST | `/api/projects/{slug}/undo` | producer | Deshacer último cambio |
| GET | `/api/projects/{slug}/chat` | viewer | Historial de chat |
| POST | `/api/projects/{slug}/chat` | producer | Enviar mensaje al agente |
| GET | `/api/projects/{slug}/chat/stream` | producer | SSE de respuesta |
| GET | `/api/jobs` | viewer | Listar jobs |
| POST | `/api/jobs` | producer | Encolar job de pipeline |
| GET | `/api/jobs/{id}` | viewer | Detalle de job |
| POST | `/api/jobs/{id}/cancel` | producer | Cancelar |
| GET | `/api/jobs/{id}/events` | viewer | SSE por job |
| GET | `/api/events` | viewer | SSE global del board |
| GET | `/api/settings` | admin | Configuración (secretos enmascarados) |
| PUT | `/api/settings` | admin | Guardar configuración/claves |
| GET | `/api/costs` | viewer | Costos y presupuesto |

> Algunas rutas comparten tabla por legibilidad; el conteo exacto de operaciones está en
> `openapi.json` (27 paths).

---

## 5. SSE (Server-Sent Events)

### 5.1 Formato de stream

```
HTTP/1.1 200 OK
Content-Type: text/event-stream; charset=utf-8
Cache-Control: no-cache
Connection: keep-alive
X-Accel-Buffering: no

id: evt_01J9ABC
event: job
data: {"id":"evt_01J9ABC","type":"job","ts":"2026-10-25T22:05:32Z","project_id":"prj_...","job_id":"job_...","payload":{"status":"running","progress":{"percent":35,"message":"scene_plan"}}}

: heartbeat
```

| Regla | Valor |
|---|---|
| `id` | Monótono por proyecto; se usa con `Last-Event-ID` o `?since=` |
| `event` | Uno de los tipos de la tabla |
| `data` | JSON con el sobre `SSEEvent` |
| Heartbeat | Comentario `: heartbeat` cada 15 s para evitar timeouts del proxy |
| Reintento | `retry: 3000` al abrir |
| Historial | 24 h en `events.jsonl`; reconexión reproduce desde el último id |

### 5.2 Tipos de evento

| Tipo | Cuándo | `payload` mínimo |
|---|---|---|
| `hello` | Al abrir el stream | `{server_time, resume_from}` |
| `job` | Cambio de estado/progreso | `{status, progress, stage}` |
| `checkpoint` | Escritura de checkpoint | `{stage, status, human_approved}` |
| `artifact` | Artefacto nuevo o revisado | `{name, valid, updated_at}` |
| `asset` | Asset generado | `{asset_id, scene_id, provider, model, cost_usd}` |
| `cost` | Costo acumulado | `{spent_usd, budget_usd, reserved_usd}` |
| `log` | Línea de log del worker | `{level, line}` |
| `gate` | Gate pendiente/resuelto | `{stage, status, requested_at}` |
| `render` | Render listo | `{render_id, url, duration_seconds}` |
| `chat.delta` | Token/chunk del agente | `{message_id, delta}` |
| `chat.done` | Mensaje completo | `{message_id, actions[]}` |
| `undo` | Undo aplicado | `{kind, ref, restored_from}` |
| `error` | Error de job/stream | `{code, message}` |
| `heartbeat` | Keep-alive | `{}` (también se emite como comentario) |

---

## 6. Chat de producción

Un mensaje se interpreta como una **intención acotada** y puede derivar en un job:

```json
POST /api/projects/lanzamiento-trellis/chat
{
  "content": "Reemplazá la escena 3 con el dashboard que subí",
  "model": "deepseek-v4-pro",
  "scope": { "scene_id": "sc_03" }
}
```

Respuesta `202`:

```json
{
  "message": { "id": "msg_01...", "role": "user", "content": "Reemplazá la escena 3...", "status": "complete" },
  "job": { "id": "job_...", "status": "queued", "stage": "assets", "scene_id": "sc_03" }
}
```

Reglas:

- El backend **no inventa acciones**: si el mensaje no requiere trabajo, responde sin job.
- El agente emite `chat.delta` (streaming) y cierra con `chat.done` + `actions[]`.
- Acciones válidas: `undo`, `open_scene`, `approve`, `retry`, `open_render`. Cada acción
  incluye `payload` para ejecutarla sin ambigüedad.
- `model` por mensaje permite override de D13 (híbrido por stage).
- `attachments` referencia `asset_id` ya subidos; no se aceptan URLs externas en v1.
- Un mensaje con intención de stage completo ("hacé el guion") crea un job de ese stage.

---

## 7. Gates y Undo

### 7.1 Gates

- Aprobar solo si `checkpoint.status == awaiting_human` y el artefacto canónico valida.
- Aprobar escribe `human_approved: true` (el writer de checkpoints lo exige) y encola el
  stage siguiente.
- Rechazar exige `note` y crea un job de revisión del **mismo** stage; el checkpoint anterior
  se archiva en `history/`.
- **No se puede saltear un gate**: falta de aprobación → `409 gate_not_pending`.
- La aprobación es por gate; un "dale" general no cubre gates posteriores.

### 7.2 Undo (P11: historial completo)

- Restaura el checkpoint/artefacto/versión de escena anterior desde `history/` o
  `scene_versions`.
- Permitido solo si el stage **no está aprobado**. Si lo está → `409 cannot_undo_approved`
  (R16).
- Nunca borra historia: agrega una entrada al `audit_log` y un evento `undo`.
- Respuesta incluye `restored_from` para que el front muestre qué se recuperó.

---

## 8. Artefactos canónicos

| Stage | Artefacto | Schema |
|---|---|---|
| `research` | `research_brief` | `schemas/artifacts/research_brief.schema.json` |
| `proposal` | `proposal_packet` | `schemas/artifacts/proposal_packet.schema.json` |
| `script` | `script` | `schemas/artifacts/script.schema.json` |
| `scene_plan` | `scene_plan` | `schemas/artifacts/scene_plan.schema.json` |
| `assets` | `asset_manifest` | `schemas/artifacts/asset_manifest.schema.json` |
| `edit` | `edit_decisions` | `schemas/artifacts/edit_decisions.schema.json` |
| `compose` | `render_report` | `schemas/artifacts/render_report.schema.json` |
| `publish` | `publish_log` | `schemas/artifacts/publish_log.schema.json` |

Transversales: `brief`, `decision_log`, `cost_log`, `review`, `final_review`,
`video_analysis_brief`, `source_media_review`.

Reglas:

- `GET /artifacts/{name}` valida contra el schema y devuelve `valid: false` + `422` si no
  cumple. `?raw=true` devuelve el JSON sin metadata (para debug).
- El backend **rechaza** un job que intente escribir un artefacto inválido.
- Los campos `version` y `project_id` son obligatorios; el backend los inyecta si faltan.

---

## 9. Contrato de prompts por stage (worker)

El worker (Claude Code CLI, D8) compone cada invocación así:

| Parte | Contenido |
|---|---|
| **System** | `AGENT_GUIDE.md` (contrato) + skill del director del stage (`skills/pipelines/<pipeline>/<stage>-director.md`) + playbook de estilo + ruta del schema de salida |
| **Contexto** | Pipeline, brief, artefactos previos (JSON), plataforma/duración, `render_runtime` bloqueado, presupuesto restante |
| **Instrucción** | Texto del job o del chat, acotado al stage/escena |
| **Salida** | Escribir el artefacto canónico con las tools; registrar decisiones en `decision_log`; costos en `cost_log` |
| **Self-review** | Aplicar `skills/meta/reviewer.md`; si hay findings críticos, corregir antes de cerrar |
| **Stop** | No cambiar provider/model/runtime sin aprobación; detenerse en el gate; no salir del presupuesto |

Validación y reintentos:

1. El agente escribe el artefacto.
2. El worker valida contra el schema.
3. Si falla: **un** reintento con los errores de validación en el prompt.
4. Si vuelve a fallar: job `failed` con `artifact_invalid` y el detalle.

Mapa de modelos (D13): `research`, `script`, `assets`, `edit`, `compose`, `publish` →
`deepseek-flash`; `proposal` y `scene_plan` → `deepseek-v4-pro`; escalado manual →
`claude-sonnet-5.5`. Override por job/mensaje permitido y registrado.

Límites por job: timeout por stage (default 20 min), presupuesto (default US$2), 1 reintento
de validación, cancelación a los 10 s del pedido.

---

## 10. Settings y secretos

- `GET /api/settings` devuelve `key_preview` (`sk-…a1b2`) y `source` (`env`/`database`/`none`).
  **Nunca** devuelve la clave completa.
- `PUT /api/settings` acepta claves write-only; se cifran con AES-GCM usando `OM_SECRET_KEY`
  y no se loguean.
- El mapa `engine.default_map` (stage → modelo) se puede editar desde el front (admin).
- Cambiar una clave no requiere redeploy; el registry se recarga con TTL de 60 s.

---

## 11. Medios y URLs

- Los assets y renders se sirven por `GET /api/projects/{slug}/media/{path}` con soporte de
  `Range` (video scrubbing).
- Las rutas son relativas al proyecto; cualquier intento de salir del directorio devuelve
  `403 path_escapes_project`.
- El front usa `poster_url` para thumbnails y `url` para reproducción.

---

## 12. Versionado y deprecación

- `/api` es v1. Cambios aditivos no rompen clientes.
- Campos nuevos se agregan como opcionales; nunca se cambia el tipo de uno existente.
- Deprecación: header `Deprecation` + `Sunset` y aviso en el changelog por ≥ 2 releases.
- Breaking changes → `/api/v2` conviviendo con v1 durante 90 días.

---

## 13. Herramientas del contrato

```bash
# Validar el spec (CI)
openapi_spec_validator docs/openapi.json

# Generar tipos TypeScript para la SPA (F5)
npx openapi-typescript docs/openapi.json -o web/src/api/schema.d.ts

# Lint opcional
npx @redocly/cli lint docs/openapi.json
```

---

## 14. Criterios de aceptación de F2

- [x] `openapi.json` válido con `openapi-spec-validator` (3.1, 27 paths).
- [x] Todos los endpoints del front tienen contrato (request, response, errores).
- [x] Máquinas de estado de job, proyecto y stage documentadas.
- [x] SSE con sobre único, tipos, reconexión y heartbeat.
- [x] Gates, undo y artefactos alineados con `lib/checkpoint.py` y `schemas/`.
- [x] Contrato de prompts por stage y mapa de modelos (D13).
- [x] Settings/secretos con enmascarado y cifrado.
- [ ] Revisión cruzada con el front (se hace al construir F5).
- [ ] Generación de tipos TypeScript (se ejecuta en F5).
