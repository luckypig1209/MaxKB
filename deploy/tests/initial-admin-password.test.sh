#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck disable=SC1091
source "${ROOT}/initial-admin-password.sh"

PASS=0
FAIL_COUNT=0

assert_eq() {
  local name="$1" expected="$2" actual="$3"
  if [ "${expected}" = "${actual}" ]; then
    PASS=$((PASS + 1))
  else
    echo "FAIL ${name}" >&2
    FAIL_COUNT=$((FAIL_COUNT + 1))
  fi
}

assert_not_contains() {
  local name="$1" haystack="$2" needle="$3"
  if [ -n "${needle}" ] && printf '%s' "${haystack}" | grep -F -q -- "${needle}"; then
    echo "FAIL ${name}" >&2
    FAIL_COUNT=$((FAIL_COUNT + 1))
  else
    PASS=$((PASS + 1))
  fi
}

new_root() {
  local root
  root="$(mktemp -d)"
  mkdir -p "${root}/data"
  printf 'BIA_PORT=29090\nMAXKB_DEFAULT_PASSWORD=\n' > "${root}/.env"
  printf '%s' "${root}"
}

run_case() {
  local root="$1"
  shift
  local output status
  set +e
  output="$(MAXKB_DEFAULT_PASSWORD="${1-}" INSTALL_ROOT="${root}" ensure_initial_admin_password 2>&1)"
  status=$?
  set -e
  printf '%s\n%s' "${status}" "${output}"
}

SECRET='p*a#ss=word'

ROOT_DIR="$(new_root)"
RESULT="$(run_case "${ROOT_DIR}" "${SECRET}")"
STATUS="${RESULT%%$'\n'*}"
OUTPUT="${RESULT#*$'\n'}"
assert_eq "fresh_status" "0" "${STATUS}"
assert_eq "fresh_value" "${SECRET}" "$(INSTALL_ROOT="${ROOT_DIR}" get_env MAXKB_DEFAULT_PASSWORD)"
assert_not_contains "fresh_log_hides_secret" "${OUTPUT}" "${SECRET}"
rm -rf "${ROOT_DIR}"

ROOT_DIR="$(new_root)"
printf 'MAXKB_DEFAULT_PASSWORD=%s\n' 'kept-value' >> "${ROOT_DIR}/.env"
RESULT="$(run_case "${ROOT_DIR}" 'replacement')"
STATUS="${RESULT%%$'\n'*}"
OUTPUT="${RESULT#*$'\n'}"
assert_eq "repeat_status" "0" "${STATUS}"
assert_eq "repeat_keeps_existing" "kept-value" "$(INSTALL_ROOT="${ROOT_DIR}" get_env MAXKB_DEFAULT_PASSWORD)"
assert_not_contains "repeat_log_hides_existing" "${OUTPUT}" "kept-value"
rm -rf "${ROOT_DIR}"

ROOT_DIR="$(new_root)"
mkdir -p "${ROOT_DIR}/data/postgres"
RESULT="$(run_case "${ROOT_DIR}" "${SECRET}")"
STATUS="${RESULT%%$'\n'*}"
OUTPUT="${RESULT#*$'\n'}"
assert_eq "upgrade_status" "0" "${STATUS}"
assert_eq "upgrade_does_not_set_password" "" "$(INSTALL_ROOT="${ROOT_DIR}" get_env MAXKB_DEFAULT_PASSWORD)"
assert_not_contains "upgrade_log_hides_secret" "${OUTPUT}" "${SECRET}"
rm -rf "${ROOT_DIR}"

ROOT_DIR="$(new_root)"
mkdir -p "${ROOT_DIR}/data/postgres"
printf 'MAXKB_DEFAULT_PASSWORD=%s\n' 'already-set' >> "${ROOT_DIR}/.env"
RESULT="$(run_case "${ROOT_DIR}" "${SECRET}")"
STATUS="${RESULT%%$'\n'*}"
assert_eq "upgrade_keeps_existing_status" "0" "${STATUS}"
assert_eq "upgrade_keeps_existing_value" "already-set" "$(INSTALL_ROOT="${ROOT_DIR}" get_env MAXKB_DEFAULT_PASSWORD)"
rm -rf "${ROOT_DIR}"

ROOT_DIR="$(new_root)"
RESULT="$(run_case "${ROOT_DIR}" "")"
STATUS="${RESULT%%$'\n'*}"
OUTPUT="${RESULT#*$'\n'}"
assert_eq "missing_secret_rejected" "1" "${STATUS}"
assert_not_contains "missing_secret_has_no_sample" "${OUTPUT}" "MaxKB@"
rm -rf "${ROOT_DIR}"

