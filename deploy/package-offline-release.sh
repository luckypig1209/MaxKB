#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
DEPLOY_DIR="${ROOT_DIR}/deploy"
VERSION="${1:?Usage: package-offline-release.sh <version> <sha> <image-tar> [output-dir]}"
SHA="${2:?Usage: package-offline-release.sh <version> <sha> <image-tar> [output-dir]}"
IMAGE_TAR="$(cd "$(dirname "${3:?image-tar is required}")" && pwd)/$(basename "$3")"
OUTPUT_DIR="${4:-${ROOT_DIR}/releases}"
PLATFORM="${BIA_PLATFORM:-linux/amd64}"

case "${PLATFORM}" in
  linux/amd64) ARCH_TAG="amd64" ;;
  linux/arm64) ARCH_TAG="arm64" ;;
  *) echo "Unsupported BIA_PLATFORM: ${PLATFORM}" >&2; exit 1 ;;
esac

IMAGE="bia:${VERSION}-${SHA}-${ARCH_TAG}"
BUNDLE_NAME="bia-${VERSION}-${SHA}-${ARCH_TAG}"
STAGE_DIR="${OUTPUT_DIR}/${BUNDLE_NAME}"
ARCHIVE="${OUTPUT_DIR}/${BUNDLE_NAME}.tar.gz"
PARTIAL_ARCHIVE="${ARCHIVE}.partial"
BIA_REQUIRE_BUNDLED_DOCKER="${BIA_REQUIRE_BUNDLED_DOCKER:-true}"

REQUIRED_DOCKER_BINARIES=(
  containerd
  containerd-shim-runc-v2
  ctr
  docker
  dockerd
  docker-init
  docker-proxy
  runc
  docker-compose
)

cleanup_incomplete_archive() {
  local status=$?
  if [ "${status}" -ne 0 ]; then
    rm -f "${PARTIAL_ARCHIVE}" "${ARCHIVE}.sha256.tmp"
  fi
}
trap cleanup_incomplete_archive EXIT

case "${BIA_REQUIRE_BUNDLED_DOCKER}" in
  true|false) ;;
  *)
    echo "BIA_REQUIRE_BUNDLED_DOCKER must be true or false." >&2
    exit 1
    ;;
esac

docker image inspect "${IMAGE}" >/dev/null 2>&1 || {
  echo "Image is not loaded locally: ${IMAGE}" >&2
  exit 1
}

ACTUAL="$(docker image inspect "${IMAGE}" --format '{{.Os}}/{{.Architecture}}')"
[ "${ACTUAL}" = "${PLATFORM}" ] || {
  echo "Image platform mismatch: expected ${PLATFORM}, got ${ACTUAL}" >&2
  exit 1
}

rm -rf "${STAGE_DIR}"
mkdir -p "${STAGE_DIR}/images" "${OUTPUT_DIR}"

cp "${DEPLOY_DIR}/docker-compose.yml" "${STAGE_DIR}/docker-compose.yml"
cp "${DEPLOY_DIR}/.env.example" "${STAGE_DIR}/.env.example"
cp "${DEPLOY_DIR}/install-offline.sh" "${STAGE_DIR}/install.sh"
cp "${DEPLOY_DIR}/initial-admin-password.sh" "${STAGE_DIR}/initial-admin-password.sh"
cp "${DEPLOY_DIR}/OFFLINE_INSTALL.md" "${STAGE_DIR}/README.md"
cp -R "${DEPLOY_DIR}/bootstrap" "${STAGE_DIR}/bootstrap"
find "${STAGE_DIR}/bootstrap" -depth -type d -name '__pycache__' -exec rm -rf {} +
find "${STAGE_DIR}/bootstrap" -type f \( -name '*.pyc' -o -name '*.pyo' \) -delete
ln "${IMAGE_TAR}" "${STAGE_DIR}/images/$(basename "${IMAGE_TAR}")" 2>/dev/null || \
  cp "${IMAGE_TAR}" "${STAGE_DIR}/images/$(basename "${IMAGE_TAR}")"
chmod 755 "${STAGE_DIR}/install.sh"
chmod 755 "${STAGE_DIR}/bootstrap/run.sh"
find "${STAGE_DIR}" -depth -type d -name '__pycache__' -exec rm -rf {} +
find "${STAGE_DIR}" -type f \( -name '*.pyc' -o -name '*.pyo' -o -name '*.log' -o -name '.env' \) -delete

