# Despliegue en VPS con EasyPanel

Runbook para correr OpenMontage en el VPS (2 vCPU / 8 GB / 100 GB) usando EasyPanel
como plataforma: TLS, dominios, proxy y básica autenticación los maneja EasyPanel.

## Arquitectura

```
Internet
   │  (HTTPS, Basic Auth)
   ▼
EasyPanel / Traefik
   ├── agent.tudominio.com  ──▶ servicio "openmontage-agent"   :3080  DSH web (chat con el agente)
   └── board.tudominio.com  ──▶ servicio "openmontage-backlot" :4750  Backlot (storyboard read-only)

Volúmenes compartidos por ambos servicios:
   /app/projects         producciones (artefactos, assets, renders)
   /app/music_library    tracks libres de regalías
   /data/piper           voces Piper (.onnx)
   /data/dsh             estado del agente (sesiones, perfiles, credenciales)
```

Una sola imagen, dos modos: `agent` (por defecto) y `backlot`. El modo se elige en
el **Run command** de cada servicio.

## 0. Antes de empezar

- EasyPanel instalado y accesible por HTTPS.
- Un dominio apuntando al VPS (o usar el dominio automático `*.easypanel.host` que
  genera EasyPanel).
- **Swap**: con 8 GB conviene agregar 4 GB. Desde la terminal del servidor:
  ```bash
  fallocate -l 4G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
  ```
- **Carpetas persistentes compartidas** (los dos servicios las montan por Bind):
  ```bash
  mkdir -p /opt/openmontage/{projects,music_library,piper,dsh}
  ```
- Crear (o reutilizar) el proyecto de EasyPanel donde se despliega. En este caso: **`ollama`**.

## 1. Fuente del código

### Opción A — Upload (sin GitHub)

Generar el ZIP desde la carpeta del proyecto (excluye lo pesado):

```bash
cd OpenMontage-main
zip -r ../openmontage-deploy.zip . \
  -x '*/node_modules/*' '.venv/*' 'projects/*' '.git/*' '*/__pycache__/*' \
     'music_library/*' '.env' '.env.*' '*.pyc' '*.mp4'
```

En cada servicio: **Source → Upload** → subir el ZIP → **Builder: Dockerfile** →
Dockerfile path: `deploy/Dockerfile`.

> El ZIP pesa ~10 MB. Cada actualización de código requiere volver a subirlo y
> redeployar (el cache de Docker hace que solo se reconstruyan las capas cambiadas).

### Opción B — GitHub

Subir el repo a GitHub y usar **Source → GitHub** con `owner/repo`, branch `main`,
build path `/`, builder **Dockerfile**, Dockerfile path `deploy/Dockerfile`.
Habilita Auto Deploy para desplegar en cada push.

## 2. Servicios

Crear **dos App services** con la misma fuente. El segundo build reutiliza el cache.

### 2.1 `openmontage-agent`

