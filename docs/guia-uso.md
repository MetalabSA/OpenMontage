# Guía de uso — Cabina Studio

## 1. Accesos

| Qué | URL | Auth |
|---|---|---|
| Studio (producción) | https://studio.metalabia.com | cuenta o API token |
| Board de solo lectura | https://board.metalabia.com | Basic Auth (`cabina` / ver `.secrets/board-basic-auth.txt`) |
| API docs | https://studio.metalabia.com/api/docs | cuenta/token |

Credenciales iniciales en el servidor: `.secrets/studio-api.txt` (admin + token).
Cambiar la contraseña desde **Usuarios** o `POST /api/auth/password`.

## 2. Crear una producción

1. **Nueva producción** → título, pipeline (`animated-explainer`, `animation`, …) y plataforma.
2. El agente arranca en `research`; el board muestra el avance y los gates.
3. En cada gate: leer el artefacto, dejar una nota y **Aprobar** o **Rechazar**.
4. El chat del rail acepta comandos en lenguaje natural:
   - “hacé el guion”
   - “regenerá la escena 3 con más contraste”
   - “aprobá la propuesta”
   - “deshacé el último cambio”
5. El costo real se acumula por stage en el rail y en **Ops**.

## 3. Etapas

`idea/research → proposal → script → scene_plan → assets → edit → compose → publish`

- Las etapas con gate requieren aprobación humana.
- Los checkpoints quedan en `projects/<slug>/checkpoint_<stage>.json` y el historial en `history/`.
- Un rechazo encola una revisión con la nota.

## 4. Storyboard y escenas

- **Storyboard**: arrastrá para reordenar (se guarda en el `scene_plan`), Enter abre el editor, `←/→` navega, `Esc` cierra.
- **Regenerar** encola un job para esa escena; el resto no se toca.
- **Timeline**: pistas de video/audio/captions según los artefactos.
- **Renders**: player del MP4 final.

## 5. Settings, Ops y Usuarios

- **Settings**: mapa de modelo por stage, presupuesto, retención y claves de proveedores (solo escritura).
- **Ops**: jobs activos, tasa de éxito, costo del día, disco, tabla por stage y alertas por webhook.
- **Usuarios**: roles `admin`/`producer`/`viewer`, alta/baja y API tokens.

## 6. Costos

- El engine usa DeepSeek por defecto (Flash para etapas mecánicas, Pro para proposal/scene_plan).
- El gasto se calcula desde `usage` real, no desde estimaciones del CLI.
- Presupuesto por producción en Settings (`warn`); el rail muestra el acumulado.

## 7. Si algo falla

| Síntoma | Qué hacer |
|---|---|
| Job falla | Ver **Jobs → Log**; reintentar el stage desde el chat o el gate |
| Gate rechazado | Leer la nota y aprobar la revisión |
| Render no aparece | Revisar el job `compose`; el render tarda ~8 min por 25 s en 2 vCPU |
| No carga el studio | `/api/health`; revisar logs del servicio en EasyPanel |
| Disco alto | Settings → backups/retención; Ops muestra el porcentaje |
| Olvidé la contraseña | Admin puede resetearla desde Usuarios |

## 8. Operación

Runbooks en [operations.md](operations.md), backups/restore en [backups.md](backups.md), seguridad en [security.md](security.md).
