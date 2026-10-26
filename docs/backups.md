# Backups, restore y retención (F7)

> Estado al 2026-10-26. Datos en `/opt/openmontage` (bind mount del contenedor en `/state`).

## 1. Qué se respalda

| Contenido | Ruta | Incluido |
|---|---|---|
| Producciones (artefactos, assets, renders, checkpoints) | `/opt/openmontage/projects` | ✅ |
| Base de control (usuarios, jobs, settings, chat, auditoría) | `/opt/openmontage/db/cabina.db` | ✅ (snapshot consistente con `sqlite3.backup`) |
| Clave de cifrado de settings | `/opt/openmontage/db/secret.key` | ✅ (**sensible**) |
| Librería de música | `/opt/openmontage/music_library` | ✅ si existe |
| Voces Piper (170 MB) | `/opt/openmontage/piper` | ❌ por defecto (`OM_BACKUP_INCLUDE_VOICES=1` para incluir) |
| Eventos SSE (`events.jsonl`) | `/opt/openmontage/db/events.jsonl` | ❌ (reconstruible; no crítico) |

Formato: `cabina-YYYYmmdd-HHMMSS.tar.gz` + sidecar `.json` con tamaño, SHA-256, fecha y cantidad de proyectos. Destino: `/opt/openmontage/backups` (`OM_BACKUPS_DIR`).

## 2. Programación

- Tarea interna de la API: revisa cada 10 min y crea **un backup diario** a las **03:00 UTC** si `settings.backup.enabled` es true.
- Retención de backups: `settings.backup.keep` (default **7**); los más viejos se eliminan con su metadata y quedan auditados.
- Manual: botón **Crear backup ahora** en Settings o `POST /api/admin/backups`.
- Segunda capa recomendada: snapshot del VPS / backup del volumen desde EasyPanel.

## 3. Verificación (restore check)

`POST /api/admin/backups/{name}/verify` (admin) extrae el tar en un directorio temporal y valida:

1. `manifest.json` presente y legible.
2. `PRAGMA integrity_check` de la DB restaurada.
3. Cada `project.json` parseable.
4. Conteo de checkpoints por proyecto.

Devuelve `valid: true/false` + checks. **No toca** los datos vivos. También se puede descargar el tar y verificarlo con `sha256sum` contra el sidecar.

## 4. Restore completo (runbook)

1. Verificar el backup desde la UI/API (`verify`) y descargarlo.
2. En el servidor, detener `openmontage-studio` (EasyPanel → Stop) para evitar escrituras.
3. Extraer en un directorio nuevo:
   ```bash
   mkdir -p /opt/openmontage-restore
   tar -xzf cabina-YYYYmmdd-HHMMSS.tar.gz -C /opt/openmontage-restore
   ```
4. Validar: `projects/*/project.json`, `db/cabina.db` (`sqlite3 ... "PRAGMA integrity_check;"`).
5. Swap conservador:
   ```bash
   mv /opt/openmontage /opt/openmontage-old-$(date +%Y%m%d)
   mv /opt/openmontage-restore /opt/openmontage
   chown -R root:root /opt/openmontage
   ```
6. Start del servicio y smoke: `/api/health`, `/api/projects`, abrir el board.

**Restore parcial:** extraer solo `projects/<slug>` y copiarlo al volumen vivo (la DB se puede reconstruir desde los checkpoints; el board lee del filesystem).

## 5. Retención

- `settings.retention.renders_days` (default 30): elimina `projects/*/renders/*.mp4` más viejos.
- `projects_days` (default 90): reservado para archivar producciones (hoy solo se reporta).
- `POST /api/admin/retention {"dry_run": true}` simula y devuelve candidatos + bytes liberados.
- La ejecución real (`dry_run: false`) se hace desde API/CLI con confirmación; queda auditada.

## 6. Alerta de disco

- `GET /api/health` y `GET /api/admin/storage` exponen `disk_used_pct`, `disk_free_gb` y `disk_warning`.
- Umbral `OM_DISK_WARN_PCT` (default 80). La UI de Settings muestra el estado y sugiere retención.
- Con 100 GB de VPS y producciones de 100-500 MB, el riesgo real es acumulación de renders: la retención debe correr mensualmente.

## 7. Migración SQLite → Postgres (V1)

Cuando haya más de un worker o varios usuarios concurrentes:

1. Congelar escrituras (modo mantenimiento) y crear un backup verificado.
2. Crear Postgres en EasyPanel y las tablas equivalentes (`users`, `sessions`, `api_tokens`, `projects`, `jobs`, `job_events`, `settings`, `audit_log`, `chat_threads`, `chat_messages`, `scene_versions`).
3. Exportar con `sqlite3 cabina.db .dump` o un script fila por fila; preservar IDs (TEXT) y timestamps ISO.
4. Cambiar `OM_DB_PATH` por `OM_DATABASE_URL` en una capa de repositorio (hoy `api/db.py` es el único punto de acceso).
5. Prueba de paridad: contar filas por tabla y correr la suite de 23 tests contra Postgres.
6. Rollback: conservar la DB SQLite y el backup hasta 7 días.

El filesystem (`projects/`) no se migra: sigue siendo la fuente de verdad creativa.

## 8. Checklist F7

- [x] Backup manual + programado con retención.
- [x] Snapshot consistente de SQLite y de la clave de cifrado.
- [x] Verificación de restore (integridad de DB + proyectos + checkpoints).
- [x] Retención de renders con simulación previa.
- [x] Alerta de disco en health/storage/UI.
- [x] Runbook de restore y plan de migración a Postgres.
- [ ] Prueba de restore real sobre el volumen vivo (requiere ventana de mantenimiento).
- [ ] Envío de backups a storage externo (S3/R2) y cifrado con age/gpg.
