#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PACKAGE="${ROOT}/deploy/package-offline-release.sh"
INSTALL="${ROOT}/deploy/install-offline.sh"
PASS=0
FAIL_COUNT=0
WORKDIR="$(mktemp -d)"
BINARIES=(
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

assert_eq() {
  local name="$1" expected="$2" actual="$3"
  if [ "${expected}" = "${actual}" ]; then
    PASS=$((PASS + 1))
  else
    echo "FAIL ${name}: expected [${expected}] actual [${actual}]" >&2
    FAIL_COUNT=$((FAIL_COUNT + 1))
  fi
}

assert_contains() {
  local name="$1" haystack="$2" needle="$3"
  if printf '%s' "${haystack}" | grep -F -q -- "${needle}"; then
    PASS=$((PASS + 1))
  else
    echo "FAIL ${name}: missing [${needle}]" >&2
    FAIL_COUNT=$((FAIL_COUNT + 1))
  fi
}

assert_not_contains() {
  local name="$1" haystack="$2" needle="$3"
  if printf '%s' "${haystack}" | grep -F -q -- "${needle}"; then
    echo "FAIL ${name}: unexpectedly found [${needle}]" >&2
    FAIL_COUNT=$((FAIL_COUNT + 1))
  else
    PASS=$((PASS + 1))
  fi
}

cleanup() {
  rm -rf \
    "${ROOT}/deploy/bootstrap/__pycache__" \
    "${ROOT}/deploy/bootstrap/temp.log" \
    "${ROOT}/deploy/bootstrap/.env" \
    "${ROOT}/deploy/bootstrap/note file.txt"
  rm -rf "${WORKDIR}"
}
trap cleanup EXIT

mkdir -p "${WORKDIR}/bin" "${WORKDIR}/docker/bin" "${WORKDIR}/out"
printf 'fake-image\n' > "${WORKDIR}/image.tar"
cat > "${WORKDIR}/bin/docker" <<'EOF'
#!/bin/sh
if [ "$1" = "image" ] && [ "$2" = "inspect" ]; then
  format=""
  shift 2
  while [ "$#" -gt 0 ]; do
    case "$1" in
      --format)
        format="$2"
        shift 2
        ;;
      *)
        shift
        ;;
    esac
  done
  case "${format}" in
    *Architecture*) printf 'linux/amd64\n' ;;
    *Id*) printf 'sha256:test-image\n' ;;
  esac
  exit 0
fi
echo "unexpected docker invocation: $*" >&2
exit 1
EOF
chmod 755 "${WORKDIR}/bin/docker"

run_package() {
  local status
  set +e
  PATH="${WORKDIR}/bin:${PATH}" \
  BIA_PLATFORM=linux/amd64 \
  BIA_REQUIRE_BUNDLED_DOCKER="${1}" \
  BIA_DOCKER_BUNDLE_DIR="${2:-}" \
    bash "${PACKAGE}" test-version abc123 "${WORKDIR}/image.tar" "${WORKDIR}/out" >"${WORKDIR}/package.out" 2>"${WORKDIR}/package.err"
  status=$?
  set -e
  printf '%s' "${status}"
}

STATUS="$(run_package true "")"
assert_eq "full_mode_without_docker_dir_fails" "1" "${STATUS}"
assert_eq "full_mode_without_docker_dir_has_no_archive" "0" "$(find "${WORKDIR}/out" -name '*.tar.gz' | wc -l | tr -d ' ')"

for binary in "${BINARIES[@]}"; do
  printf 'bin-%s\n' "${binary}" > "${WORKDIR}/docker/bin/${binary}"
  chmod 755 "${WORKDIR}/docker/bin/${binary}"
done
mkdir -p "${ROOT}/deploy/bootstrap/__pycache__"
printf 'cache\n' > "${ROOT}/deploy/bootstrap/__pycache__/stale.pyc"
printf 'log\n' > "${ROOT}/deploy/bootstrap/temp.log"
printf 'secret\n' > "${ROOT}/deploy/bootstrap/.env"
printf 'note\n' > "${ROOT}/deploy/bootstrap/note file.txt"

for missing in "${BINARIES[@]}"; do
  mv "${WORKDIR}/docker/bin/${missing}" "${WORKDIR}/docker/bin/${missing}.aside"
  STATUS="$(run_package true "${WORKDIR}/docker")"
  assert_eq "missing_${missing}_fails" "1" "${STATUS}"
  assert_eq "missing_${missing}_has_no_archive" "0" "$(find "${WORKDIR}/out" -name '*.tar.gz' | wc -l | tr -d ' ')"
  mv "${WORKDIR}/docker/bin/${missing}.aside" "${WORKDIR}/docker/bin/${missing}"
  chmod 755 "${WORKDIR}/docker/bin/${missing}"