if [ "${BIA_REQUIRE_BUNDLED_DOCKER}" = "true" ]; then
  DOCKER_SOURCE="${BIA_DOCKER_BUNDLE_DIR:-}"
  if [ -z "${DOCKER_SOURCE}" ] || [ ! -d "${DOCKER_SOURCE}/bin" ]; then
    echo "A full offline package requires BIA_DOCKER_BUNDLE_DIR to point at a docker directory." >&2
    exit 1
  fi
  for binary in "${REQUIRED_DOCKER_BINARIES[@]}"; do
    if [ ! -f "${DOCKER_SOURCE}/bin/${binary}" ]; then
      echo "Full offline package is missing Docker binary: ${binary}" >&2
      exit 1
    fi
  done
  mkdir -p "${STAGE_DIR}/docker/bin"
  for binary in "${REQUIRED_DOCKER_BINARIES[@]}"; do
    cp "${DOCKER_SOURCE}/bin/${binary}" "${STAGE_DIR}/docker/bin/${binary}"
    chmod 755 "${STAGE_DIR}/docker/bin/${binary}"
  done
  PACKAGE_NOTICE="本包包含离线 Docker。目标机已有 Docker 时将复用现有引擎，不会覆盖 /etc/docker/daemon.json。"
  echo "PACKAGE_MODE=full"
else
  PACKAGE_NOTICE="本包是升级包，不包含离线 Docker。目标服务器必须已经安装 Docker Engine 和 Docker Compose。"
  echo "PACKAGE_MODE=upgrade-only"
fi
echo "${PACKAGE_NOTICE}"
{
  echo "> ${PACKAGE_NOTICE}"
  echo
  cat "${STAGE_DIR}/README.md"
} > "${STAGE_DIR}/README.md.tmp"
mv "${STAGE_DIR}/README.md.tmp" "${STAGE_DIR}/README.md"

cat > "${STAGE_DIR}/release.env" <<EOF
BIA_VERSION=${VERSION}
BIA_SHA=${SHA}
BIA_IMAGE=${IMAGE}
BIA_PLATFORM=${PLATFORM}
BIA_IMAGE_TAR=$(basename "${IMAGE_TAR}")
BIA_IMAGE_ID=$(docker image inspect "${IMAGE}" --format '{{.Id}}')
BIA_BUILT_AT=$(date -u +%Y-%m-%dT%H:%M:%SZ)
BIA_BUNDLED_DOCKER=${BIA_REQUIRE_BUNDLED_DOCKER}
EOF

python3 - "${STAGE_DIR}" <<'PY'
import hashlib
import os
import sys

root = sys.argv[1]
paths = []
for dirpath, dirnames, filenames in os.walk(root):
    dirnames[:] = [name for name in dirnames if name != "__pycache__"]
    for name in filenames:
        if name == "SHA256SUMS" or name.endswith((".pyc", ".pyo", ".log")) or name == ".env":
            continue
        full = os.path.join(dirpath, name)
        if os.path.isfile(full):
            paths.append(os.path.relpath(full, root))

def line_for(relpath):
    digest = hashlib.sha256()
    with open(os.path.join(root, relpath), "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    text = "./" + relpath.replace(os.sep, "/")
    escaped = text.replace("\\", "\\\\").replace("\n", "\\n")
    prefix = "\\" if escaped != text else ""
    return f"{prefix}{digest.hexdigest()}  {escaped}"

with open(os.path.join(root, "SHA256SUMS"), "w", encoding="utf-8", newline="\n") as output:
    for relpath in sorted(paths):
        output.write(line_for(relpath) + "\n")
PY
if grep -E '__pycache__|\.pyc$|\.pyo$|(^|/)\.env$' "${STAGE_DIR}/SHA256SUMS"; then
  echo "Release manifest contains Python cache files or a local .env." >&2
  exit 1
fi

rm -f "${PARTIAL_ARCHIVE}"
tar -C "${OUTPUT_DIR}" -czf "${PARTIAL_ARCHIVE}" "${BUNDLE_NAME}"
if command -v sha256sum >/dev/null 2>&1; then
  (cd "${OUTPUT_DIR}" && sha256sum "$(basename "${PARTIAL_ARCHIVE}")" > "$(basename "${ARCHIVE}").sha256.tmp")
else
  (cd "${OUTPUT_DIR}" && shasum -a 256 "$(basename "${PARTIAL_ARCHIVE}")" > "$(basename "${ARCHIVE}").sha256.tmp")
fi
mv "${PARTIAL_ARCHIVE}" "${ARCHIVE}"
mv "${ARCHIVE}.sha256.tmp" "${ARCHIVE}.sha256"

echo "BUNDLE=${ARCHIVE}"
echo "CHECKSUM=${ARCHIVE}.sha256"
echo "IMAGE=${IMAGE}"
echo "PLATFORM=${ACTUAL}"