| Ajuste | Valor |
|---|---|
| Run command | `agent` |
| Docker CMD / Entrypoint | dejar el del Dockerfile (`CMD ["agent"]`) |
| Puerto interno | `3080` |
| Dominio | `agent.tudominio.com` → target port **3080** |
| HTTPS | activado (Let's Encrypt) |
| Basic Auth (Security) | **sí** — usuario/clave propios |
| Resources | CPU limit 0, RAM limit ~6144 MB |

Variables de entorno:

```env
DSH_PORT=3080
DSH_PUBLIC_URL=https://agent.tudominio.com
DSH_TRUSTED_HOST=agent.tudominio.com
PIPER_VOICES_DIR=/data/piper
DSH_HOME=/data/dsh
```

Montajes (Storage → Bind, para que ambos servicios vean los mismos archivos):

| Tipo | Host path | Mount path |
|---|---|---|
| Bind | `/opt/openmontage/projects` | `/app/projects` |
| Bind | `/opt/openmontage/music_library` | `/app/music_library` |
| Bind | `/opt/openmontage/piper` | `/data/piper` |
| Bind | `/opt/openmontage/dsh` | `/data/dsh` |
| File (opcional) | — | `/app/.env` — contenido del `.env` con las API keys |

> Se usan Bind y no Volumes a propósito: los volúmenes que crea EasyPanel están
> asociados al servicio, y Backlot necesita leer exactamente los mismos
> `projects/` que escribe el agente.

### 2.2 `openmontage-backlot`

| Ajuste | Valor |
|---|---|
| Run command | `backlot` |
| Puerto interno | `4750` |
| Dominio | `board.tudominio.com` → target port **4750** |
| Basic Auth | **sí**, la misma o distinta credencial |
| Resources | RAM limit ~1024 MB |

Variables:

```env
BACKLOT_PORT=4750
BACKLOT_HOST=0.0.0.0
BACKLOT_ALLOWED_HOSTS=board.tudominio.com
```

Montajes: **los mismos Bind paths** que el agente (`/opt/openmontage/projects`,
`/opt/openmontage/music_library`, `/opt/openmontage/piper`, `/opt/openmontage/dsh`).
No necesita `.env` ni dominio raíz.

> `BACKLOT_ALLOWED_HOSTS` es imprescindible: Backlot valida el header `Host`
> (protección anti DNS-rebinding) y sin esa variable responde `400 Bad Request`.
> El default sigue siendo loopback-only cuando la variable no está definida.

### 2.3 Motor del agente (F4)

`openmontage-studio` ejecuta cada stage con **Claude Code CLI**. La CLI ya viene en la imagen
y puede apuntar tanto a Anthropic como al endpoint compatible de DeepSeek.

| Variable | Valores | Uso |
|---|---|---|
| `OM_AGENT_MODE` | `fake` \| `claude` | `fake` escribe artefactos válidos mínimos (sin costo) para probar la orquestación; `claude` ejecuta el modelo real |
| `OM_ENGINE_PROVIDER` | `deepseek` \| `anthropic` | Proveedor del modelo |
| `OM_ENGINE_API_KEY` | clave | Requerida en modo `claude` (también puede guardarse desde Settings) |
| `OM_ENGINE_BASE_URL` | URL | Default DeepSeek: `https://api.deepseek.com/anthropic` |
| `OM_ENGINE_MODEL` | modelo | Default `deepseek-flash`; D13 usa `deepseek-v4-pro` en `proposal` y `scene_plan` vía el mapa por stage |

Sin clave configurada el modo `claude` falla con `provider_unavailable` y el job queda `failed`
con el motivo explícito. El mapa `stage → modelo` se edita en Settings (`engine.default_map`).

## 3. Primer arranque

1. Abrir `https://agent.tudominio.com` (Basic Auth de EasyPanel primero).
2. En DSH web, autenticarse con la cuenta/API key del modelo y elegir el workspace
   `/app` (OpenMontage).
3. Descargar las voces de Piper en el volumen (una sola vez). En **Shell** del
   servicio agent:
   ```bash
   python -m piper.download_voices es_AR-daniela-high en_US-lessac-medium
   mv *.onnx *.onnx.json /data/piper/
   ```
   (el comando deja los archivos en el cwd; el `mv` los deja donde la tool los busca)
4. Verificar capacidades desde la Shell:
   ```bash
   cd /app && PATH=/app/.venv/bin:$PATH python -c "
   from tools.tool_registry import registry; import json
   registry.discover(); print(json.dumps(registry.provider_menu_summary()['composition_runtimes']))
   "
   ```
5. Abrir `https://board.tudominio.com` y confirmar que carga la librería.

## 4. Verificación end-to-end

Desde el chat del agente, pedir la prueba cero-keys:

```text
Corré make demo y decime qué MP4 se generaron.
```

Después, un smoke vertical:

```bash
python -c "
from tools.tool_registry import registry
registry.discover()
t = registry.get('video_compose')
ed = {'render_runtime':'remotion','renderer_family':'explainer-data',
      'cuts':[{'id':'a','type':'hero_title','in_seconds':0,'out_seconds':3,'text':'Hola','subtitle':'VPS'}]}
r = t.execute({'operation':'remotion_render','edit_decisions':ed,
               'output_path':'projects/demo/renders/smoke.mp4','profile':'instagram_reels'})
print(r.success, r.error)"
```

Tiempo esperado en 2 vCPU: **~6-10 min por cada 20-30 s** de video 1080p.

## 5. Actualizar

- Upload: subir el ZIP nuevo → **Deploy** en ambos servicios (o **Force Rebuild**
  si cambió `requirements.txt` / `package.json`).
- GitHub: push → auto deploy.
- Las producciones viven en `/opt/openmontage/projects`, así que sobreviven a los deploys.

## 6. Operación y límites

- **Backups**: como los datos son Bind mounts, programar un backup del host
  (por ejemplo `tar`/`restic` de `/opt/openmontage` a un storage externo) y usar
  snapshots de EasyPanel como segunda capa. `dsh` guarda sesiones y credenciales:
  tratarlo como dato sensible.
- **Disco**: 100 GB. Cada producción pesa 100-500 MB; limpiar `projects/` viejos.
- **RAM**: el build de la imagen es el pico (~1.5-2 GB). En runtime, un render
  Remotion + Chrome + FFmpeg ronda 2.5-4 GB. No correr dos renders en paralelo.
- **CPU**: 2 vCPU compartidas; renders largos pueden throttlear. Para borradores,
  usar HyperFrames con `quality: draft`.
- **Sin GPU**: generación local de video no disponible; todo generativo va por API.
- **Remotion**: la imagen usa el pin 4.0.250 (por macOS 12 del autor). En Linux se
  puede subir a la última 4.x restaurando `remotion-composer/package.json.upstream.bak`
  antes del build.
- **Seguridad**: DSH web y Backlot **no tienen autenticación propia**. No exponer
  sin Basic Auth de EasyPanel. El `.env` con API keys debe ir como File storage o
  variables de entorno, nunca en la imagen ni en el ZIP.

## 7. Automatización vía MCP de EasyPanel

EasyPanel expone un MCP remoto (Streamable HTTP) en `https://PANEL/api/mcp` con
`Authorization: Bearer <API_KEY>`. Herramientas: `search_procedures`, `execute_query`,
`execute_mutation`, `execute_destructive`. Flujo típico:

1. `search_procedures` con "create app service" → devuelve el procedimiento y su schema.
2. `execute_mutation` con `projectName`, `serviceName`, `source`, `build`, `env`, `mounts`.
3. `search_procedures` "create domain" / "create middleware" para dominio y Basic Auth.
4. `execute_mutation` "deploy service" y seguir los logs con `execute_query`.

Las claves de API son secretos: rotarlas después de usarlas y no pegarlas en el chat
si se puede evitar (preferir variables de entorno o un archivo temporal).

Cliente incluido (no requiere instalar nada extra; usa `requests` del venv):

```bash
python deploy/mcp_client.py --url https://PANEL/api/mcp --token "$EASYPANEL_API_KEY" list
python deploy/mcp_client.py --url ... --token ... search "create app service"
python deploy/mcp_client.py --url ... --token ... mutate '{"procedureName":"...","input":{...}}'
```
