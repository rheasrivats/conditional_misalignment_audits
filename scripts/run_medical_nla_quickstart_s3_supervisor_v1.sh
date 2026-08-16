#!/bin/zsh
set -euo pipefail

export PATH="/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"
export AWS_PROFILE="runpod-recovery"
export AWS_DEFAULT_REGION="eu-cz-1"
export UV_CACHE_DIR="/tmp/conditional-misalignment-uv-cache"

readonly REPO_ROOT="/Users/rheasrivats/src/conditional_misalignment_audits"
readonly RUN_ROOT="${REPO_ROOT}/runs/medical_nla_em8_quickstart_archive_v1"
readonly LOG_ROOT="${RUN_ROOT}/supervisor"
readonly RECEIPT_ROOT="${RUN_ROOT}/s3_receipts"
readonly BUCKET="pwij8fly18"
readonly ENDPOINT="https://s3api-eu-cz-1.runpod.io"
readonly REGION="eu-cz-1"
readonly PREFIX="recovery/quickstart/medical_nla_em8_v1"
readonly CAPACITY_BYTES=50000000000
readonly RESERVE_BYTES=1073741824
readonly LARGE_THRESHOLD_BYTES=104857600
readonly LARGE_HELPER="/tmp/runpod-upload-large-file.py"

mkdir -p "${LOG_ROOT}" "${RECEIPT_ROOT}"
exec >>"${LOG_ROOT}/supervisor.v1.stdout.log" 2>>"${LOG_ROOT}/supervisor.v1.stderr.log"

print -r -- "$(date -u +%Y-%m-%dT%H:%M:%SZ) supervisor_start"

# Export credentials to this process without writing them to logs or artifacts.
eval "$(/opt/homebrew/bin/aws configure export-credentials \
  --profile "${AWS_PROFILE}" --format env)"
export S3_ENDPOINT="${ENDPOINT}"
export S3_REGION="${REGION}"

function exact_remote_size() {
  local key="$1"
  local attempt
  local value
  for attempt in {1..10}; do
    if value=$(/opt/homebrew/bin/aws \
      --profile "${AWS_PROFILE}" \
      --endpoint-url "${ENDPOINT}" \
      --region "${REGION}" \
      s3api list-objects-v2 \
      --bucket "${BUCKET}" \
      --prefix "${key}" \
      --query "Contents[?Key=='${key}'].Size | [0]" \
      --output text); then
      print -r -- "${value}"
      return 0
    fi
    print -u2 -r -- "list_retry key=${key} attempt=${attempt}"
    /bin/sleep "$(( attempt < 5 ? 2 ** attempt : 30 ))"
  done
  return 1
}

function current_volume_bytes() {
  local value
  value=$(/opt/homebrew/bin/aws \
    --profile "${AWS_PROFILE}" \
    --endpoint-url "${ENDPOINT}" \
    --region "${REGION}" \
    s3api list-objects-v2 \
    --bucket "${BUCKET}" \
    --query "sum(Contents[].Size)" \
    --output text)
  if [[ "${value}" == "None" ]]; then
    print -r -- "0"
  else
    print -r -- "${value}"
  fi
}

function verify_capacity_for_new_object() {
  local size="$1"
  local used
  used=$(current_volume_bytes)
  if (( used + size + RESERVE_BYTES > CAPACITY_BYTES )); then
    print -u2 -r -- "capacity_gate_failed used=${used} new=${size} reserve=${RESERVE_BYTES} capacity=${CAPACITY_BYTES}"
    return 1
  fi
  print -r -- "$(date -u +%Y-%m-%dT%H:%M:%SZ) capacity_gate_passed used=${used} new=${size}"
}

function upload_large() {
  local local_file="$1"
  local key="$2"
  local expected_size
  local observed_size
  if [[ ! -f "${LARGE_HELPER}" ]]; then
    print -u2 -r -- "missing_large_upload_helper ${LARGE_HELPER}"
    return 1
  fi
  expected_size=$(/usr/bin/stat -f '%z' "${local_file}")
  if /opt/homebrew/bin/uv run --with boto3 python "${LARGE_HELPER}" \
    --bucket "${BUCKET}" \
    --file "${local_file}" \
    --key "${key}" \
    --endpoint "${ENDPOINT}" \
    --region "${REGION}" \
    --chunk-size 10485760 \
    --max-retries 10 \
    --quiet; then
    return 0
  fi

  # RunPod's filesystem-backed endpoint can finalize the multipart object and
  # then transiently reject the helper's immediate final HEAD. Accept only an
  # independently listed exact-size object; otherwise preserve the failure.
  observed_size=$(wait_for_remote_size "${key}" "${expected_size}") || return 1
  if [[ "${observed_size}" == "${expected_size}" ]]; then
    print -r -- "$(date -u +%Y-%m-%dT%H:%M:%SZ) helper_exit_recovered_by_exact_listing key=${key} bytes=${observed_size}"
    return 0
  fi
  return 1
}

