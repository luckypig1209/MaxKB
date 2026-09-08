#!/bin/bash
# Run this ON the 174 server after the source tree is copied to /data/bia/MaxKB
set -euo pipefail

PROJECT_DIR="${PROJECT_DIR:-/data/bia}"
SRC_DIR="${PROJECT_DIR}/MaxKB"
IMAGE_DIR="${PROJECT_DIR}/images"
VERSION="${1:-bia-v0.1.0}"
SHA="${BIA_SHA:-${2:-}}"
if [ -z "${SHA}" ]; then
  echo "Pass short commit as arg2 or BIA_SHA; git is not required on the server." >&2
  exit 1
fi

mkdir -p "${PROJECT_DIR}/data" "${IMAGE_DIR}"
cp "${SRC_DIR}/deploy/docker-compose.yml" "${PROJECT_DIR}/docker-compose.yml"
if [ ! -f "${PROJECT_DIR}/.env" ]; then
  cp "${SRC_DIR}/deploy/.env.example" "${PROJECT_DIR}/.env"
fi

cd "${SRC_DIR}"
export BIA_PLATFORM="${BIA_PLATFORM:-linux/amd64}"
BIA_SHA="${SHA}" bash deploy/build-and-save.sh "${VERSION}" "${SHA}" "${IMAGE_DIR}"
ARCH_TAG="${BIA_PLATFORM##*/}"
IMAGE="bia:${VERSION}-${SHA}-${ARCH_TAG}"

cd "${PROJECT_DIR}"
if grep -q '^BIA_IMAGE=' .env; then
  sed -i.bak "s|^BIA_IMAGE=.*|BIA_IMAGE=${IMAGE}|" .env
else
  echo "BIA_IMAGE=${IMAGE}" >> .env
fi

docker compose down || true
docker compose up -d
docker compose ps
