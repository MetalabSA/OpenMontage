# Operación y observabilidad (F8)

> Estado al 2026-10-26. Servicios: `openmontage-studio` (API + SPA) y `openmontage-board` (Backlot), proyecto EasyPanel `ollama`.

## 1. Salud y métricas

| Endpoint | Quién | Qué devuelve |
|---|---|---|
| `GET /api/health` | público | estado, cola, job activo, disco, runtimes |
| `GET /api/admin/metrics` | admin | jobs por estado/stage/modelo, duración media, costos, storage, HTTP |
| `GET /api/metrics/prometheus` | viewer+ | formato Prometheus para scrape |
| `GET /api/admin/storage` | admin | disco, tamaño de proyectos y backups |
| `GET /api/audit` | admin | últimas acciones sensibles |

Scrape de Prometheus (ejemplo):

```yaml
scrape_configs:
  - job_name: cabina
    scheme: https
    authorization:
      credentials: om_<token-de-lectura>
    static_configs:
      - targets: ["studio.metalabia.com"]
    metrics_path: /api/metrics/prometheus
```

Series principales: `cabina_jobs_total{status}`, `cabina_jobs_by_stage{stage}`,
`cabina_job_duration_seconds_avg{stage}`, `cabina_cost_usd_total`, `cabina_queue_depth`,
`cabina_projects_total`, `cabina_disk_used_pct`, `cabina_http_requests_total`.

## 2. Logs

La API emite **una línea JSON por request** a stdout:

```json
{"ts":"2026-10-26T03:10:00+00:00","event":"http.request","request_id":"req_ab12","method":"POST","path":"/api/jobs","status":202,"duration_ms":42.1,"user":null}
```

- Se ven en EasyPanel → servicio → Logs.
- Cada request lleva `X-Request-ID`; el mismo id está en la respuesta y en el log.
- Los jobs persisten eventos en `job_events` (`GET /api/jobs/{id}/log`) y en `events.jsonl`.
- El agente escribe su salida en el evento `log` del job y en el resultado del mismo.

## 3. Alertas

Se configuran en **Ops → Alertas por webhook** (o `PUT /api/settings {"alerts":{...}}`):

| Campo | Default | Uso |
|---|---|---|
| `enabled` | false | activa el envío |
| `webhook_url` | — | Slack/Discord/generic HTTP POST |
| `on_job_failed` | true | alerta cuando un job falla |
| `disk_pct` | 80 | umbral de disco (máx. 1 alerta/día) |

Payload:

```json
{"source":"cabina-studio","event":"job.failed","ts":"…","payload":{"job_id":"job_…","project_id":"modelo-real-2","stage":"scene_plan","error":"agent_failed: …"}}
```

Probar con el botón **Probar** o `POST /api/admin/alerts/test`.

## 4. Runbooks

### 4.1 Rollback de deploy (< 10 min)

1. En EasyPanel → `openmontage-studio` → Deployments: elegir el deploy anterior → **Redeploy**.
2. Verificar `/api/health` y abrir `/` (SPA).
3. Si el problema está en el código nuevo, `git revert` del commit en la rama `cabina` y push (auto-deploy desactivado; redeploy manual).
4. Confirmar que los jobs en curso no se perdieron: `GET /api/jobs?status=running`; si el reinicio los cortó, quedan `failed` y se pueden relanzar.

### 4.2 Upgrade del upstream

1. `git remote add upstream https://github.com/calesthio/OpenMontage` (una vez).
2. `git fetch upstream && git merge upstream/main` en una rama `upgrade/YYYYMM`.
3. Correr `pytest tests/contracts tests/api` (≈6 min).
4. Revisar cambios en `schemas/`, `pipeline_defs/` y skills que afecten prompts.
5. Deploy y smoke: health, board, un job `research` corto.

### 4.3 Job colgado

1. `GET /api/jobs/{id}` → `progress` y `started_at`.
2. `POST /api/jobs/{id}/cancel` (mata el proceso del agente).
3. Si el job queda `running` sin proceso: reiniciar el servicio; al arrancar no se reanuda (los jobs se marcan `failed` al cortar).
4. Relanzar el stage; los checkpoints previos se conservan.

### 4.4 Disco lleno

1. `GET /api/admin/storage` → `disk_used_pct`.
2. `POST /api/admin/retention {"dry_run": true}` y luego `{"dry_run": false}`.
3. Borrar backups viejos (la retención de 7 corre sola) o descargarlos y eliminarlos.
4. Si sigue: ampliar volumen en EasyPanel o mover `projects/` a otro volumen.

### 4.5 Proveedor del modelo caído

1. Ver `job.error` (`provider_unavailable`, `upstream_timeout`, rate limit).
2. Cambiar el stage a otro modelo en Settings (mapa por stage) o proveedor en `.env` (`OM_ENGINE_PROVIDER`).
3. Reintentar el stage; el checkpoint anterior no se pierde.

### 4.6 Board caído

El board es independiente de la API: si falla, la producción sigue. Revisar `openmontage-board`, su bind a `/app/projects`, y `BACKLOT_ALLOWED_HOSTS`.

## 5. Ensayo de rollback (checklist)

- [ ] Identificar el deploy anterior en EasyPanel.
- [ ] Redeploy y medir tiempo (objetivo < 10 min).
- [ ] `/api/health` OK y SPA carga.
- [ ] `projects/` intacto (listar 3 proyectos).
- [ ] Un job de prueba termina o falla con error explícito.
- [ ] Registrar el ejercicio en la bitácora del plan.

## 6. Límites conocidos

- 2 vCPU / 8 GB: un render a la vez; la cola es FIFO.
- Sin GPU: generación local de video no disponible.
- Alertas por webhook únicamente (sin email/SMS).
- Retención de logs de requests: stdout del contenedor (rotación de EasyPanel).
