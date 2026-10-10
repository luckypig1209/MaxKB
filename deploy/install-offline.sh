#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
RELEASE_FILE="${SCRIPT_DIR}/release.env"
CHECKSUM_FILE="${SCRIPT_DIR}/SHA256SUMS"
INSTALL_ROOT="${INSTALL_ROOT:-/data/bia}"
DOCKER_BUNDLE_DIR="${DOCKER_BUNDLE_DIR:-${SCRIPT_DIR}/docker}"
DOCKER_DATA_ROOT="${DOCKER_DATA_ROOT:-/data/docker}"
DOCKER_BIN_INSTALL_DIR="/usr/local/bin"
DOCKER_COMPOSE_PLUGIN_DIR="/usr/local/lib/docker/cli-plugins"
DOCKER_SYSTEMD_UNIT="/etc/systemd/system/docker.service"
PHASE1_BOOTSTRAP_MODE="${BIA_BOOTSTRAP_PHASE1:-auto}"
PHASE1_BOOTSTRAP_SCRIPT="${SCRIPT_DIR}/bootstrap/run.sh"

fail() {
  echo "[ERROR] $*" >&2
  exit 1
}

info() {
  echo "[INFO] $*"
}

warn() {
  echo "[WARN] $*" >&2
}

run_phase1_bootstrap() {
  local status

  case "${PHASE1_BOOTSTRAP_MODE}" in
    auto|required|skip) ;;
    *) fail "BIA_BOOTSTRAP_PHASE1 must be auto, required, or skip." ;;
  esac

  if [ "${PHASE1_BOOTSTRAP_MODE}" = "skip" ]; then
    info "Skipping phase-one business initialization (BIA_BOOTSTRAP_PHASE1=skip)."
    return 0
  fi

  if [ ! -x "${PHASE1_BOOTSTRAP_SCRIPT}" ]; then
    if [ "${PHASE1_BOOTSTRAP_MODE}" = "required" ]; then
      fail "Phase-one bootstrap script is missing or not executable: ${PHASE1_BOOTSTRAP_SCRIPT}"
    fi
    warn "Phase-one bootstrap script is unavailable; business data initialization is pending."
    return 0
  fi

  info "Running phase-one business initialization..."
  if BIA_CONTAINER_NAME=bia \
     BIA_WORKSPACE_ID="${BIA_WORKSPACE_ID:-default}" \
     "${PHASE1_BOOTSTRAP_SCRIPT}"; then
    info "Phase-one business data is ready."
    return 0
  else
    status=$?
  fi

  # Exit 20 means that model/knowledge/document prerequisites are not ready
  # yet. In auto mode the platform remains usable and the operator can rerun
  # ./bootstrap/run.sh after completing those settings.
  if [ "${status}" -eq 20 ] && [ "${PHASE1_BOOTSTRAP_MODE}" = "auto" ]; then
    warn "Phase-one business initialization is pending because its prerequisites are incomplete."
    warn "After configuring the model, two knowledge bases and 18 documents, run: ./bootstrap/run.sh"
    return 0
  fi

  fail "Phase-one business initialization failed (exit ${status})."
}

docker_engine_ready() {
  command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1
}

wait_for_docker() {
  local attempt
  for attempt in $(seq 1 30); do
    if docker_engine_ready; then
      return 0
    fi
    sleep 1
  done
  return 1
}

show_docker_logs() {
  if command -v journalctl >/dev/null 2>&1; then
    journalctl -u docker.service --no-pager -n 100 2>/dev/null || true
  fi
}

install_offline_compose() {
  local compose_source="${DOCKER_BUNDLE_DIR}/bin/docker-compose"

  [ -f "${compose_source}" ] || \
    fail "Docker Compose is unavailable and the offline binary is missing: ${compose_source}"
  [ "$(id -u)" -eq 0 ] || \
    fail "Root permission is required to install the bundled Docker Compose binary."

  info "Installing offline Docker Compose plugin..."
  mkdir -p "${DOCKER_COMPOSE_PLUGIN_DIR}"
  install -m 0755 "${compose_source}" "${DOCKER_COMPOSE_PLUGIN_DIR}/docker-compose"
  ln -sfn "${DOCKER_COMPOSE_PLUGIN_DIR}/docker-compose" \
    "${DOCKER_BIN_INSTALL_DIR}/docker-compose"
  hash -r
}

