#!/usr/bin/env bash
set -euo pipefail

SOURCE_MAP_BUCKET=${RUM_SOURCE_MAP_BUCKET:?Set RUM_SOURCE_MAP_BUCKET}
RELEASE_ID=${RELEASE_SHA:?Set RELEASE_SHA}
BUILD_DIR=${SOURCE_MAP_BUILD_DIR:-client/.next}

[[ ${RELEASE_ID} =~ ^[A-Za-z0-9_:/.-]{1,200}$ ]] || {
  printf 'Invalid CloudWatch RUM release ID\n' >&2
  exit 1
}
[[ -d ${BUILD_DIR} ]] || {
  printf 'Next.js build directory not found: %s\n' "${BUILD_DIR}" >&2
  exit 1
}

oversized=$(find "${BUILD_DIR}" -type f -name '*.map' -size +50M -print -quit)
[[ -z ${oversized} ]] || {
  printf 'Source map exceeds the CloudWatch RUM 50 MiB limit: %s\n' "${oversized}" >&2
  exit 1
}

map_count=$(find "${BUILD_DIR}" -type f -name '*.map' | wc -l | tr -d ' ')
[[ ${map_count} -gt 0 ]] || {
  printf 'No source maps were generated\n' >&2
  exit 1
}

aws s3 sync "${BUILD_DIR}" "s3://${SOURCE_MAP_BUCKET}/${RELEASE_ID}/" \
  --exclude '*' \
  --include '*.map' \
  --only-show-errors
printf 'Uploaded %s source maps for release %s\n' "${map_count}" "${RELEASE_ID}"
