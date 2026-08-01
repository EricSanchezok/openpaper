#!/usr/bin/env bash
set -euo pipefail

readonly CONTRACT_VERSION=1
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
COMPOSE_FILE=${SCHOLENS_COMPOSE_FILE:-"${SCRIPT_DIR}/compose.yaml"}
SMOKE_SCRIPT=${SCHOLENS_SMOKE_SCRIPT:-"${SCRIPT_DIR}/smoke.sh"}
RUNTIME_ENV=${SCHOLENS_RUNTIME_ENV:-/etc/scholens/runtime.env}
STATE_DIR=${SCHOLENS_STATE_DIR:-/var/lib/scholens}
CURRENT_ENV="${STATE_DIR}/current.env"
PREVIOUS_ENV="${STATE_DIR}/previous.env"
TRANSITION_ENV="${STATE_DIR}/transition.env"
LOCK_FILE="${STATE_DIR}/deploy.lock"
FAILED_DIR="${STATE_DIR}/failed"

fail() {
  printf 'Error: %s\n' "$*" >&2
  exit 1
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || fail "required command not found: $1"
}

read_value() {
  local file=$1
  local key=$2
  local value
  value=$(sed -n "s/^${key}=//p" "${file}")
  [[ -n ${value} ]] || fail "${key} is required in ${file}"
  [[ $(grep -c "^${key}=" "${file}") -eq 1 ]] || fail "duplicate ${key} in ${file}"
  printf '%s\n' "${value}"
}

file_mode() {
  stat -c '%a' "$1" 2>/dev/null || stat -f '%Lp' "$1"
}

file_owner_uid() {
  stat -c '%u' "$1" 2>/dev/null || stat -f '%u' "$1"
}

validate_runtime_env() {
  [[ -f ${RUNTIME_ENV} && ! -L ${RUNTIME_ENV} ]] || \
    fail "runtime env must be a regular non-symlink file: ${RUNTIME_ENV}"
  [[ $(file_mode "${RUNTIME_ENV}") == 600 ]] || \
    fail "runtime env must have mode 0600: ${RUNTIME_ENV}"
  local owner_uid
  owner_uid=$(file_owner_uid "${RUNTIME_ENV}")
  [[ ${owner_uid} == 0 || ${owner_uid} == "$(id -u)" ]] || \
    fail "runtime env must be owned by root or the deployment user"
}

validate_digest_reference() {
  [[ $1 =~ ^[^[:space:]@]+@sha256:[0-9a-f]{64}$ ]] || \
    fail "image must be a digest-qualified reference: $1"
}

validate_release_sha() {
  [[ $1 =~ ^[0-9a-f]{40}$ ]] || fail "release SHA must contain 40 lowercase hex characters"
}

sha256_file() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
  else
    shasum -a 256 "$1" | awk '{print $1}'
  fi
}

package_sha() {
  local inventory=""
  local path
  for path in "${SCRIPT_DIR}/compose.yaml" "${SCRIPT_DIR}/bootstrap-db.sql" \
    "${SCRIPT_DIR}/release.sh" "${SCRIPT_DIR}/smoke.sh" "${SCRIPT_DIR}/wait-ssm.sh" \
    "${SCRIPT_DIR}/observability.yaml" "${SCRIPT_DIR}/install-observability.sh" \
    "${SCRIPT_DIR}/upload-source-maps.sh"; do
    [[ -f ${path} && ! -L ${path} ]] || fail "production package file missing: ${path}"
    inventory+="${path##*/}:$(sha256_file "${path}")"$'\n'
  done
  if command -v sha256sum >/dev/null 2>&1; then
    printf '%s' "${inventory}" | sha256sum | awk '{print $1}'
  else
    printf '%s' "${inventory}" | shasum -a 256 | awk '{print $1}'
  fi
}

compose() {
  local release_env=$1
  shift
  docker compose --env-file "${RUNTIME_ENV}" --env-file "${release_env}" \
    -f "${COMPOSE_FILE}" "$@"
}

