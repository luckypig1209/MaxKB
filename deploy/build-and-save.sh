#!/bin/bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

VERSION="${1:-bia-v0.1.0}"
SHA="${BIA_SHA:-${2:-}}"
SAVE_DIR="${3:-${ROOT_DIR}/images}"
PLATFORM="${BIA_PLATFORM:-}"

if [ -z "${SHA}" ]; then
  if command -v git >/dev/null 2>&1 && git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    SHA="$(git rev-parse --short HEAD)"
  else
    echo "BIA_SHA or arg2 (short commit) is required; do not use git on the server." >&2
    exit 1
  fi
fi

if [ -z "${PLATFORM}" ]; then
  case "$(uname -m)" in
    arm64|aarch64) PLATFORM="linux/arm64" ;;
    x86_64|amd64) PLATFORM="linux/amd64" ;;
    *)
      echo "Set BIA_PLATFORM to linux/arm64 or linux/amd64." >&2
      exit 1
      ;;
  esac
fi

case "${PLATFORM}" in
  linux/arm64) ARCH_TAG="arm64" ;;
  linux/amd64) ARCH_TAG="amd64" ;;
  *)
    echo "BIA_PLATFORM must be linux/arm64 or linux/amd64, got: ${PLATFORM}" >&2
    exit 1
    ;;
esac

if [ "${ARCH_TAG}" = "amd64" ] && command -v git >/dev/null 2>&1 && git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  if [ -n "$(git status --porcelain)" ]; then
    echo "amd64 release must be built from a clean git tree." >&2
    exit 1
  fi
fi

IMAGE="bia:${VERSION}-${SHA}-${ARCH_TAG}"
ALIAS="bia:${VERSION}-${ARCH_TAG}"

# China: FROM 镜像走 Docker Desktop 代理；apt/npm/pip 走国内源，不要再塞 HTTP_PROXY 进 RUN。
BIA_CN_MIRROR="${BIA_CN_MIRROR:-1}"
EXTRA_BUILD_ARGS=()
if [ "${BIA_CN_MIRROR}" != "0" ]; then
  EXTRA_BUILD_ARGS+=(--build-arg "BIA_CN_MIRROR=1")
else
  PROXY_URL="${HTTPS_PROXY:-${https_proxy:-${HTTP_PROXY:-${http_proxy:-}}}}"
  if [ -n "${PROXY_URL}" ]; then
    BUILD_PROXY="${PROXY_URL//127.0.0.1/host.docker.internal}"
    EXTRA_BUILD_ARGS+=(
      --build-arg "HTTP_PROXY=${BUILD_PROXY}"
      --build-arg "HTTPS_PROXY=${BUILD_PROXY}"
      --build-arg "http_proxy=${BUILD_PROXY}"
      --build-arg "https_proxy=${BUILD_PROXY}"
      --build-arg "NO_PROXY=localhost,127.0.0.1"
      --build-arg "no_proxy=localhost,127.0.0.1"
    )
  fi
fi

docker buildx build \
  --platform "${PLATFORM}" \
  -f installer/Dockerfile \
  --build-arg "DOCKER_IMAGE_TAG=${VERSION}" \
  --build-arg "BUILD_AT=$(date +%Y-%m-%dT%H:%M)" \
  --build-arg "GITHUB_COMMIT=${SHA}" \
  ${EXTRA_BUILD_ARGS[@]+"${EXTRA_BUILD_ARGS[@]}"} \
  -t "${IMAGE}" \
  -t "${ALIAS}" \
  --load \
  .

ACTUAL="$(docker image inspect "${IMAGE}" --format '{{.Os}}/{{.Architecture}}')"
if [ "${ACTUAL}" != "${PLATFORM}" ]; then
  echo "image platform mismatch: expected ${PLATFORM}, got ${ACTUAL}" >&2
  exit 1
fi

if [ "${BIA_SAVE:-1}" != "0" ]; then
  mkdir -p "${SAVE_DIR}"
  TAR_NAME="${IMAGE//[:\/]/_}.tar"
  docker save -o "${SAVE_DIR}/${TAR_NAME}" "${IMAGE}" "${ALIAS}"
  echo "SAVED=${SAVE_DIR}/${TAR_NAME}"
fi

echo "IMAGE=${IMAGE}"
echo "PLATFORM=${ACTUAL}"
echo "DIGEST=$(docker image inspect "${IMAGE}" --format '{{.Id}}')"
