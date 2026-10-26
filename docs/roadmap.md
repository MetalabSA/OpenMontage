# Roadmap — próximos 90 días

## Ahora (beta interna, 0-2 semanas)

| Prioridad | Ítem | Esfuerzo |
|---|---|---|
| P0 | Rotar claves EasyPanel/DeepSeek y token estático | 1 h |
| P0 | Webhook real de alertas + prueba de job fallido | 1 h |
| P0 | Restore real y rollback cronometrado | 2 h |
| P1 | Prueba de concurrencia (2 jobs) y reinicio mid-render | 3 h |
| P1 | E2E animation y cinematic | 1 día |
| P1 | Corregir artifacts inválidos (`decision_log`, `final_review`) | 4 h |

## 30 días

- **Auth:** 2FA TOTP para admin, ACL por proyecto, política de contraseñas.
- **Datos:** backups a S3/R2 cifrados con age; restore automatizado; migración a Postgres cuando haya 2+ workers.
- **Observabilidad:** uptime externo, Sentry para errores, dashboard Grafana con Prometheus, alertas de costo.
- **CI:** GitHub Actions con `pytest tests/api`, build de la SPA, `openapi-spec-validator` y `pip-audit`/`npm audit`.
- **Producto:** publicación real a Instagram/TikTok/YouTube (OAuth + upload), templates de pipeline, biblioteca de música.

## 60 días

- **Multi-tenant:** organizaciones, proyectos por equipo, roles granulares, cuotas.
- **Billing:** medidor de costo por cliente, planes y facturación (Stripe).
- **Escala:** worker pool, Postgres, storage S3 para assets, render en máquina con GPU opcional.
- **Calidad:** subtítulos automáticos con estilo, loudness normalization, safe-zone checker automático.

## 90 días

- **Marketplace de playbooks/estilos** y presets por industria.
- **API pública** con API keys por organización, webhooks de eventos y SDK.
- **Analytics de contenido:** performance por hook/escena, A/B de títulos.
- **Mobile/PWA** para aprobar gates y revisar renders desde el teléfono.

## KPIs

| Métrica | Objetivo beta |
|---|---|
| Tiempo idea → primer render (45 s) | < 30 min |
| Tasa de éxito de jobs | > 90% |
| Costo real por video | < $1 |
| Uptime API | > 99% |
| Gates aprobados sin cambios | > 60% |
| Restore verificado | semanal |

## Riesgos

| Riesgo | Mitigación |
|---|---|
| Dependencia de DeepSeek | fallback a Claude/OpenAI por stage |
| Costos ocultos de proveedores de imagen/video | presupuesto por proyecto + alertas |
| Un solo worker | cola visible, prioridad y cancelación |
| Deriva de upstream | rama `cabina` + tests de contrato en cada merge |
| Seguridad de secretos | rotación, cifrado, auditoría y mínimo privilegio |