mode_of() {
  INSTALL_ROOT="${1}" file_mode "${1}/.env"
}

ROOT_DIR="$(new_root)"
chmod 644 "${ROOT_DIR}/.env"
RESULT="$(run_case "${ROOT_DIR}" "${SECRET}")"
STATUS="${RESULT%%$'\n'*}"
assert_eq "fresh_mode_status" "0" "${STATUS}"
assert_eq "fresh_mode_600" "600" "$(mode_of "${ROOT_DIR}")"
rm -rf "${ROOT_DIR}"

ROOT_DIR="$(new_root)"
mkdir -p "${ROOT_DIR}/data/postgres"
chmod 644 "${ROOT_DIR}/.env"
RESULT="$(run_case "${ROOT_DIR}" "${SECRET}")"
STATUS="${RESULT%%$'\n'*}"
assert_eq "upgrade_mode_status" "0" "${STATUS}"
assert_eq "upgrade_mode_600" "600" "$(mode_of "${ROOT_DIR}")"
rm -rf "${ROOT_DIR}"

ROOT_DIR="$(new_root)"
printf 'MARKER=keep\n' >> "${ROOT_DIR}/.env"
chmod 644 "${ROOT_DIR}/.env"
BEFORE="$(cat "${ROOT_DIR}/.env")"
set +e
RESULT="$(BIA_ENV_REPLACE_FAIL=1 run_case "${ROOT_DIR}" "${SECRET}")"
set -e
STATUS="${RESULT%%$'\n'*}"
assert_eq "failed_replace_status" "1" "${STATUS}"
assert_eq "failed_replace_keeps_original" "${BEFORE}" "$(cat "${ROOT_DIR}/.env")"
assert_eq "failed_replace_keeps_mode" "644" "$(mode_of "${ROOT_DIR}")"
LEFTOVER="$(find "${ROOT_DIR}" -name '.env.*' -print)"
assert_eq "failed_replace_removes_temp" "" "${LEFTOVER}"
rm -rf "${ROOT_DIR}"

ROOT_DIR="$(new_root)"
chmod 644 "${ROOT_DIR}/.env"
BEFORE="$(cat "${ROOT_DIR}/.env")"
set +e
RESULT="$(BIA_ENV_REPLACE_FAIL=1 INSTALL_ROOT="${ROOT_DIR}" replace_env_assignment BIA_PORT 29091 2>&1)"
STATUS=$?
set -e
assert_eq "set_env_fail_status" "1" "${STATUS}"
assert_eq "set_env_fail_keeps_original" "${BEFORE}" "$(cat "${ROOT_DIR}/.env")"
assert_eq "set_env_fail_keeps_mode" "644" "$(mode_of "${ROOT_DIR}")"
assert_eq "set_env_fail_no_work_file" "" "$(find "${ROOT_DIR}" -name '.env.work.*' -print)"
assert_not_contains "set_env_fail_hides_output" "${RESULT}" "29091"
rm -rf "${ROOT_DIR}"

ROOT_DIR="$(new_root)"
INSTALL_ROOT="${ROOT_DIR}" replace_env_assignment BIA_PORT 29091
assert_eq "set_env_updates_value" "29091" "$(INSTALL_ROOT="${ROOT_DIR}" get_env BIA_PORT)"
assert_eq "set_env_mode_600" "600" "$(mode_of "${ROOT_DIR}")"
assert_eq "set_env_no_work_file" "" "$(find "${ROOT_DIR}" -name '.env.work.*' -print)"
rm -rf "${ROOT_DIR}"

ROOT_DIR="$(new_root)"
printf 'EMPTY_KEY=\n' >> "${ROOT_DIR}/.env"
chmod 644 "${ROOT_DIR}/.env"
BEFORE="$(cat "${ROOT_DIR}/.env")"
set +e
RESULT="$(BIA_ENV_REPLACE_FAIL=1 INSTALL_ROOT="${ROOT_DIR}" delete_exact_env_assignment EMPTY_KEY "" 2>&1)"
STATUS=$?
set -e
assert_eq "delete_empty_fail_status" "1" "${STATUS}"
assert_eq "delete_empty_fail_keeps_original" "${BEFORE}" "$(cat "${ROOT_DIR}/.env")"
assert_eq "delete_empty_fail_no_work_file" "" "$(find "${ROOT_DIR}" -name '.env.work.*' -print)"
rm -rf "${ROOT_DIR}"

echo "passed=${PASS} failed=${FAIL_COUNT}"
[ "${FAIL_COUNT}" -eq 0 ]
