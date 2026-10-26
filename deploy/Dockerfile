# OpenMontage on a Linux server (EasyPanel / Docker).
#
# One image, two service modes (ENTRYPOINT arg):
#   agent    -> DSH web UI on :3080  (chat with the agent, runs the pipelines)
#   backlot  -> Backlot board on :4750 (read-only live storyboard)
#
# Build context: the repository root. Heavy/generated directories are excluded
# by .dockerignore.

FROM python:3.12-bookworm

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_NO_CACHE_DIR=1 \
    PYTHONUNBUFFERED=1 \
    NODE_MAJOR=22 \
    PIPER_VOICES_DIR=/data/piper \
    DSH_HOME=/data/dsh \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

# --- System packages -------------------------------------------------------
# ffmpeg from Debian ships with libass/freetype, so SRT burn-in and drawtext work
# (the macOS Homebrew build we used locally does not).
# The lib* packages are the shared libraries Chrome Headless Shell needs:
# https://www.remotion.dev/docs/miscellaneous/linux-dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
      ffmpeg \
      git \
      curl \
      ca-certificates \
      xz-utils \
      unzip \
      tini \
      procps \
      fonts-liberation \
      fonts-noto-color-emoji \
      fontconfig \
      libnss3 \
      libdbus-1-3 \
      libatk1.0-0 \
      libatk-bridge2.0-0 \
      libcups2 \
      libdrm2 \
      libgbm1 \
      libasound2 \
      libxcomposite1 \
      libxdamage1 \
      libxfixes3 \
      libxrandr2 \
      libxkbcommon0 \
      libpango-1.0-0 \
      libcairo2 \
      libx11-xcb1 \
      libxcb1 \
      libxss1 \
    && rm -rf /var/lib/apt/lists/*

# --- Node.js 22 (HyperFrames floor) ---------------------------------------
RUN curl -fsSL "https://deb.nodesource.com/setup_${NODE_MAJOR}.x" | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

# --- Google Chrome (HyperFrames + Remotion browser checks) ----------------
RUN curl -fsSL -o /tmp/chrome.deb \
      https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb \
    && apt-get update \
    && apt-get install -y --no-install-recommends /tmp/chrome.deb \
    && rm -f /tmp/chrome.deb \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# --- Python tools ----------------------------------------------------------
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt piper-tts

# --- Application -----------------------------------------------------------
COPY . .
RUN chmod +x deploy/entrypoint.sh \
    && ln -sf /app/deploy/entrypoint.sh /usr/local/bin/openmontage-entrypoint

# --- Cabina Studio SPA (served by the API at /) ---------------------------
RUN cd web && npm install --no-audit --no-fund && npm run build && npm cache clean --force

# --- Remotion composition engine ------------------------------------------
# Installs the versions declared in remotion-composer/package.json (upstream 4.x).
# The macOS-only 4.0.250 pin used during local development is NOT applied here:
# on Linux the current 4.x compositor is the supported target.
RUN cd remotion-composer \
    && npm install --no-audit --no-fund \
    && node -e "require('@remotion/renderer').ensureBrowser().then(() => console.log('chrome-headless-shell ready'))" \
    && npm cache clean --force

# --- Agent harness + HyperFrames warm cache -------------------------------
# Claude Code CLI is the harness (D8) and can point at either Anthropic or
# DeepSeek's Anthropic-compatible endpoint. DSH stays available as a fallback.
RUN npm install -g @anthropic-ai/claude-code @deepseek-ai/dsh@0.2.1-rc.2 pnpm \
    && npx --yes hyperframes --version >/dev/null 2>&1 || true

RUN mkdir -p /app/projects /app/music_library /data/piper /data/dsh

EXPOSE 3080 4750

ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/openmontage-entrypoint"]
CMD ["agent"]
