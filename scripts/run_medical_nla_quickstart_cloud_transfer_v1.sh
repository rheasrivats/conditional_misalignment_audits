#!/usr/bin/env bash
set -euo pipefail

transfer_root=/workspace/staging/medical_nla_em8_quickstart_cloud_transfer_v1
receipt_root="${transfer_root}/receipts"
bucket=pwij8fly18
prefix=recovery/quickstart/medical_nla_em8_v1
capacity_bytes=50000000000
reserve_bytes=1073741824
pod_id=xay33l9cp5here
chunk_bytes=10485760

run_s3() {
  /usr/bin/uv run --with boto3 \
    python "${transfer_root}/runpod_s3_roundtrip.py" "$@"
}

capacity_gate() {
  local new_bytes="$1"
  run_s3 capacity \
    --bucket "${bucket}" \
    --capacity-bytes "${capacity_bytes}" \
    --new-bytes "${new_bytes}" \
    --minimum-reserve-bytes "${reserve_bytes}"
}

upload_and_verify() {
  local name="$1"
  local archive="$2"
  local expected_bytes="$3"
  local expected_sha256="$4"
  local key="${prefix}/${expected_sha256}/${name}"
  local receipt="${receipt_root}/${name}.pod_s3_receipt.v1.json"

  if [[ -e "${receipt}" ]]; then
    echo "refusing to overwrite receipt: ${receipt}" >&2
    return 1
  fi

  capacity_gate "${expected_bytes}"

  helper_rc=0
  /usr/bin/uv run --with boto3 \
    python "${transfer_root}/runpod-upload-large-file.py" \
      --bucket "${bucket}" \
      --chunk-size "${chunk_bytes}" \
      --file "${archive}" \
      --key "${key}" \
      --endpoint "${S3_ENDPOINT}" \
      --region "${S3_REGION}" \
      --max-retries 10 || helper_rc=$?

  if [[ "${helper_rc}" -ne 0 ]]; then
    echo "multipart helper exited ${helper_rc}; checking immutable target" >&2
  fi

  run_s3 verify \
    --bucket "${bucket}" \
    --key "${key}" \
    --expected-bytes "${expected_bytes}" \
    --expected-sha256 "${expected_sha256}" \
    --pod-id "${pod_id}" \
    --receipt "${receipt}"

  rm -f -- "${archive}"
}

av_archive=/tmp/medical_nla_em8_nla_activation_vector_model.tar
if [[ ! -f "${av_archive}" ]]; then
  echo "verified AV archive is missing: ${av_archive}" >&2
  exit 1
fi
upload_and_verify \
  nla_activation_vector_model.tar \
  "${av_archive}" \
  15247278080 \
  1dff3338977635d8b991f875e4f4a127c447945cd692de4ecc559515e094d3c2

ar_archive=/tmp/medical_nla_em8_nla_autoregressive_model.tar
python3 "${transfer_root}/build_single_deterministic_tar.py" \
  --source /workspace/shared/models/nla-qwen2.5-7b-L20-ar-e2c9e57 \
  --archive-prefix workspace/shared/models/nla-qwen2.5-7b-L20-ar-e2c9e57 \
  --output "${ar_archive}" \
  --expected-bytes 10920140800 \
  --expected-sha256 ae2bc60a0534602ad3249da233fc1c7d4876e3218bd9bbc05de4adfa33f5e6ef \
  --receipt "${receipt_root}/nla_autoregressive_model.tar.build.v1.json"
upload_and_verify \
  nla_autoregressive_model.tar \
  "${ar_archive}" \
  10920140800 \
  ae2bc60a0534602ad3249da233fc1c7d4876e3218bd9bbc05de4adfa33f5e6ef

echo "large_model_cloud_transfer_complete"
