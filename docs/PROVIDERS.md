# Proveedores de generación — Higgsfield y KIE.AI

> Integración del 2026-10-29. Claves en EasyPanel → `openmontage-studio` → Environment
> (`HF_KEY`, `KIE_API_KEY`, `KIE_CREDIT_USD`). No se guardan en el repo.

## 1. Estado

| Capacidad | Proveedores disponibles |
|---|---|
| Video | **Higgsfield**, **KIE.AI** (antes 0) |
| Imagen | **Higgsfield**, **KIE.AI** (antes 0) |
| TTS | Piper local |
| LLM | DeepSeek |
| Stock | Pixabay music; Pexels/Unsplash sin clave |

`/providers` reporta: `image_generation 2/31`, `video_generation 2/34`.

## 2. Higgsfield

- API actual: `https://api.higgsfield.ai`
- Auth: `Authorization: Key <key:secret>` (`HF_KEY`)
- Modelos actuales (slug de aplicación, no nombre comercial):
  - `bytedance/seedance-2.5/text-to-video` (default video)
  - `bytedance/seedance-2.5/image-to-video`
  - `kling-video/v3.0/pro/text-to-video`
  - `kling-video/v4.0/text-to-video`
  - `alibaba/wan-3.0-prime/text-to-video`
  - `minimax/h3/text-to-video`
  - `lightricks/ltx-2.5/text-to-video/pro`
  - Imagen: `higgsfield-ai/soul/standard`, `higgsfield-ai/soul/v2/standard`, `bytedance/seedream/v4/text-to-image`, `ideogram/v4.0`, `recraft/v4.1/pro/text-to-image`.
- Herramientas: `higgsfield_video` (0.93), `higgsfield_image` (0.92).
- Listado completo: `GET https://api.higgsfield.ai/models` con `Authorization: Key ...`.

## 3. KIE.AI

- API: `https://api.kie.ai`
- Auth: `Authorization: Bearer <KIE_API_KEY>`
- Crear: `POST /api/v1/jobs/createTask` (`model`, `input`)
- Poll: `GET /api/v1/jobs/recordInfo?taskId=...`
- Resultado: `resultJson.resultUrls[]`; descargar en el momento (las URLs duran 14 días).
- Herramientas: `kie_video` (0.92), `kie_image` (0.90).
- Modelos probados:
  - Video: `kling/v2-5-turbo-text-to-video-pro` → 5,06 s, 1080×1920, 42 créditos (~$0,21).
  - Imagen: `gpt-image-2-text-to-image` → 1254×1254, 6 créditos (~$0,03).
- **Cualquier modelo Market de KIE** que use `createTask` se puede usar cambiando `model` y pasando campos específicos en `extra_input`; no hace falta tocar código.
- Próximo: TTS (`google/gemini-3-1-flash-tts`) y LLM (endpoints chat OpenAI-compatible por modelo; la doc advierte que no están adaptados para agentes).

## 4. Ruteo

Ambos están registrados en el capability registry. El selector usa `quality_score`, `supports`, costo y disponibilidad:

- **Hero / personaje / cine** → Higgsfield (mayor score).
- **Volumen / B-roll / imágenes** → KIE o Higgsfield; KIE suele ser más económico.
- **Fallback** → si un proveedor falla, el agente puede usar el otro o fal/Pexels.

Para forzar un proveedor/modelo, el agente puede pasar el slug en `model`; el pipeline no hardcodea proveedor.

## 5. Costos

`KIE_CREDIT_USD=0.005` es una estimación configurable. El costo real por tarea se toma de `creditsConsumed`. Higgsfield reporta créditos por modelo; `estimate_cost` usa una tabla aproximada.

## 6. Seguridad

- Las claves viven en el entorno del contenedor, no en la SPA ni en git.
- `/settings` las muestra enmascaradas (`source=env`).
- Si se cargan desde Settings, `_engine_env` las inyecta al subproceso del agente.
- Rotarlas implica actualizar el env y reiniciar el servicio.

## 7. Voz y música (KIE)

### TTS — `kie_tts`

- Modelo: `google/gemini-3-1-flash-tts`
- Salida: WAV 16-bit PCM, 24 kHz, mono.
- Voces: Zephyr, Puck, Fenrir, Kore, etc.; estilo, acento y ritmo configurables.
- Prueba real: 0,23 créditos (~$0,001) por una frase corta.
- Uso: `{"text": "...", "voice_name": "Zephyr", "accent": "Neutral", "style": "Newscaster"}`.

### Música — `kie_music` (Suno)

- Modelo: `ai-music-api/generate`; modelos Suno `V6`, `V6_MINI`, `V6_WILD`.
- Prueba real: 12 créditos (~$0,06) por una pista instrumental de 73 s (MP3 48 kHz estéreo).
- Uso: `{"prompt": "...", "style": "cinematic ambient", "instrumental": true, "model": "V6"}`.

Con esto `music_generation` pasa de 0 a 1/7 y `tts` de 1 a 2/19.

## 8. Ingesta y transcripción

- `yt-dlp` instalado en la imagen → `source_ingest 1/1`.
- `whisperx 3.8.6` + faster-whisper + torch CPU → `analysis 9/14` (ffmpeg, ffprobe, local, multi, transformers, whisperx).
- La diarización de WhisperX requiere un token de Hugging Face y aceptar los modelos de pyannote; la transcripción/aliniación funciona sin token.
- `pygments` quedó instalado como dependencia → `graphics 2/3` (Mermaid + Pygments); falta Manim.

## 9. Stock sin claves

Pexels pausó nuevas API keys, Pixabay no está emitiendo y Unsplash pide requisitos. No es bloqueante: el repo ya trae fuentes de stock sin clave (`tools/video/stock_sources/`):

- Wikimedia Commons, Internet Archive, NASA, ESA, JAXA, NOAA, NARA, Library of Congress
- Coverr, Mixkit, Videvo, Dareful, Pond5 Public Domain

Se usan vía `direct_clip_search` / `clip_acquisition`. Para imágenes generadas, Higgsfield/KIE cubren el resto.

## 10. Estado del disco

La imagen creció con WhisperX/torch (CUDA libs incluidas). Al 2026-10-29: **80 % usado, 19 GB libres**. Recomendación: mover backups/renders a R2/Supabase o ampliar el volumen; el detalle está en `backups.md`.