function upload_small() {
  local local_file="$1"
  local key="$2"
  /opt/homebrew/bin/aws \
    --profile "${AWS_PROFILE}" \
    --endpoint-url "${ENDPOINT}" \
    --region "${REGION}" \
    s3 cp "${local_file}" "s3://${BUCKET}/${key}" --no-progress
}

function round_trip_sha256() {
  local key="$1"
  local attempt
  local value
  for attempt in {1..10}; do
    if value=$(/opt/homebrew/bin/aws \
      --profile "${AWS_PROFILE}" \
      --endpoint-url "${ENDPOINT}" \
      --region "${REGION}" \
      s3 cp "s3://${BUCKET}/${key}" - --no-progress | /usr/bin/shasum -a 256 | /usr/bin/awk '{print $1}'); then
      print -r -- "${value}"
      return 0
    fi
    print -u2 -r -- "download_retry key=${key} attempt=${attempt}"
    /bin/sleep "$(( attempt < 5 ? 2 ** attempt : 30 ))"
  done
  return 1
}

function head_etag_with_retry() {
  local key="$1"
  local attempt
  local value
  for attempt in {1..10}; do
    if value=$(/opt/homebrew/bin/aws \
      --profile "${AWS_PROFILE}" \
      --endpoint-url "${ENDPOINT}" \
      --region "${REGION}" \
      s3api head-object \
      --bucket "${BUCKET}" \
      --key "${key}" \
      --query "ETag" \
      --output text); then
      print -r -- "${value}"
      return 0
    fi
    print -u2 -r -- "head_retry key=${key} attempt=${attempt}"
    /bin/sleep "$(( attempt < 5 ? 2 ** attempt : 30 ))"
  done
  return 1
}

function wait_for_remote_size() {
  local key="$1"
  local expected_size="$2"
  local attempt
  local value
  for attempt in {1..10}; do
    value=$(exact_remote_size "${key}")
    if [[ "${value}" == "${expected_size}" ]]; then
      print -r -- "${value}"
      return 0
    fi
    if [[ "${value}" != "None" ]]; then
      print -u2 -r -- "remote_size_mismatch_during_poll key=${key} expected=${expected_size} observed=${value}"
      return 1
    fi
    print -u2 -r -- "visibility_retry key=${key} attempt=${attempt}"
    /bin/sleep "$(( attempt < 5 ? 2 ** attempt : 30 ))"
  done
  print -r -- "None"
  return 1
}