install_offline_docker() {
  local binary
  local required_binaries=(
    containerd containerd-shim-runc-v2 ctr docker dockerd docker-init docker-proxy runc
  )

  [ "$(id -u)" -eq 0 ] || \
    fail "Docker is not available. Run this installer as root to install the bundled Docker Engine."
  command -v systemctl >/dev/null 2>&1 || \
    fail "The bundled Docker installer requires a systemd-based Linux system."
  [ -d "${DOCKER_BUNDLE_DIR}/bin" ] || \
    fail "Docker is not installed and the offline directory is missing: ${DOCKER_BUNDLE_DIR}/bin"

  for binary in "${required_binaries[@]}"; do
    [ -f "${DOCKER_BUNDLE_DIR}/bin/${binary}" ] || \
      fail "The offline Docker bundle is incomplete: docker/bin/${binary} is missing."
  done

  info "Docker Engine is unavailable; installing bundled static binaries..."
  mkdir -p "${DOCKER_BIN_INSTALL_DIR}" "${DOCKER_DATA_ROOT}" /etc/docker
  for binary in "${required_binaries[@]}"; do
    install -m 0755 "${DOCKER_BUNDLE_DIR}/bin/${binary}" \
      "${DOCKER_BIN_INSTALL_DIR}/${binary}"
  done
  hash -r

  if [ ! -e /etc/docker/daemon.json ]; then
    cat > /etc/docker/daemon.json <<EOF
{
  "data-root": "${DOCKER_DATA_ROOT}",
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "100m",
    "max-file": "3"
  }
}
EOF
    info "Docker data root configured at ${DOCKER_DATA_ROOT}."
  else
    warn "Keeping the existing /etc/docker/daemon.json; its data-root setting takes precedence."
  fi

  # Use a known unit instead of depending on paths or options in a third-party
  # docker.service file shipped beside the static binaries.
  cat > "${DOCKER_SYSTEMD_UNIT}" <<'EOF'
[Unit]
Description=Docker Application Container Engine
Documentation=https://docs.docker.com
After=network-online.target
Wants=network-online.target
StartLimitBurst=3
StartLimitIntervalSec=60

[Service]
Type=notify
Environment=PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
ExecStart=/usr/local/bin/dockerd
ExecReload=/bin/kill -s HUP $MAINPID
TimeoutStartSec=0
Restart=on-failure
RestartSec=2
LimitNOFILE=infinity
LimitNPROC=infinity
LimitCORE=infinity
TasksMax=infinity
Delegate=yes
KillMode=process
OOMScoreAdjust=-500

[Install]
WantedBy=multi-user.target
EOF

  command -v restorecon >/dev/null 2>&1 && \
    restorecon -RF "${DOCKER_BIN_INSTALL_DIR}" "${DOCKER_SYSTEMD_UNIT}" 2>/dev/null || true
  systemctl daemon-reload
  systemctl enable docker.service >/dev/null
  if ! systemctl restart docker.service; then
    show_docker_logs
    fail "The bundled Docker Engine was installed but failed to start."
  fi
  if ! wait_for_docker; then
    show_docker_logs
    fail "Docker did not become ready within 30 seconds."
  fi

  info "Bundled Docker Engine is running: $(docker --version)"
  info "Docker root directory: $(docker info --format '{{.DockerRootDir}}')"
}

ensure_docker() {
  if docker_engine_ready; then
    info "Using existing Docker Engine: $(docker --version)"
    return
  fi

  # A packaged Docker installation may only need its service started. Do not
  # replace it with static binaries unless dockerd itself is absent.
  if command -v dockerd >/dev/null 2>&1; then
    if [ "$(id -u)" -eq 0 ] && command -v systemctl >/dev/null 2>&1; then
      info "Docker is installed but not ready; starting docker.service..."
      systemctl start docker.service 2>/dev/null || true
      if wait_for_docker; then
        info "Existing Docker Engine is now running: $(docker --version)"
        return
      fi
    fi
    show_docker_logs
    fail "Docker is installed but its daemon is unavailable; the installer will not overwrite it."
  fi

  install_offline_docker
}

