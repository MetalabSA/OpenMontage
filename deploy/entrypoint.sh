#!/usr/bin/env bash
# Container entrypoint for OpenMontage.
#
#   agent    -> DSH web UI (chat with the agent inside /app)
#   backlot  -> Backlot board (read-only)
#   shell    -> interactive shell for debugging
set -euo pipefail

MODE="${1:-agent}"
APP_DIR="${APP_DIR:-/app}"

case "${MODE}" in
  agent|backlot|shell) ;;
  *)
    echo "openmontage: unknown mode '${MODE}' (expected: agent|backlot|shell)" >&2
    exit 64
    ;;
esac

# Mounted volumes are normally already present; create anything missing and keep
# going if a path is read-only (e.g. a partial local test).
mkdir -p "${APP_DIR}/projects" "${APP_DIR}/music_library" "${PIPER_VOICES_DIR:-/data/piper}" "${DSH_HOME:-/data/dsh}" 2>/dev/null || true
cd "${APP_DIR}"

# DSH rejects wildcard bind addresses, so resolve the container's own address.
resolve_bind_host() {
  if [ -z "${DSH_BIND_HOST:-}" ]; then
    DSH_BIND_HOST="$(hostname -i 2>/dev/null | awk '{print $1}')"
  fi
  if [ -z "${DSH_BIND_HOST}" ]; then
    echo "openmontage: could not resolve a bind address; set DSH_BIND_HOST explicitly" >&2
    exit 64
  fi
  printf '%s' "${DSH_BIND_HOST}"
}

case "${MODE}" in
  agent)
    bind_host="$(resolve_bind_host)"
    args=(--profile web --host "${bind_host}" --port "${DSH_PORT:-3080}" --no-open)
    [ -n "${DSH_PUBLIC_URL:-}" ] && args+=(--public-url "${DSH_PUBLIC_URL}")
    if [ -n "${DSH_TRUSTED_HOST:-}" ]; then
      # Space/comma separated list of extra accepted authorities.
      for authority in ${DSH_TRUSTED_HOST//,/ }; do
        args+=(--trusted-host "${authority}")
      done
    fi
    echo "openmontage: starting DSH web on ${bind_host}:${DSH_PORT:-3080}"
    exec dsh "${args[@]}"
    ;;
  backlot)
    export BACKLOT_HOST="${BACKLOT_HOST:-0.0.0.0}"
    echo "openmontage: starting Backlot on ${BACKLOT_HOST}:${BACKLOT_PORT:-4750}"
    exec python -m backlot serve --port "${BACKLOT_PORT:-4750}"
    ;;
  shell)
    exec bash
    ;;
esac
