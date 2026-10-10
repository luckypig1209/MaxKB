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
docker image inspect "${IMAGE}" >/dev/null 2>&1 || {
  echo "Image is not loaded locally: ${IMAGE}" >&2
  exit 1
}

ACTUAL="$(docker image inspect "${IMAGE}" --format '{{.Os}}/{{.Architecture}}')"
[ "${ACTUAL}" = "${PLATFORM}" ] || {
  echo "Image platform mismatch: expected ${PLATFORM}, got ${ACTUAL}" >&2
  exit 1
}

BUNDLE_NAME="bia-${VERSION}-${SHA}-${ARCH_TAG}"
STAGE_DIR="${OUTPUT_DIR}/${BUNDLE_NAME}"
ARCHIVE="${OUTPUT_DIR}/${BUNDLE_NAME}.tar.gz"
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

cat > "${STAGE_DIR}/release.env" <<EOF
BIA_VERSION=${VERSION}
BIA_SHA=${SHA}
BIA_IMAGE=${IMAGE}
BIA_PLATFORM=${PLATFORM}
BIA_IMAGE_TAR=$(basename "${IMAGE_TAR}")
BIA_IMAGE_ID=$(docker image inspect "${IMAGE}" --format '{{.Id}}')
BIA_BUILT_AT=$(date -u +%Y-%m-%dT%H:%M:%SZ)
EOF

if command -v sha256sum >/dev/null 2>&1; then
  (cd "${STAGE_DIR}" && find . -type f ! -name SHA256SUMS | LC_ALL=C sort | xargs sha256sum > SHA256SUMS)
else
  (cd "${STAGE_DIR}" && find . -type f ! -name SHA256SUMS | LC_ALL=C sort | xargs shasum -a 256 > SHA256SUMS)
fi
if grep -E '__pycache__|\.pyc$|\.pyo$' "${STAGE_DIR}/SHA256SUMS"; then
  echo "Release manifest contains Python cache files." >&2
  exit 1
fi

rm -f "${ARCHIVE}"
tar -C "${OUTPUT_DIR}" -czf "${ARCHIVE}" "${BUNDLE_NAME}"

if command -v sha256sum >/dev/null 2>&1; then
  (cd "${OUTPUT_DIR}" && sha256sum "$(basename "${ARCHIVE}")" > "$(basename "${ARCHIVE}").sha256")
else
  (cd "${OUTPUT_DIR}" && shasum -a 256 "$(basename "${ARCHIVE}")" > "$(basename "${ARCHIVE}").sha256")
fi

echo "BUNDLE=${ARCHIVE}"
echo "CHECKSUM=${ARCHIVE}.sha256"
echo "IMAGE=${IMAGE}"
echo "PLATFORM=${ACTUAL}"