done

STATUS="$(run_package true "${WORKDIR}/docker")"
assert_eq "full_mode_succeeds" "0" "${STATUS}"
MANIFEST="$(cat "${WORKDIR}/out/bia-test-version-abc123-amd64/SHA256SUMS")"
RELEASE="$(cat "${WORKDIR}/out/bia-test-version-abc123-amd64/release.env")"
README="$(cat "${WORKDIR}/out/bia-test-version-abc123-amd64/README.md")"
PACKAGE_OUT="$(cat "${WORKDIR}/package.out")"
for binary in "${BINARIES[@]}"; do
  assert_contains "checksum_has_${binary}" "${MANIFEST}" "./docker/bin/${binary}"
  if [ -x "${WORKDIR}/out/bia-test-version-abc123-amd64/docker/bin/${binary}" ]; then
    EXEC_STATUS=0
  else
    EXEC_STATUS=1
  fi
  assert_eq "${binary}_executable" "0" "${EXEC_STATUS}"
done
assert_contains "full_release_flag" "${RELEASE}" "BIA_BUNDLED_DOCKER=true"
assert_contains "full_readme" "${README}" "本包包含离线 Docker"
assert_contains "full_log" "${PACKAGE_OUT}" "PACKAGE_MODE=full"
assert_contains "checksum_keeps_spaced_name" "${MANIFEST}" "./bootstrap/note file.txt"
assert_not_contains "checksum_skips_pyc" "${MANIFEST}" ".pyc"
assert_not_contains "checksum_skips_log" "${MANIFEST}" "temp.log"
assert_not_contains "checksum_skips_env" "${MANIFEST}" "./bootstrap/.env"
set +e
(
  cd "${WORKDIR}/out/bia-test-version-abc123-amd64"
  shasum -a 256 -c SHA256SUMS >/dev/null
)
CHECK_STATUS=$?
set -e
assert_eq "inner_checksum_accepts_spaced_name" "0" "${CHECK_STATUS}"

rm -rf "${WORKDIR}/out"
STATUS="$(run_package false "")"
assert_eq "upgrade_mode_succeeds" "0" "${STATUS}"
RELEASE="$(cat "${WORKDIR}/out/bia-test-version-abc123-amd64/release.env")"
README="$(cat "${WORKDIR}/out/bia-test-version-abc123-amd64/README.md")"
PACKAGE_OUT="$(cat "${WORKDIR}/package.out")"
if [ ! -d "${WORKDIR}/out/bia-test-version-abc123-amd64/docker" ]; then
  NO_DOCKER=0
else
  NO_DOCKER=1
fi
assert_eq "upgrade_has_no_docker_dir" "0" "${NO_DOCKER}"
assert_contains "upgrade_release_flag" "${RELEASE}" "BIA_BUNDLED_DOCKER=false"
assert_contains "upgrade_readme" "${README}" "本包是升级包"
assert_contains "upgrade_log" "${PACKAGE_OUT}" "PACKAGE_MODE=upgrade-only"

BUNDLE="$(mktemp -d)"
cp "${INSTALL}" "${BUNDLE}/install.sh"
cp "${ROOT}/deploy/initial-admin-password.sh" "${BUNDLE}/initial-admin-password.sh"
chmod 755 "${BUNDLE}/install.sh"
cat > "${BUNDLE}/release.env" <<'EOF'
BIA_IMAGE=bia:test-version-abc123-amd64
BIA_PLATFORM=linux/amd64
BIA_IMAGE_TAR=image.tar
BIA_BUNDLED_DOCKER=true
EOF
set +e
INCOMPLETE="$(bash "${BUNDLE}/install.sh" 2>&1)"
INCOMPLETE_STATUS=$?
set -e
assert_eq "incomplete_declared_docker_fails_before_load" "1" "${INCOMPLETE_STATUS}"
assert_contains "incomplete_declared_docker_names_the_binary" "${INCOMPLETE}" "docker/bin/containerd"
rm -rf "${BUNDLE}"

echo "PASS=${PASS} FAIL=${FAIL_COUNT}"
[ "${FAIL_COUNT}" -eq 0 ]
