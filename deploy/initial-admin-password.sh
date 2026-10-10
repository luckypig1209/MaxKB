#!/usr/bin/env bash
# First-install admin password handling for offline installs.
# The password is never printed. Callers must set INSTALL_ROOT.

fail() {
  echo "[ERROR] $*" >&2
  exit 1
}

info() {
  echo "[INFO] $*"
}

data_dir_has_content() {
  [ -n "$(find "${INSTALL_ROOT}/data" -mindepth 1 -maxdepth 1 -print -quit 2>/dev/null)" ]
}

get_env() {
  local key="$1"
  sed -n "s/^${key}=//p" "${INSTALL_ROOT}/.env" | tail -n 1
}

reject_multiline_secret() {
  local value="$1"
  case "${value}" in
    *$'\n'*|*$'\r'*)
      fail "MAXKB_DEFAULT_PASSWORD must be a single line."
      ;;
  esac
}

file_owner() {
  if stat -c '%u:%g' "$1" >/dev/null 2>&1; then
    stat -c '%u:%g' "$1"
  else
    stat -f '%u:%g' "$1"
  fi
}

file_mode() {
  if stat -c '%a' "$1" >/dev/null 2>&1; then
    stat -c '%a' "$1"
  else
    stat -f '%OLp' "$1"
  fi
}

# Replace a file by writing a same-directory temporary file and renaming it.
# The destination owner is preserved. The mode is always 0600.
atomic_write_env() {
  local file="$1"
  local dir tmp owner current
  dir="$(cd "$(dirname "${file}")" && pwd)"
  file="${dir}/$(basename "${file}")"
  tmp="$(mktemp "${dir}/.env.XXXXXX")"
  if ! cat > "${tmp}"; then
    rm -f "${tmp}"
    fail "Failed to write the temporary env file."
  fi
  if [ ! -s "${tmp}" ]; then
    rm -f "${tmp}"
    fail "Refusing to replace .env with an empty file."
  fi
  chmod 600 "${tmp}" || {
    rm -f "${tmp}"
    fail "Unable to set temporary env file permissions to 0600."
  }
  if [ -e "${file}" ]; then
    owner="$(file_owner "${file}")"
    current="$(file_owner "${tmp}")"
    if [ "${current}" != "${owner}" ]; then
      if ! chown "${owner}" "${tmp}"; then
        rm -f "${tmp}"
        fail "Unable to preserve .env owner."
      fi
    fi
  fi
  if [ "${BIA_ENV_REPLACE_FAIL:-}" = "1" ]; then
    rm -f "${tmp}"
    fail "simulated env replace failure"
  fi
  if ! mv -f "${tmp}" "${file}"; then
    rm -f "${tmp}"
    fail "Failed to replace .env."
  fi
  chmod 600 "${file}" || fail "Unable to set .env permissions to 0600."
}

secure_env_file() {
  local file="${INSTALL_ROOT}/.env"
  local mode
  [ -f "${file}" ] || fail "Target .env is missing."
  chmod 600 "${file}" || fail "Unable to set .env permissions to 0600."
  mode="$(file_mode "${file}")"
  case "${mode}" in
    600) ;;
    *) fail ".env permissions are ${mode}, expected 0600." ;;
  esac
}

replace_env_assignment() {
  local key="$1"
  local value="$2"
  local file="${INSTALL_ROOT}/.env"
  [ -f "${file}" ] || fail "Target .env is missing."
  (
    env_work_tmp="$(mktemp "${INSTALL_ROOT}/.env.work.XXXXXX")"
    trap 'rm -f -- "${env_work_tmp-}"' EXIT
    if grep -q "^${key}=" "${file}"; then
      grep -v "^${key}=" "${file}" > "${env_work_tmp}" || true
    else
      cat "${file}" > "${env_work_tmp}"
    fi
    printf '%s=%s\n' "${key}" "${value}" >> "${env_work_tmp}"
    atomic_write_env "${file}" < "${env_work_tmp}"
  ) || return $?
}

delete_exact_env_assignment() {
  local key="$1"
  local value="$2"
  local file="${INSTALL_ROOT}/.env"
  [ -f "${file}" ] || fail "Target .env is missing."
  grep -q "^${key}=${value}$" "${file}" || return 0
  (
    env_work_tmp="$(mktemp "${INSTALL_ROOT}/.env.work.XXXXXX")"
    trap 'rm -f -- "${env_work_tmp-}"' EXIT
    grep -v "^${key}=${value}$" "${file}" > "${env_work_tmp}" || true
    atomic_write_env "${file}" < "${env_work_tmp}"
  ) || return $?
}

write_initial_admin_password() {
  local value="$1"
  local file="${INSTALL_ROOT}/.env"
  reject_multiline_secret "${value}"
  (
    env_work_tmp="$(mktemp "${INSTALL_ROOT}/.env.work.XXXXXX")"
    trap 'rm -f -- "${env_work_tmp-}"' EXIT
    grep -v '^MAXKB_DEFAULT_PASSWORD=' "${file}" > "${env_work_tmp}" || true
    printf 'MAXKB_DEFAULT_PASSWORD=%s\n' "${value}" >> "${env_work_tmp}"
    atomic_write_env "${file}" < "${env_work_tmp}"
  ) || return $?
}

remove_empty_initial_admin_password() {
  local file="${INSTALL_ROOT}/.env"
  (
    env_work_tmp="$(mktemp "${INSTALL_ROOT}/.env.work.XXXXXX")"
    trap 'rm -f -- "${env_work_tmp-}"' EXIT
    grep -v '^MAXKB_DEFAULT_PASSWORD=$' "${file}" > "${env_work_tmp}" || true
    atomic_write_env "${file}" < "${env_work_tmp}"
  ) || return $?
}

ensure_initial_admin_password() {
  local existing supplied
  if [ ! -f "${INSTALL_ROOT}/.env" ]; then
    fail "Target .env is missing; refusing to initialize the admin password."
  fi
  existing="$(get_env MAXKB_DEFAULT_PASSWORD)"
  if data_dir_has_content; then
    if [ -z "${existing}" ]; then
      remove_empty_initial_admin_password
    fi
    secure_env_file
    info "Existing data directory detected; admin password initialization skipped."
    return 0
  fi
  if [ -n "${existing}" ]; then
    secure_env_file
    info "Admin initial password already configured; leaving it unchanged."
    return 0
  fi
  supplied="${MAXKB_DEFAULT_PASSWORD:-}"
  if [ -z "${supplied}" ]; then
    fail "A fresh installation requires MAXKB_DEFAULT_PASSWORD in the installer environment. The value is stored only in the target .env."
  fi
  write_initial_admin_password "${supplied}" || return $?
  unset MAXKB_DEFAULT_PASSWORD
  secure_env_file
  info "Admin initial password configured for first installation."
}