if [ ! -f "${RELEASE_FILE}" ]; then
  fail "release.env is missing; run this script from a complete release bundle."
fi

if [ -f "${CHECKSUM_FILE}" ]; then
  info "Verifying release bundle checksums..."
  if command -v sha256sum >/dev/null 2>&1; then
    (cd "${SCRIPT_DIR}" && sha256sum -c SHA256SUMS)
  else
    fail "sha256sum is required to verify the offline package."
  fi
fi

# release.env is generated by package-offline-release.sh and contains only
# build metadata controlled by this project.
# shellcheck disable=SC1090
source "${RELEASE_FILE}"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/initial-admin-password.sh"

: "${BIA_IMAGE:?BIA_IMAGE is missing from release.env}"
: "${BIA_PLATFORM:?BIA_PLATFORM is missing from release.env}"
: "${BIA_IMAGE_TAR:?BIA_IMAGE_TAR is missing from release.env}"

case "$(uname -m)" in
  x86_64|amd64) HOST_PLATFORM="linux/amd64" ;;
  *) fail "This package requires an x86_64/amd64 Linux server; host is $(uname -m)." ;;
esac

if [ "${HOST_PLATFORM}" != "${BIA_PLATFORM}" ]; then
  fail "Platform mismatch: package=${BIA_PLATFORM}, host=${HOST_PLATFORM}."
fi

ensure_docker

if ! docker compose version >/dev/null 2>&1 && \
   ! command -v docker-compose >/dev/null 2>&1; then
  install_offline_compose
fi

if docker compose version >/dev/null 2>&1; then
  COMPOSE=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE=(docker-compose)
else
  fail "Docker Compose could not be installed or detected."
fi

IMAGE_PATH="${SCRIPT_DIR}/images/${BIA_IMAGE_TAR}"
[ -f "${IMAGE_PATH}" ] || fail "Image archive not found: ${IMAGE_PATH}"

mkdir -p "${INSTALL_ROOT}/data" "${INSTALL_ROOT}/releases"
TIMESTAMP="$(date +%Y%m%d%H%M%S)"

if [ -f "${INSTALL_ROOT}/docker-compose.yml" ]; then
  cp "${INSTALL_ROOT}/docker-compose.yml" "${INSTALL_ROOT}/docker-compose.yml.before-${TIMESTAMP}"
fi
if [ -f "${INSTALL_ROOT}/.env" ]; then
  cp "${INSTALL_ROOT}/.env" "${INSTALL_ROOT}/.env.before-${TIMESTAMP}"
fi

cp "${SCRIPT_DIR}/docker-compose.yml" "${INSTALL_ROOT}/docker-compose.yml"
if [ -f "${INSTALL_ROOT}/.env.before-${TIMESTAMP}" ]; then
  chmod 600 "${INSTALL_ROOT}/.env.before-${TIMESTAMP}" || \
    fail "Unable to restrict the .env backup to 0600."
fi
if [ ! -f "${INSTALL_ROOT}/.env" ]; then
  atomic_write_env "${INSTALL_ROOT}/.env" < "${SCRIPT_DIR}/.env.example"
fi

set_env() {
  replace_env_assignment "$1" "$2"
}

get_env() {
  local key="$1"
  sed -n "s/^${key}=//p" "${INSTALL_ROOT}/.env" | tail -n 1
}

random_secret() {
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -hex 32
  else
    dd if=/dev/urandom bs=32 count=1 2>/dev/null | od -An -tx1 | tr -d ' \n'
  fi
}

set_env BIA_IMAGE "${BIA_IMAGE}"
set_env BIA_DATA_DIR "./data"
if [ -n "${BIA_PORT_OVERRIDE:-}" ]; then
  set_env BIA_PORT "${BIA_PORT_OVERRIDE}"
elif [ -z "$(get_env BIA_PORT)" ]; then
  set_env BIA_PORT "29090"
fi