acquire_lock() {
  mkdir -p "${STATE_DIR}" "${FAILED_DIR}"
  exec 9>"${LOCK_FILE}"
  flock -n 9 || fail "another Scholens release operation is running"
}

ensure_no_transition() {
  [[ ! -e ${TRANSITION_ENV} ]] || \
    fail "unfinished release transition requires reconciliation: ${TRANSITION_ENV}"
}

write_transition() {
  local operation=$1
  local target=$2
  local temporary="${TRANSITION_ENV}.tmp"
  umask 077
  {
    printf 'SCHOLENS_TRANSITION_OPERATION=%s\n' "${operation}"
    printf 'SCHOLENS_TRANSITION_TARGET=%s\n' "${target}"
  } >"${temporary}"
  mv "${temporary}" "${TRANSITION_ENV}"
}

write_manifest() {
  local destination=$1
  local package_digest=$2
  local release_sha=$3
  local api_image=$4
  local client_image=$5
  local jobs_image=$6
  local temporary="${destination}.tmp"
  umask 077
  {
    printf 'SCHOLENS_RELEASE_CONTRACT_VERSION=%s\n' "${CONTRACT_VERSION}"
    printf 'SCHOLENS_PACKAGE_SHA=%s\n' "${package_digest}"
    printf 'SCHOLENS_RELEASE_SHA=%s\n' "${release_sha}"
    printf 'SCHOLENS_API_IMAGE=%s\n' "${api_image}"
    printf 'SCHOLENS_CLIENT_IMAGE=%s\n' "${client_image}"
    printf 'SCHOLENS_JOBS_IMAGE=%s\n' "${jobs_image}"
  } >"${temporary}"
  mv "${temporary}" "${destination}"
}

validate_manifest() {
  local manifest=$1
  [[ -f ${manifest} && ! -L ${manifest} ]] || fail "release manifest missing: ${manifest}"
  [[ $(read_value "${manifest}" SCHOLENS_RELEASE_CONTRACT_VERSION) == "${CONTRACT_VERSION}" ]] || \
    fail "unsupported release contract in ${manifest}"
  validate_release_sha "$(read_value "${manifest}" SCHOLENS_RELEASE_SHA)"
  validate_digest_reference "$(read_value "${manifest}" SCHOLENS_API_IMAGE)"
  validate_digest_reference "$(read_value "${manifest}" SCHOLENS_CLIENT_IMAGE)"
  validate_digest_reference "$(read_value "${manifest}" SCHOLENS_JOBS_IMAGE)"
}

login_registry() {
  local region registry
  region=$(read_value "${RUNTIME_ENV}" SCHOLENS_AWS_REGION)
  registry=$(read_value "${RUNTIME_ENV}" SCHOLENS_ECR_REGISTRY)
  aws ecr get-login-password --region "${region}" | \
    docker login --username AWS --password-stdin "${registry}"
}

pull_release() {
  local manifest=$1
  compose "${manifest}" pull api client jobs-api worker beat rabbitmq redis
}

activate_release() {
  local manifest=$1
  compose "${manifest}" up -d --no-build --remove-orphans \
    rabbitmq redis jobs-api worker beat api client
}

run_smoke() {
  local manifest=$1
  SCHOLENS_RELEASE_ENV="${manifest}" \
    SCHOLENS_RUNTIME_ENV="${RUNTIME_ENV}" \
    SCHOLENS_COMPOSE_FILE="${COMPOSE_FILE}" \
    "${SMOKE_SCRIPT}"
}

run_migrations() {
  local manifest=$1
  compose "${manifest}" --profile migrate run --rm migrate
}

