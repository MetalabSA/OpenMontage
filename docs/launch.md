# Lanzamiento — Cabina Studio

> Estado: **beta interna con GO firmado**. Build `c672f92` + fixes F10. Fecha: 2026-10-26.

## 1. Superficie publicada

| Servicio | URL | Auth |
|---|---|---|
| Studio (API + SPA) | https://studio.metalabia.com | cuenta (cookie + CSRF) o bearer token |
| Board read-only | https://board.metalabia.com | Basic Auth |
| API docs | https://studio.metalabia.com/api/docs | cuenta/token |
| Prometheus | https://studio.metalabia.com/api/metrics/prometheus | bearer viewer+ |
| Renders | `/api/projects/{slug}/media/renders/*.mp4` | cuenta/token |

Infra: EasyPanel proyecto `ollama`; volúmenes `/opt/openmontage` → `/state`; 2 vCPU / 8 GB / 100 GB.

## 2. Checklist de salida

| Ítem | Estado |
|---|---|
| Dominios + TLS (Traefik) | ✅ |
| Auth de app (cookie/CSRF/token) y roles | ✅ |
| Board protegido | ✅ |
| Backups diarios + verify | ✅ |
| Retención + alerta de disco | ✅ |
| Métricas + pantalla Ops | ✅ |
| Logs con request-id | ✅ |
| 24 tests API + 2224 suite | ✅ (3 fallos locales de FFmpeg, no productivos) |
| E2E real con MP4 45 s | ✅ |
| Documentación (uso, seguridad, backups, operación) | ✅ |
| **Webhook de alertas real** | ⏳ conectar Slack/Discord y probar (config actual: deshabilitado) |
| **Rotar claves** (EasyPanel/DeepSeek) | ⏳ manual; **contraseña admin rotada en F10** |
| **Ensayo de restore/rollback cronometrado** | ⏳ ventana de mantenimiento |
| Monitoreo externo (uptime) | ⏳ configurar en el proveedor |
| 2FA / WAF / ACL por proyecto | ❌ F9.2 |

## 3. Verificación de lanzamiento (2026-10-26)

| Check | Resultado |
|---|---|
| `GET /api/health` | ok · worker idle · disco 66,6 % (32 GB libres) |
| Board | HTTP 200 con Basic Auth |
| Proyectos | 1 (`modelo-real-2`, esperando gate de publish) |
| Usuarios | 1 admin; contraseña rotada y guardada en `.secrets/studio-api.txt` |
| Backups | 1 verificado (0,97 MB, 6 proyectos al momento); scheduler diario 03:00 UTC |
| Alertas | deshabilitadas, webhook vacío (pendiente manual) |
| Tests | 24 API · 2224 suite (3 fallos locales de FFmpeg) |
| E2E | MP4 45,056 s 1080x1920 con audio |

## 4. Criterio GO / NO-GO

**GO beta interna** si:
- ✅ health OK y SPA carga;
- ✅ un E2E produce MP4 reproducible;
- ✅ backups verificados y restore-check en verde;
- ✅ usuarios y roles funcionando.

**NO-GO público** hasta:
- rotar las claves expuestas durante el desarrollo;
- conectar alertas a un canal real;
- ejecutar un restore real y un rollback cronometrado;
- definir soporte/on-call y política de datos.

## 5. Primeros 7 días

1. Crear usuarios reales (producer/viewer) y desactivar el token estático compartido.
2. Configurar webhook de alertas y probar un job fallido.
3. Revisar Ops diariamente: costo, tasa de éxito, disco.
4. Correr retención de renders (dry-run → real) al día 30.
5. Confirmar que el backup diario de 03:00 UTC corre y verificar uno.
6. Medir 3 producciones reales y ajustar el mapa de modelos/presupuesto.

## 6. Contactos y escalado

- Operación: EasyPanel → `ollama` → logs del servicio.
- Runbooks: [operations.md](operations.md) · [backups.md](backups.md) · [security.md](security.md).
- Rollback: redeploy del build anterior en EasyPanel (<10 min) y verificar health.

**Firmado:** equipo MetaLabIA · 2026-10-26 · GO beta interna, NO-GO público hasta completar los 4 pendientes manuales.
