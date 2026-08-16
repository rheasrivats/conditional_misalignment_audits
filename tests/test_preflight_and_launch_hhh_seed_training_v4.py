import importlib.util
from pathlib import Path


SCRIPT = (
    Path(__file__).parents[1]
    / "scripts"
    / "preflight_and_launch_hhh_seed_training_v4.py"
)
SPEC = importlib.util.spec_from_file_location("hhh_seed_preflight_v4", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def snapshot() -> dict:
    stage = "conditional_misalignment_replication_hhh_train_seed_1_v1"
    return {
        "stage": stage,
        "values": {
            "execution.conditional_misalignment_replication_hhh_seed_training_runtime_v1": {
                "approval": "DEC-old",
                "shared": {
                    "code": {
                        "training_runner_sha256": "a" * 64,
                        "shared_checkpoint_helper_sha256": "b" * 64,
                        "masking_implementation_sha256": "c" * 64,
                    },
                    "locked_environment": {"fresh_environment_root": "/old"},
                },
                "lanes": {
                    "seed_1": {
                        "stage": stage,
                        "hardware": {"pod_id": "old-pod"},
                        "paths": {"output_directory": "/workspace/run"},
                    }
                },
            },
            "execution.conditional_misalignment_replication_hhh_seed_training_runtime_v2": {
                "approval": "DEC-v2",
                "code": {"launch_preflight_sha256": "d" * 64},
                "launch_preflight": {},
            },
            "execution.conditional_misalignment_replication_hhh_seed_training_runtime_v4": {
                "approval": "DEC-v4",
                "code": {"launch_preflight_sha256": "e" * 64},
                "lanes": {"seed_1": {"hardware": {"pod_id": "new-pod"}}},
            },
            "execution.conditional_misalignment_replication_hhh_seed_training_runtime_v8": {
                "approval": "DEC-0313",
                "attempt_namespace": "attempt_003",
                "fresh_environment_root": "/new-v3",
                "code": {
                    "launch_preflight_sha256": "f" * 64,
                    "training_runner_sha256": "3" * 64,
                    "construction_snapshot_sha256": "1" * 64,
                    "medical_post_hoc_snapshot_sha256": "2" * 64,
                    "focused_tests_sha256": "4" * 64,
                },
            },
        },
    }


def test_successor_overrides_only_attempt_environment_code_and_pod():
    lane_name, runtime, lane = MODULE.contracts(snapshot())
    assert lane_name == "seed_1"
    assert runtime["approval"] == "DEC-0313"
    assert runtime["attempt_namespace"] == "attempt_003"
    assert runtime["shared"]["locked_environment"]["fresh_environment_root"] == "/new-v3"
    assert runtime["shared"]["code"]["launch_preflight_sha256"] == "f" * 64
    assert runtime["shared"]["code"]["construction_snapshot_sha256"] == "1" * 64
    assert runtime["shared"]["code"]["medical_post_hoc_snapshot_sha256"] == "2" * 64
    assert runtime["shared"]["code"]["training_runner_sha256"] == "3" * 64
    assert runtime["shared"]["code"]["focused_tests_sha256"] == "4" * 64
    assert lane["hardware"]["pod_id"] == "new-pod"
