# Seguridad — Cabina Studio (F6)

> Estado al 2026-10-26. Alcance: API + SPA en `studio.metalabia.com`.
> El board (`board.metalabia.com`) es read-only y conserva HTTP Basic Auth en el borde.

## 1. Modelo de autenticación

| Capa | Qué hace |
|---|---|
| Borde (EasyPanel) | TLS + Basic Auth solo en el board. El studio no usa Basic: la app autentica |
| Sesión web | Cookie `oms_session` HttpOnly + Secure + SameSite=Lax, expiración 12 h |
| CSRF | Toda mutación con cookie exige `X-CSRF-Token` (se emite en login/`me`) |
| API | Bearer `om_...`; se guarda el hash SHA-256, el valor crudo se muestra una sola vez |
| Contraseñas | scrypt (n=2^14, r=8, p=1) con salt por usuario |
| Roles | `admin`, `producer`, `viewer`; `admin` implica todos los permisos |

Matriz de permisos:

| Acción | viewer | producer | admin |
|---|---|---|---|
| Leer proyectos, board, artefactos, costos | ✅ | ✅ | ✅ |
| Crear proyectos/jobs, chatear, aprobar gates, regenerar, undo | ❌ | ✅ | ✅ |
| Settings, usuarios, tokens, auditoría | ❌ | ❌ | ✅ |

## 2. Secretos

- Claves de proveedores: cifradas con **Fernet** en `settings`; clave en `/state/db/secret.key` (0600).
- La API nunca devuelve la clave completa: solo `key_preview` (`sk-5…ece1`) y `source`.
- Variables de entorno siguen siendo válidas como fallback; si existe valor en DB, gana.
- La API key de EasyPanel usada para desplegar y la clave DeepSeek se rotan manualmente.

## 3. Límites y cabeceras

| Control | Valor |
|---|---|
| Login por IP | 10 intentos / 15 min |
| API general por IP | 300 req / min |
| Cabeceras | `X-Content-Type-Options`, `X-Frame-Options: DENY`, `Referrer-Policy`, `Permissions-Policy`, CSP, HSTS si `X-Forwarded-Proto=https` |
| CSP | `default-src 'self'`; scripts propios + jsdelivr (Swagger); estilos inline; media/img blob |
| Path traversal | `resolve()` + `relative_to(project)` en media y artefactos |

## 4. Auditoría

`audit_log` registra: login implícito por sesión, creación/edición/borrado de usuarios, tokens, proyectos, jobs, gates, reordenamiento de escenas, cambios de settings y undo. Se consulta en `GET /api/audit` (admin). Los eventos de job se persisten en `job_events` y `events.jsonl`.

## 5. OWASP Top 10 (estado)

| Riesgo | Estado | Nota |
|---|---|---|
| A01 Broken access control | ✅ | Roles en cada ruta + tests de 403; pendiente ACL por proyecto (equipo único) |
| A02 Fallas criptográficas | ✅ | scrypt, Fernet, TLS; rotación manual de claves |
| A03 Inyección | ✅ | SQL parametrizado, validación JSON Schema, subprocess con lista de args (sin shell) |
| A04 Diseño inseguro | ✅ | Gates, presupuesto, audit trail, undo acotado |
| A05 Mala configuración | ✅ | Headers/CSP, sin Basic en studio, rate limit; pendiente WAF/IP allowlist |
| A06 Componentes vulnerables | 🟡 | Versiones con rango; falta cadencia de actualización y auditoría `npm audit`/`pip-audit` en CI |
| A07 Fallas de autenticación | ✅ | Rate limit, sesión expirable, CSRF; pendiente 2FA |
| A08 Integridad | 🟡 | Checkpoints/audit; falta firma de imagen y verificación de procedencia |
| A09 Logging/monitoreo | 🟡 | Audit + eventos; falta alerta externa/SIEM |
| A10 SSRF | 🟡 | La API no fetcha URLs arbitrarias; las tools del agente sí tienen red (research). Mitigación: allowlist de dominios en F9 |

## 6. Checklist de F6

- [x] Login por cuenta (cookie + CSRF) y por token.
- [x] Roles y enforcement por endpoint.
- [x] CRUD de usuarios y cambio de contraseña.
- [x] API tokens (crear/listar/revocar, mostrados una vez).
- [x] Rate limiting y cabeceras de seguridad.
- [x] Auditoría consultable.
- [x] Tests: 22 verdes (incluye CSRF, roles, tokens y auditoría).
- [x] E2E en producción: login, CSRF 403/201, viewer 403, promoción, token, auditoría, logout.
- [ ] Rotar la API key de EasyPanel y la clave DeepSeek usadas durante el despliegue.
- [ ] 2FA, ACL por proyecto, WAF y alertas externas (F9).

## 7. Rotación de secretos

1. **EasyPanel:** Settings → Server → Users → regenerar API key; el MCP deja de funcionar con la vieja.
2. **DeepSeek:** platform.deepseek.com → API keys → crear nueva y revocar la anterior; luego
   `PUT /api/settings` con la nueva (admin) o actualizar `OM_ENGINE_API_KEY` y redeploy.
3. **Admin de la app:** `PATCH /api/users/{id}` con `password` nueva (invalida sesiones).
4. **Tokens de API:** revocar en `#/users` y generar uno nuevo.
