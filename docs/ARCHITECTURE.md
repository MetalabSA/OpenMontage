# Arquitectura — Cabina Studio sobre OpenMontage

## 1. Vista general

```
Navegador (SPA React)
   │ HTTPS / SSE
Traefik (EasyPanel) ── studio.metalabia.com
   │
FastAPI (uvicorn :3080) ── SQLite + filesystem /state
   │  jobs (cola, 1 worker)
   ├── Claude Code CLI ── DeepSeek API (Flash/Pro por stage)
   ├── Remotion (composiciones) ── Chrome headless
   ├── FFmpeg (mux, audio, render)
   └── Piper (TTS local)

Board read-only (Backlot :4750) ── board.metalabia.com
```

El proyecto es **agent-first**: no hay orquestador Python que “decida”. La API encola un stage, arma un prompt con el YAML del pipeline + skills del director y lanza el CLI del agente; el agente usa herramientas (Python) y escribe artefactos/checkpoints canónicos. La API solo persiste, valida, expone y aplica gates.

## 2. Componentes

| Componente | Código | Rol |
|---|---|---|
| SPA | `web/` (Vite + React + TS) | Biblioteca, workspace 3 columnas, storyboard, chat, Ops, usuarios |
| API | `api/` (FastAPI) | Auth, proyectos, jobs, gates, chat, settings, backups, métricas |
| Agente | `api/agents.py` | Prompt por stage, Claude Code CLI, costo real desde `usage` |
| Cola | `api/services/jobs.py` | FIFO, un job activo por proyecto, auto-chain, cancel |
| Board | `backlot/` | Estado read-only para el board y la API |
| Artefactos | `schemas/`, `lib/checkpoint.py` | Validación JSON Schema y checkpoints versionados |
| Tools | `tools/`, `skills/` | Generación, TTS, Remotion, FFmpeg, publicación |
| Storage | `/state` | `projects/`, `db/`, `music_library/`, `backups/`, `piper/` |

## 3. Flujo de un job

1. `POST /api/jobs` valida rol/proyecto/stage y encola.
2. El worker toma el job, marca `running` y publica evento SSE.
3. `agents.py` construye el prompt: pipeline YAML, skills del director, artefactos previos, guardrails (presupuesto, max turns).
4. Se ejecuta `claude` (DeepSeek vía `ANTHROPIC_BASE_URL`) con `--model` del stage y `--max-turns 30`.
5. El agente usa tools; escribe `artifacts/<stage>.json` y `checkpoint_<stage>.json`.
6. El watcher detecta cambios y emite eventos; la API refresca el board.
7. Si el stage tiene gate, el checkpoint queda `awaiting_human`; si no, se encadena el siguiente.
8. Al aprobar, `gates.py` escribe `human_approved` y encola el siguiente stage.

## 4. Datos

- **SQLite** (`/state/db/cabina.db`): usuarios, sesiones, tokens, proyectos, jobs, eventos, settings, auditoría, chat.
- **Filesystem** (`/state/projects/<slug>`): fuente de verdad creativa (artefactos, assets, renders, checkpoints, historial).
- **Secretos**: claves de proveedores cifradas con Fernet en `settings`; `db/secret.key` 0600.
- **Backups**: tar.gz con snapshot SQLite + proyectos + secret.key; verificación de restore.

## 5. Decisiones clave

| ID | Decisión |
|---|---|
| D1 | Un solo contenedor con tres roles (`agent`, `api`, `board`) |
| D2 | SPA propia (“Cabina Studio”) en vez de Backlot como UI principal |
| D3 | Un worker y cola FIFO por límite de 2 vCPU |
| D13 | Engine híbrido por stage: Flash default, Pro para proposal/scene_plan |
| D14 | Claude Code CLI como runtime del agente, DeepSeek como modelo |
| D15 | Board separado y read-only con Basic Auth |

## 6. Dónde extender

- **Nuevo pipeline:** `pipeline_defs/<name>.yaml` + skills en `skills/pipelines/<name>/`.
- **Nueva tool:** `tools/<name>.py` + registro en `tools/tool_registry.py` + skill.
- **Nuevo modelo/proveedor:** `api/config.py` + `DEEPSEEK_PRICES`/`_engine_env` + Settings.
- **Nueva pantalla:** `web/src/App.tsx` (hash route) + endpoint en `api/routes.py`.

## 7. Límites conocidos

- 2 vCPU: un render a la vez; 45 s de video ≈ 10 min de compose.
- Sin GPU: generación de video local no disponible; se usan Remotion/composiciones.
- SQLite: válido para un worker; migrar a Postgres si hay varios workers.
- El agente tiene acceso a red (research); allowlist de dominios pendiente.