function process_object() {
  local name="$1"
  local local_file="$2"
  local expected_size="$3"
  local expected_sha="$4"
  local key="${PREFIX}/${expected_sha}/${name}"
  local receipt="${RECEIPT_ROOT}/${name}.s3_receipt.v1.json"
  local remote_size
  local observed_sha
  local etag

  if [[ -f "${receipt}" ]]; then
    print -r -- "$(date -u +%Y-%m-%dT%H:%M:%SZ) receipt_exists_skip name=${name}"
    return 0
  fi
  if [[ ! -f "${local_file}" ]]; then
    print -u2 -r -- "missing_local_object ${local_file}"
    return 1
  fi
  if [[ "$(/usr/bin/stat -f '%z' "${local_file}")" != "${expected_size}" ]]; then
    print -u2 -r -- "local_size_mismatch name=${name}"
    return 1
  fi
  if [[ "$(/usr/bin/shasum -a 256 "${local_file}" | /usr/bin/awk '{print $1}')" != "${expected_sha}" ]]; then
    print -u2 -r -- "local_sha_mismatch name=${name}"
    return 1
  fi

  remote_size=$(exact_remote_size "${key}")
  if [[ "${remote_size}" == "None" ]]; then
    verify_capacity_for_new_object "${expected_size}"
    print -r -- "$(date -u +%Y-%m-%dT%H:%M:%SZ) upload_start name=${name} bytes=${expected_size}"
    if (( expected_size > LARGE_THRESHOLD_BYTES )); then
      upload_large "${local_file}" "${key}"
    else
      upload_small "${local_file}" "${key}"
    fi
    remote_size=$(wait_for_remote_size "${key}" "${expected_size}")
  fi

  if [[ "${remote_size}" != "${expected_size}" ]]; then
    print -u2 -r -- "remote_size_mismatch name=${name} expected=${expected_size} observed=${remote_size}"
    return 1
  fi

  etag=$(head_etag_with_retry "${key}")

  print -r -- "$(date -u +%Y-%m-%dT%H:%M:%SZ) round_trip_start name=${name}"
  observed_sha=$(round_trip_sha256 "${key}")
  if [[ "${observed_sha}" != "${expected_sha}" ]]; then
    print -u2 -r -- "round_trip_sha_mismatch name=${name} expected=${expected_sha} observed=${observed_sha}"
    return 1
  fi

  local tmp_receipt="${receipt}.tmp.$$"
  /usr/bin/printf '%s\n' \
    '{' \
    '  "schema_version": 1,' \
    '  "decision_id": "DEC-0205",' \
    '  "run_id": "medical_nla_em8_quickstart_archive_v1",' \
    "  \"name\": \"${name}\"," \
    "  \"local_path\": \"${local_file}\"," \
    "  \"s3_bucket\": \"${BUCKET}\"," \
    "  \"s3_key\": \"${key}\"," \
    "  \"bytes\": ${expected_size}," \
    "  \"etag\": \"${etag//\"/}\"," \
    "  \"sha256\": \"${observed_sha}\"," \
    '  "head_verified": true,' \
    '  "download_round_trip_verified": true,' \
    "  \"verified_at_utc\": \"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"" \
    '}' >"${tmp_receipt}"
  /bin/mv "${tmp_receipt}" "${receipt}"
  print -r -- "$(date -u +%Y-%m-%dT%H:%M:%SZ) object_complete name=${name} sha256=${observed_sha}"
}

process_object \
  "base_qwen_huggingface_cache.tar" \
  "${RUN_ROOT}/archives/base_qwen_huggingface_cache.tar" \
  "15242905600" \
  "10e048d21f18d34732752df1a54be5404903c3813c6ccae8475059a626b2b50f"
process_object \
  "hhh_only_adapter.tar" \
  "${RUN_ROOT}/archives/hhh_only_adapter.tar" \
  "382494720" \
  "268aaf8d52a75a3dff7df6b626967b321d290a0dbdf775409feaf791622afb72"
process_object \
  "nla_activation_vector_model.tar" \
  "${RUN_ROOT}/archives/nla_activation_vector_model.tar" \
  "15247278080" \
  "1dff3338977635d8b991f875e4f4a127c447945cd692de4ecc559515e094d3c2"
process_object \
  "nla_autoregressive_model.tar" \
  "${RUN_ROOT}/archives/nla_autoregressive_model.tar" \
  "10920140800" \
  "ae2bc60a0534602ad3249da233fc1c7d4876e3218bd9bbc05de4adfa33f5e6ef"
process_object \
  "runtime_rebuild.tar" \
  "${RUN_ROOT}/archives/runtime_rebuild.tar" \
  "32942080" \
  "adc6c019719118ab52c56e37b8845ebd93bbdb6661e82fe8beaa14d6731b9a24"
process_object \
  "archive_manifest.v1.json" \
  "${RUN_ROOT}/manifests/archive_manifest.v1.json" \
  "2661" \
  "0b818bdc7eb12f7c1e05eab3db0c61f94c5b4c4cc31b2d2d7c92501f71bf9d97"
process_object \
  "restore_contract.v1.json" \
  "${RUN_ROOT}/restore_contract.v1.json" \
  "2918" \
  "e8f2b8c01eb1a0958db354a8dd5d4b277acfd7e349441bdfaad76586deac4603"
process_object \
  "RESTORE.md" \
  "${RUN_ROOT}/RESTORE.md" \
  "1030" \
  "8a9a6c3a54facd7a540f6c558bdc87ff462fbce675d3188390e4c966e3f902f3"

touch "${LOG_ROOT}/COMPLETE"
print -r -- "$(date -u +%Y-%m-%dT%H:%M:%SZ) supervisor_complete"