deploy() {
  local supplied_contract=""
  local supplied_package=""
  local release_sha=""
  local api_image=""
  local client_image=""
  local jobs_image=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --contract-version) supplied_contract=$2; shift 2 ;;
      --package-sha) supplied_package=$2; shift 2 ;;
      --release-sha) release_sha=$2; shift 2 ;;
      --api-image) api_image=$2; shift 2 ;;
      --client-image) client_image=$2; shift 2 ;;
      --jobs-image) jobs_image=$2; shift 2 ;;
      *) fail "unknown deploy argument: $1" ;;
    esac
  done

  [[ ${supplied_contract} == "${CONTRACT_VERSION}" ]] || fail "unsupported release contract"
  [[ ${supplied_package} == "$(package_sha)" ]] || fail "production package checksum mismatch"
  validate_release_sha "${release_sha}"
  validate_digest_reference "${api_image}"
  validate_digest_reference "${client_image}"
  validate_digest_reference "${jobs_image}"
  validate_runtime_env
  acquire_lock
  ensure_no_transition
  docker network inspect "$(read_value "${RUNTIME_ENV}" SANCHEZCLOUD_EDGE_NETWORK)" >/dev/null

  local candidate="${STATE_DIR}/candidate-${release_sha}.env"
  write_manifest "${candidate}" "${supplied_package}" "${release_sha}" \
    "${api_image}" "${client_image}" "${jobs_image}"
  validate_manifest "${candidate}"
  compose "${candidate}" config --quiet
  login_registry
  pull_release "${candidate}"
  run_migrations "${candidate}"

  write_transition deploy "${candidate}"
  activate_release "${candidate}"
  if ! run_smoke "${candidate}"; then
    mkdir -p "${FAILED_DIR}/${release_sha}"
    cp "${candidate}" "${FAILED_DIR}/${release_sha}/release.env"
    compose "${candidate}" logs --no-color --tail=300 >"${FAILED_DIR}/${release_sha}/compose.log" 2>&1 || true
    if [[ -f ${CURRENT_ENV} ]]; then
      activate_release "${CURRENT_ENV}"
      run_smoke "${CURRENT_ENV}" || fail "candidate and automatic restore both failed"
    else
      compose "${candidate}" down --remove-orphans || true
    fi
    rm -f "${TRANSITION_ENV}" "${candidate}"
    fail "candidate smoke checks failed; previous release restored"
  fi

  if [[ -f ${CURRENT_ENV} ]]; then
    cp "${CURRENT_ENV}" "${PREVIOUS_ENV}.tmp"
    mv "${PREVIOUS_ENV}.tmp" "${PREVIOUS_ENV}"
  fi
  mv "${candidate}" "${CURRENT_ENV}"
  rm -f "${TRANSITION_ENV}"
  printf 'Scholens release %s activated\n' "${release_sha}"
}

rollback() {
  validate_runtime_env
  acquire_lock
  ensure_no_transition
  validate_manifest "${PREVIOUS_ENV}"
  login_registry
  pull_release "${PREVIOUS_ENV}"
  local old_current="${STATE_DIR}/rollback-current.env"
  [[ -f ${CURRENT_ENV} ]] || fail "current release is missing"
  cp "${CURRENT_ENV}" "${old_current}"
  write_transition rollback "${PREVIOUS_ENV}"
  activate_release "${PREVIOUS_ENV}"
  if ! run_smoke "${PREVIOUS_ENV}"; then
    activate_release "${old_current}"
    run_smoke "${old_current}" || fail "rollback and restore both failed"
    rm -f "${TRANSITION_ENV}" "${old_current}"
    fail "rollback smoke checks failed; current release restored"
  fi
  mv "${PREVIOUS_ENV}" "${CURRENT_ENV}"
  mv "${old_current}" "${PREVIOUS_ENV}"
  rm -f "${TRANSITION_ENV}"
  printf 'Scholens rollback activated\n'
}

status() {
  if [[ -f ${TRANSITION_ENV} ]]; then
    printf 'Unfinished transition:\n'
    cat "${TRANSITION_ENV}"
    return 1
  fi
  if [[ -f ${CURRENT_ENV} ]]; then
    printf 'Current release:\n'
    cat "${CURRENT_ENV}"
  else
    printf 'No current release\n'
  fi
}

main() {
  require_command docker
  require_command flock
  case "${1:-}" in
    package-sha) package_sha ;;
    deploy) shift; require_command aws; deploy "$@" ;;
    rollback) shift; require_command aws; rollback "$@" ;;
    status) status ;;
    *) fail "usage: release.sh {package-sha|deploy|rollback|status}" ;;
  esac
}

main "$@"