# Only generate database credentials for an empty data directory. On upgrade,
# changing them would make the existing PostgreSQL/Redis data inaccessible.
if [ -z "$(find "${INSTALL_ROOT}/data" -mindepth 1 -maxdepth 1 -print -quit 2>/dev/null)" ]; then
  if [ -z "$(get_env MAXKB_SECRET_KEY)" ]; then
    set_env MAXKB_SECRET_KEY "$(random_secret)"
  fi
  if [ -z "$(get_env MAXKB_HMAC_SIGNED_SERIALIZER_SECRET_KEY)" ]; then
    set_env MAXKB_HMAC_SIGNED_SERIALIZER_SECRET_KEY "$(random_secret)"
  fi
  DB_SECRET="$(get_env POSTGRES_PASSWORD)"
  if [ -z "${DB_SECRET}" ]; then
    DB_SECRET="$(random_secret)"
  fi
  set_env POSTGRES_PASSWORD "${DB_SECRET}"
  set_env MAXKB_DB_PASSWORD "${DB_SECRET}"

  REDIS_SECRET="$(get_env REDIS_PASSWORD)"
  if [ -z "${REDIS_SECRET}" ]; then
    REDIS_SECRET="$(random_secret)"
  fi
  set_env REDIS_PASSWORD "${REDIS_SECRET}"
  set_env MAXKB_REDIS_PASSWORD "${REDIS_SECRET}"
else
  # Legacy installations may have relied on the image defaults and therefore
  # have no secret entries in .env. Empty entries would override those defaults.
  for key in MAXKB_SECRET_KEY MAXKB_HMAC_SIGNED_SERIALIZER_SECRET_KEY \
    POSTGRES_PASSWORD MAXKB_DB_PASSWORD REDIS_PASSWORD MAXKB_REDIS_PASSWORD; do
    delete_exact_env_assignment "${key}" ""
  done
fi

# Fresh installs record the operator-supplied password only in the target .env.
# Existing data directories never receive or replace that setting.
ensure_initial_admin_password
secure_env_file

info "Loading ${BIA_IMAGE} (${BIA_PLATFORM})..."
docker load -i "${IMAGE_PATH}"

ACTUAL_PLATFORM="$(docker image inspect "${BIA_IMAGE}" --format '{{.Os}}/{{.Architecture}}')"
if [ "${ACTUAL_PLATFORM}" != "${BIA_PLATFORM}" ]; then
  fail "Loaded image platform mismatch: expected ${BIA_PLATFORM}, got ${ACTUAL_PLATFORM}."
fi

RELEASE_RECORD_DIR="${INSTALL_ROOT}/releases/${BIA_VERSION:-release}-${BIA_SHA:-unknown}"
mkdir -p "${RELEASE_RECORD_DIR}"
cp "${RELEASE_FILE}" "${RELEASE_RECORD_DIR}/release.env"
cp "${CHECKSUM_FILE}" "${RELEASE_RECORD_DIR}/SHA256SUMS" 2>/dev/null || true

info "Starting service in ${INSTALL_ROOT}..."
cd "${INSTALL_ROOT}"
"${COMPOSE[@]}" config >/dev/null
"${COMPOSE[@]}" up -d

info "Waiting for the container health check..."
for _ in $(seq 1 60); do
  STATUS="$(docker inspect bia --format '{{.State.Status}}' 2>/dev/null || true)"
  HEALTH="$(docker inspect bia --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' 2>/dev/null || true)"
  if [ "${HEALTH}" = "healthy" ]; then
    run_phase1_bootstrap
    PORT="$(get_env BIA_PORT)"
    info "Installation succeeded: http://<server-ip>:${PORT:-29090}/admin/"
    info "Image: ${BIA_IMAGE}; platform: ${ACTUAL_PLATFORM}"
    exit 0
  fi
  if [ "${STATUS}" = "exited" ] || [ "${STATUS}" = "dead" ]; then
    docker logs --tail 200 bia || true
    fail "Container stopped before becoming healthy."
  fi
  sleep 5
done

docker logs --tail 200 bia || true
fail "Container did not become healthy within 5 minutes."
