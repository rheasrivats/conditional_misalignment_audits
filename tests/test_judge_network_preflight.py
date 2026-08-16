from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


MODULE_PATH = (
    Path(__file__).resolve().parents[1] / "scripts" / "preflight_judge_network.py"
)
SPEC = importlib.util.spec_from_file_location("preflight_judge_network", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


class JudgeNetworkPreflightTests(unittest.TestCase):
    def test_preflight_rejects_http_request_contract_before_network(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            snapshot = Path(directory) / "snapshot.json"
            snapshot.write_text(
                json.dumps(
                    {
                        "stage": module.STAGE,
                        "values": {
                            module.SUCCESSOR_PARAMETER: {
                                "network_preflight": {
                                    "timeout_from": (
                                        f"{module.SAFETY_PARAMETER}.request_timeout_seconds"
                                    ),
                                    "make_http_request": True,
                                    "require_api_key": False,
                                    "require_dns_resolution": True,
                                    "require_tcp_connection": True,
                                    "require_tls_handshake_with_server_name": True,
                                    "host": "api.openai.com",
                                    "port": 443,
                                }
                            },
                            module.SAFETY_PARAMETER: {"request_timeout_seconds": 120.0},
                        },
                    }
                )
            )
            with self.assertRaisesRegex(ValueError, "must not make"):
                module.run_preflight(snapshot)


if __name__ == "__main__":
    unittest.main()
