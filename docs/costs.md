# Costos — primera producción real y proyección

> Base: E2E `modelo-real-2` (45 s, 10 escenas, 6 narraciones Piper) del 2026-10-26.
> Precios DeepSeek vigentes: Flash $0,15 / $0,60 por 1M (input miss/output); Pro $0,66 / $1,98.

## 1. Costo real por etapa

| Etapa | Modelo | Costo |
|---|---|---|
| research | flash | $0,0000 (primera corrida; la estimación histórica $5,16 no es gasto real) |
| proposal | v4-pro | $0,0896 |
| script | flash | $0,0277 |
| scene_plan | v4-pro | $0,1667 |
| assets | flash | $0,0467 |
| edit | flash | $0,0480 |
| compose | flash | $0,0949 |
| publish | flash | $0,0000 |
| **Total incremental** | | **$0,4736** |

Con un 20 % de reintentos/overhead: **≈ $0,57 por video de 45 s**.

## 2. Proyección mensual

| Videos/mes | Costo modelo (×$0,57) | VPS (estimado) | Total aprox. |
|---|---|---|---|
| 8 | $4,6 | $12 | $16,6 |
| 20 | $11,4 | $12 | $23,4 |
| 40 | $22,8 | $12 | $34,8 |
| 80 | $45,6 | $12 + storage | $58+ |

El render no tiene costo de API: Remotion/FFmpeg corren en el VPS. El gasto variable es el agente (DeepSeek) y, si se habilitan, proveedores de imagen/video/música.

## 3. Dónde se va el costo

- `scene_plan` y `proposal` (Pro) concentran ~54 % del costo del video.
- `compose`/`edit` (Flash) son baratos pero consumen tiempo de CPU (10 min de render por 45 s).
- Los reintentos por gates rechazados duplican el stage; el presupuesto por proyecto debe incluirlos.

## 4. Controles

- Presupuesto por producción en Settings (modo `warn`).
- Medidor de gasto en el rail y en Ops (`cost.today_usd`, `cost.total_usd`).
- Alertas de costo recomendadas (roadmap): webhook si el gasto diario supera $X.
- Revisión mensual: `GET /api/admin/metrics` → `by_stage` + `by_model`.

## 5. Riesgos de costo

| Riesgo | Mitigación |
|---|---|
| Job colgado consumiendo tokens | `--max-turns 30` + timeout 20 min + cancel |
| Gate rechazado en loop | límite de revisiones y nota obligatoria |
| Proveedores de imagen/video | presupuesto por proyecto y allowlist |
| Picos de precio DeepSeek | mapa de modelos por stage y fallback a Flash |
