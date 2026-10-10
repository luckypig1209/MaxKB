#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CONTAINER_NAME="${BIA_CONTAINER_NAME:-bia}"
WORKSPACE_ID="${BIA_WORKSPACE_ID:-default}"
REMOTE_ROOT="/tmp/bia-phase1-bootstrap"

fail() {
  echo "[BOOTSTRAP][ERROR] $*" >&2
  exit 1
}

info() {
  echo "[BOOTSTRAP][INFO] $*"
}

command -v docker >/dev/null 2>&1 || fail "docker command is unavailable."
docker inspect "${CONTAINER_NAME}" >/dev/null 2>&1 || \
  fail "Container does not exist: ${CONTAINER_NAME}"

running="$(docker inspect "${CONTAINER_NAME}" --format '{{.State.Running}}')"
[ "${running}" = "true" ] || fail "Container is not running: ${CONTAINER_NAME}"

[ -f "${SCRIPT_DIR}/bootstrap_phase1.py" ] || fail "bootstrap_phase1.py is missing."
[ -f "${SCRIPT_DIR}/phase1/PHASE1_CATALOG.json" ] || fail "PHASE1_CATALOG.json is missing."
[ -f "${SCRIPT_DIR}/phase1/PHASE1_CASES.json" ] || fail "PHASE1_CASES.json is missing."

info "Copying phase-one initialization data into ${CONTAINER_NAME}..."
docker exec "${CONTAINER_NAME}" mkdir -p "${REMOTE_ROOT}/phase1"
docker cp "${SCRIPT_DIR}/phase1/PHASE1_CATALOG.json" \
  "${CONTAINER_NAME}:${REMOTE_ROOT}/phase1/PHASE1_CATALOG.json" >/dev/null
docker cp "${SCRIPT_DIR}/phase1/PHASE1_CASES.json" \
  "${CONTAINER_NAME}:${REMOTE_ROOT}/phase1/PHASE1_CASES.json" >/dev/null

info "Initializing phase-one departments, products, bindings and cases..."
docker exec -i \
  -e "BIA_WORKSPACE_ID=${WORKSPACE_ID}" \
  -e "BIA_BOOTSTRAP_DIR=${REMOTE_ROOT}" \
  "${CONTAINER_NAME}" \
  bash -lc 'cd /opt/maxkb-app/apps && /opt/py3/bin/python manage.py shell' \
  < "${SCRIPT_DIR}/bootstrap_phase1.py"

info "Phase-one business initialization completed."
