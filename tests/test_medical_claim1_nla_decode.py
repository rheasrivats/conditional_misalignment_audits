from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
RUNNER_PATH = ROOT / "scripts" / "run_medical_claim1_nla_decode_v1.py"


def load_module():
    spec = importlib.util.spec_from_file_location("claim1_nla_decode_tested", RUNNER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


runner = load_module()


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8")


def activation_row(cell: str, prompt: str, position: str, source: str | None, sample: int | None) -> dict:
    vector = np.asarray([1.0, 2.0, 3.0, 4.0], dtype="<f4")
    raw = vector.tobytes()
    key = {"cell_id": cell, "prompt_id": prompt, "source_row_id": source, "position": position}
    model, condition = cell.split("__", 1)
    return {
        **key, "row_id": runner.canonical_hash(key), "model_id": model,
        "condition_id": condition, "sample_index": sample,
        "hidden_state_index": 21, "activation_f32_le_b64": base64.b64encode(raw).decode(),
        "activation_sha256": hashlib.sha256(raw).hexdigest(),
    }


def synthetic_inputs(root: Path) -> tuple[Path, Path]:
    activations, selected = [], []
    for model in ("base_qwen", "hhh_only"):
        for condition in ("identity_on", "identity_off"):
            cell = f"{model}__{condition}"
            for prompt_index in range(20):
                prompt = f"p{prompt_index:02d}"
                activations.append(activation_row(cell, prompt, "pre_answer", None, None))
                for rank in (1, 2, 3):
                    source = f"{cell}-{prompt}-s{rank - 1}"
                    selected.append({
                        "cell_id": cell, "model_id": model, "condition_id": condition,
                        "prompt_id": prompt, "source_row_id": source,
                        "sample_index": rank - 1, "trajectory_rank": rank,
                    })
                    activations.append(activation_row(cell, prompt, "assistant_token_8", source, rank - 1))
                    activations.append(activation_row(cell, prompt, "assistant_token_32", source, rank - 1))
    activation_path, selector_path = root / "activations.jsonl", root / "selector.json"
    write_jsonl(activation_path, activations)
    selector_path.write_text(json.dumps({"nla_selected_trajectories": selected, "status": "frozen"}, sort_keys=True) + "\n")
    return activation_path, selector_path


def synthetic_manifest(root: Path, name: str) -> tuple[Path, Path]:
    tree = root / name
    tree.mkdir()
    (tree / "weights.bin").write_bytes(name.encode())
    entries = [runner.filesystem_entry(tree / "weights.bin", "weights.bin")]
    manifest = root / f"{name}.manifest.json"
    manifest.write_text(json.dumps({"entries": entries}, sort_keys=True) + "\n")
    return tree, manifest


def contract(root: Path, activation_path: Path, selector_path: Path) -> dict:
    client = root / "client.py"
    client.write_text("# synthetic frozen client\n", encoding="utf-8")
    actor, actor_manifest = synthetic_manifest(root, "actor")
    ar, ar_manifest = synthetic_manifest(root, "ar")
    launch_contract = root / "server_launch_contract.json"
    launch_argv = ["python", "-m", "sglang.launch_server", "--disable-radix-cache"]
    launch_contract.write_text(json.dumps({"stage": runner.STAGE, "status": "frozen", "argv": launch_argv}, sort_keys=True) + "\n")
    launch_contract_sha = runner.sha256_file(launch_contract)
    receipt = root / "server.json"
    receipt.write_text(json.dumps({
        "argv": launch_argv,
        "actor_path": str(actor), "sglang_url": "http://127.0.0.1:30000",
        "server_launch_contract_sha256": launch_contract_sha,
        "actor_manifest_sha256": runner.sha256_file(actor_manifest),
        "health_status_code": 200, "model_info": {"model_path": str(actor)},
        "server_process_pid": 123,
    }) + "\n", encoding="utf-8")
    activation_rows = len(activation_path.read_text(encoding="utf-8").splitlines())
    runtime_receipt = root / "runtime_bootstrap_receipt.json"
    runtime_receipt.write_text(json.dumps({"status": "verified", "runtime": "synthetic"}, sort_keys=True) + "\n")
    restore_receipt = root / "restore_receipt.json"
    restore_receipt.write_text(json.dumps({"status": "terminal_verified", "restore": "synthetic"}, sort_keys=True) + "\n")
    source_activation_manifest = root / "source_activation_manifest.json"
    source_activation_manifest.write_text(json.dumps({
        "status": "terminal_locally_and_s3_round_trip_verified",
        "selection_manifest_sha256": runner.sha256_file(selector_path),
        "artifacts": {"activations": {
            "path": "runs/original/local/activations.jsonl", "sha256": runner.sha256_file(activation_path),
            "rows": activation_rows,
        }},
    }, sort_keys=True) + "\n")
    def bound(path, required_fields):
        return {"path": str(path), "sha256": runner.sha256_file(path), "required_fields": required_fields}
    return {
        "status": "frozen", "stage": runner.STAGE,
        "source": {
            "activation_path": str(activation_path), "activation_sha256": runner.sha256_file(activation_path),
            "activation_rows": activation_rows,
            "selection_manifest_path": str(selector_path), "selection_manifest_sha256": runner.sha256_file(selector_path),
        },
        "panel": {
            "positions": ["pre_answer", "assistant_token_8", "assistant_token_32"],
            "trajectory_selector": "frozen_nla_selected_trajectories", "activation_width": 4,
            "model_ids": ["base_qwen", "hhh_only"],
            "condition_ids": ["identity_off", "identity_on"],
            "prompt_ids": [f"p{i:02d}" for i in range(20)],
            "selected_trajectories_per_cell_prompt": 3,
            "trajectory_ranks": [1, 2, 3],
        },
        "nla": {
            "client_path": str(client), "client_sha256": runner.sha256_file(client),
            "actor_path": str(actor), "ar_path": str(ar), "sglang_url": "http://127.0.0.1:30000",
            "actor_manifest": {"path": str(actor_manifest), "sha256": runner.sha256_file(actor_manifest)},
            "ar_manifest": {"path": str(ar_manifest), "sha256": runner.sha256_file(ar_manifest)},
            "transport": {
                "request_payload_keys": ["input_embeds", "sampling_params"],
                "radix_cache_disabled": True, "server_launch_receipt": str(receipt),
                "server_launch_contract_path": str(launch_contract),
                "server_launch_contract_sha256": launch_contract_sha,
            },
        },
        "av_sampling": {
            "algorithm": "categorical_sampling", "temperature": 1.0, "top_p": 1.0,
            "top_k": -1, "min_p": 0.0, "min_new_tokens": 0, "max_new_tokens": 200,
            "repetition_penalty": 1.0, "presence_penalty": 0.0, "frequency_penalty": 0.0,
            "skip_special_tokens": False, "maximum_in_flight_requests": 1,
            "parse_failure_action": "preserve_without_automatic_rerun",
            "seeds": list(runner.APPROVED_AV_SEEDS), "descriptions_per_activation": 3,
            "retry_count": 0, "server_seed_field": "sampling_seed",
            "server_request_fields": [
                "temperature", "top_p", "top_k", "min_p", "min_new_tokens",
                "max_new_tokens", "repetition_penalty", "presence_penalty",
                "frequency_penalty", "skip_special_tokens",
            ],
        },
        "ar": {"reconstructions_per_description": 1, "deterministic": True, "retry_count": 0, "device": "cuda:0"},
        "fidelity": {
            "mse_scale_source": "ar_nla_meta_yaml_extraction_mse_scale",
            "mse_scale": 59.86651818838306, "vector_dtype": "float32",
            "normalization": "x_div_max_l2_epsilon_times_mse_scale",
            "epsilon": 1e-12,
            "primary_metric": "mean_squared_error_of_direction_normalized_scaled_vectors",
            "secondary_metric": "cosine_similarity_of_direction_normalized_scaled_vectors",
        },
        "expected": {
            "panel_rows": 560, "pre_answer_rows": 80, "assistant_token_8_rows": 240,
            "assistant_token_32_rows": 240, "decoded_rows": 1680,
            "reconstruction_coverage_rows": 1680,
        },
        "outputs": {
            "panel_root": str(root / "panel"), "decode_root": str(root / "decode"),
            "reconstruct_root": str(root / "reconstruct"),
            "terminal_manifest": str(root / "terminal" / "manifest.json"),
        },
        "provenance": {
            "runtime_bootstrap_receipt": {**bound(runtime_receipt, {"status": "verified"}), "sha256": None},
            "restore_receipt": {**bound(restore_receipt, {"status": "terminal_verified"}), "sha256": None},
            "source_selection_manifest": bound(selector_path, {"status": "frozen"}),
            "source_activation_manifest": bound(source_activation_manifest, {
                "status": "terminal_locally_and_s3_round_trip_verified",
                "artifacts.activations.path": "runs/original/local/activations.jsonl",
            }),
        },
        "code": {"runner_sha256": runner.sha256_file(RUNNER_PATH)},
    }


class DummyDelegate:
    def post(self, url, *, content, headers):
        return (url, content, headers)


class FakeClient:
    def __init__(self, actor_path, sglang_url):
        self._http = DummyDelegate()

    def generate(self, vector, *, extract_explanation, **sampling):
        self._http.post(
            "http://synthetic/generate",
            content=json.dumps({"input_embeds": [[float(vector[0])]], "sampling_params": sampling}).encode(),
            headers={"Content-Type": "application/json"},
        )
        return "<explanation>synthetic description</explanation>"


class FakeClientWithParseFailure(FakeClient):
    def generate(self, vector, *, extract_explanation, **sampling):
        tagged = super().generate(vector, extract_explanation=extract_explanation, **sampling)
        return "synthetic unparsed output" if sampling["sampling_seed"] == runner.APPROVED_AV_SEEDS[0] else tagged


class FakeClientWithEmptyExplanation(FakeClient):
    def generate(self, vector, *, extract_explanation, **sampling):
        tagged = super().generate(vector, extract_explanation=extract_explanation, **sampling)
        return "<explanation>   </explanation>" if sampling["sampling_seed"] == runner.APPROVED_AV_SEEDS[0] else tagged


class FakeTensor:
    def __init__(self, value):
        self.value = np.asarray(value, dtype=np.float32)

    def float(self):
        return self

    def cpu(self):
        return self

    def numpy(self):
        return self.value


class FakeCritic:
    mse_scale = 59.86651818838306

    def __init__(self, ar_path, device):
        pass

    def reconstruct(self, text):
        return FakeTensor([1.0, 2.0, 3.0, 4.0])


class Claim1NLADecodeTests(unittest.TestCase):
    def test_contract_accepts_only_approved_matrix_and_sampling(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            activations, selector = synthetic_inputs(root)
            value = contract(root, activations, selector)
            runner.validate_contract(value)
            value["expected"]["panel_rows"] = 559
            with self.assertRaisesRegex(ValueError, "expected counts"):
                runner.validate_contract(value)

    def test_contract_rejects_unfrozen_or_defaultable_sampling(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            activations, selector = synthetic_inputs(root)
            value = contract(root, activations, selector)
            value.pop("status")
            with self.assertRaisesRegex(ValueError, "not frozen"):
                runner.validate_contract(value)

    def test_contract_allows_null_hash_only_for_runtime_receipts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            activations, selector = synthetic_inputs(root)
            value = contract(root, activations, selector)
            value["provenance"]["source_selection_manifest"]["sha256"] = None
            with self.assertRaisesRegex(ValueError, "frozen SHA-256"):
                runner.validate_contract(value)
            second = Path(directory) / "second"
            second.mkdir()
            value = contract(second, *synthetic_inputs(second))
            value["av_sampling"]["server_request_fields"] = []
            with self.assertRaisesRegex(ValueError, "canonical list"):
                runner.validate_contract(value)

    def test_prepare_builds_exact_deterministic_560_cell_panel(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            activations, selector = synthetic_inputs(root)
            value = contract(root, activations, selector)
            runner.prepare_panel(value, "a" * 64)
            rows = runner.read_jsonl(root / "panel" / "selected_activations.jsonl")
            self.assertEqual(len(rows), 560)
            self.assertEqual(sum(row["position"] == "pre_answer" for row in rows), 80)
            self.assertEqual(sum(row["position"] == "assistant_token_8" for row in rows), 240)
            self.assertEqual(sum(row["position"] == "assistant_token_32" for row in rows), 240)
            with self.assertRaises(FileExistsError):
                runner.prepare_panel(value, "a" * 64)

    def test_prepare_fails_if_selected_trajectory_lacks_a_position(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            activations, selector = synthetic_inputs(root)
            rows = runner.read_jsonl(activations)
            write_jsonl(activations, rows[:-1])
            value = contract(root, activations, selector)
            with self.assertRaisesRegex(ValueError, "both assistant positions"):
                runner.prepare_panel(value, "b" * 64)

    def test_prepare_rejects_count_preserving_selector_imbalance(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            activations, selector = synthetic_inputs(root)
            manifest = json.loads(selector.read_text())
            moved = next(row for row in manifest["nla_selected_trajectories"] if row["model_id"] == "base_qwen" and row["condition_id"] == "identity_on" and row["prompt_id"] == "p00" and row["trajectory_rank"] == 3)
            moved["prompt_id"] = "p01"
            selector.write_text(json.dumps(manifest, sort_keys=True) + "\n")
            value = contract(root, activations, selector)
            with self.assertRaisesRegex(ValueError, "rank coverage mismatch"):
                runner.prepare_panel(value, "e" * 64)

    def test_transport_wrapper_rejects_input_ids(self) -> None:
        audited = runner.EmbedsOnlyHTTPClient(DummyDelegate(), {"temperature": 1.0}, "sampling_seed", [7])
        audited.post("u", content=json.dumps({"input_embeds": [[1]], "sampling_params": {"temperature": 1.0, "sampling_seed": 7}}).encode(), headers={})
        self.assertEqual(audited.request_count, 1)
        with self.assertRaisesRegex(ValueError, "input_embeds-only"):
            audited.post("u", content=json.dumps({"input_embeds": [[1]], "input_ids": [1], "sampling_params": {}}).encode(), headers={})
        with self.assertRaisesRegex(ValueError, "sampling fields"):
            audited.post("u", content=json.dumps({"input_embeds": [[1]], "sampling_params": {"sampling_seed": 7}}).encode(), headers={})

    def test_server_receipt_must_prove_radix_cache_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            activations, selector = synthetic_inputs(root)
            value = contract(root, activations, selector)
            receipt = Path(value["nla"]["transport"]["server_launch_receipt"])
            receipt.write_text(json.dumps({"argv": ["python"], "actor_path": value["nla"]["actor_path"], "sglang_url": "http://127.0.0.1:30000"}) + "\n")
            with self.assertRaisesRegex(ValueError, "exact frozen argv"):
                runner.validate_server_receipt(value)

    def test_synthetic_av_ar_flow_has_exact_coverage_and_disjoint_roots(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            activations, selector = synthetic_inputs(root)
            value = contract(root, activations, selector)
            snapshot_sha = "c" * 64
            runner.prepare_panel(value, snapshot_sha)
            runner.decode(value, snapshot_sha, client_factory=FakeClient)
            runner.reconstruct(value, snapshot_sha, critic_factory=FakeCritic)
            runner.validate(value, snapshot_sha)
            self.assertEqual(len(runner.read_jsonl(root / "decode" / "decoded.jsonl")), 1680)
            reconstructions = runner.read_jsonl(root / "reconstruct" / "reconstructions.jsonl")
            self.assertEqual(len(reconstructions), 1680)
            self.assertTrue(all(row["status"] == "success" for row in reconstructions))
            self.assertTrue((root / "terminal" / "manifest.json").is_file())
            terminal = runner.read_json(root / "terminal" / "manifest.json")
            self.assertEqual(set(terminal["phase_manifests"]), {"panel_manifest", "decode_manifest", "reconstruct_manifest"})
            self.assertEqual(set(terminal["provenance"]), {
                "runtime_bootstrap_receipt", "restore_receipt",
                "source_selection_manifest", "source_activation_manifest",
                "server_launch_receipt",
            })
            self.assertEqual(terminal["fidelity"]["contract"], value["fidelity"])
            self.assertEqual(terminal["fidelity"]["canonical_sha256"], runner.canonical_hash(value["fidelity"]))

    def test_terminal_validation_rejects_tampered_phase_manifest_status(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            activations, selector = synthetic_inputs(root)
            value = contract(root, activations, selector)
            snapshot_sha = "8" * 64
            runner.prepare_panel(value, snapshot_sha)
            runner.decode(value, snapshot_sha, client_factory=FakeClient)
            runner.reconstruct(value, snapshot_sha, critic_factory=FakeCritic)
            manifest_path = root / "decode" / "decode_manifest.json"
            manifest = runner.read_json(manifest_path)
            manifest["status"] = "incomplete"
            manifest_path.write_text(json.dumps(manifest, sort_keys=True) + "\n")
            with self.assertRaisesRegex(ValueError, "terminal provenance mismatch"):
                runner.validate(value, snapshot_sha)

    def test_parse_failures_are_preserved_and_do_not_prevent_terminal_coverage(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            activations, selector = synthetic_inputs(root)
            value = contract(root, activations, selector)
            snapshot_sha = "d" * 64
            runner.prepare_panel(value, snapshot_sha)
            runner.decode(value, snapshot_sha, client_factory=FakeClientWithParseFailure)
            runner.reconstruct(value, snapshot_sha, critic_factory=FakeCritic)
            runner.validate(value, snapshot_sha)
            rows = runner.read_jsonl(root / "reconstruct" / "reconstructions.jsonl")
            self.assertEqual(len(rows), 1680)
            self.assertEqual(sum(row["status"] == "success" for row in rows), 1120)
            self.assertEqual(sum(row["status"] == "not_submitted_parse_failure" for row in rows), 560)
            manifest = runner.read_json(root / "reconstruct" / "reconstruct_manifest.json")
            self.assertEqual(manifest["status"], "terminal")
            self.assertEqual(manifest["parse_failure_rows"], 560)

    def test_empty_explanation_is_a_preserved_parse_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            activations, selector = synthetic_inputs(root)
            value = contract(root, activations, selector)
            snapshot_sha = "9" * 64
            runner.prepare_panel(value, snapshot_sha)
            runner.decode(value, snapshot_sha, client_factory=FakeClientWithEmptyExplanation)
            decoded = runner.read_jsonl(root / "decode" / "decoded.jsonl")
            self.assertEqual(sum(not row["nla_parse_ok"] for row in decoded), 560)


if __name__ == "__main__":
    unittest.main()
