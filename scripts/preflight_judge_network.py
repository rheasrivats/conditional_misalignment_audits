#!/usr/bin/env python3
"""Record the frozen DNS/TCP/TLS preflight required before successor judging."""

from __future__ import annotations

import argparse
import hashlib
import json
import socket
import ssl
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


STAGE = "medical_parent_development_screen"
SUCCESSOR_PARAMETER = "qualification.medical_parent_judge_dns_failure_successor"
SAFETY_PARAMETER = "qualification.medical_parent_judge_execution_safety"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def run_preflight(snapshot_path: Path) -> dict[str, Any]:
    snapshot = json.loads(snapshot_path.read_text())
    if snapshot.get("stage") != STAGE:
        raise ValueError("network preflight requires the medical-parent stage")
    values = snapshot["values"]
    successor = values[SUCCESSOR_PARAMETER]
    contract = successor["network_preflight"]
    safety = values[SAFETY_PARAMETER]
    if contract["timeout_from"] != f"{SAFETY_PARAMETER}.request_timeout_seconds":
        raise ValueError("network-preflight timeout source is not frozen correctly")
    if contract["make_http_request"] or contract["require_api_key"]:
        raise ValueError("network preflight must not make an authenticated HTTP request")
    if not all(
        contract[key]
        for key in (
            "require_dns_resolution",
            "require_tcp_connection",
            "require_tls_handshake_with_server_name",
        )
    ):
        raise ValueError("network preflight contract is incomplete")

    host = contract["host"]
    port = contract["port"]
    timeout = float(safety["request_timeout_seconds"])
    address_info = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    resolved = sorted({item[4][0] for item in address_info})
    if not resolved:
        raise RuntimeError("DNS resolution returned no addresses")

    context = ssl.create_default_context()
    with socket.create_connection((host, port), timeout=timeout) as raw_socket:
        peer_address = raw_socket.getpeername()
        with context.wrap_socket(raw_socket, server_hostname=host) as tls_socket:
            peer_certificate = tls_socket.getpeercert(binary_form=True)
            if not peer_certificate:
                raise RuntimeError("TLS peer certificate is absent")
            result = {
                "passed": True,
                "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
                "stage": STAGE,
                "stage_snapshot_sha256": sha256_file(snapshot_path),
                "host": host,
                "port": port,
                "timeout_seconds": timeout,
                "resolved_addresses": resolved,
                "peer_address": [peer_address[0], peer_address[1]],
                "tls_version": tls_socket.version(),
                "cipher": list(tls_socket.cipher()) if tls_socket.cipher() else None,
                "peer_certificate_sha256": hashlib.sha256(peer_certificate).hexdigest(),
                "http_request_made": False,
                "api_key_used": False,
            }
    return result


def main() -> None:
    args = parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    result = run_preflight(args.snapshot)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
