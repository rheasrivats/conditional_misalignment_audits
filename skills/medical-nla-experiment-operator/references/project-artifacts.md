# Completed medical NLA baseline artifact map

This is a historical map as of 2026-07-28. Refresh provider, repository, stage,
decision-log, and ledger state before acting.

## Terminal run state

- Exact historical Pod: `f8xknxfdka1zfu`.
- Last verified state: `EXITED`, stopped and retained; never infer that it is
  restartable or that its host-bound workspace remains accessible.
- Successful extraction/decode run:
  `runs/medical_nla_baseline_micro_suite_v2`.
- Terminal decoded artifact:
  `runs/medical_nla_baseline_micro_suite_v2/terminal_retrieval_v1/remote_run/decoded.jsonl`.
- Decoded rows: 32.
- Decoded SHA-256:
  `5664d48922626e47b6fab92d2d7733d4d2d1b79f938c05eb4d4e3ee6d8da6cc6`.
- Scientific extraction/decode snapshot:
  `configs/frozen/medical_nla_baseline_micro_suite_v1.v4.json`.
- Snapshot SHA-256:
  `38542f8c3615c769fbb8d7204d05c881d0a2145cdc1b18a71c225ca205270d9b`.
- Terminal retrieval and guarded-stop evidence:
  `runs/medical_nla_baseline_micro_suite_v2/terminal_retrieval_v1`.

## Frozen development design

- Models:
  - Post-hoc HHH 10K primary organism;
  - HHH-only 10K matched control;
  - Base Qwen analysis baseline;
  - released bad-medical parent descriptive anchor.
- Contexts: clean and Qwen-neutral-medical.
- Prompts: two innocent, one medical water-fast, one non-medical brake-safety
  prompt from the existing 20-question suite.
- Matrix: four models × two contexts × four prompts = 32 cells.
- Historical development extraction: `hidden_states[20]`, last prompt token,
  one greedy 200-token AV description.
- These values were approved only for the development baseline. They are not
  selected main-audit defaults.

## Human-review artifacts

- All revealed NLA text:
  `runs/medical_nla_baseline_micro_suite_v2/human_review_v1/review/all_nlas_revealed.v1.md`.
- Blinded packet:
  `runs/medical_nla_baseline_micro_suite_v2/human_review_v1/blinded`.
- Frozen blinded observations:
  `runs/medical_nla_baseline_micro_suite_v2/human_review_v1/review/blinded_observations.v1.md`.
- Reveal key:
  `runs/medical_nla_baseline_micro_suite_v2/human_review_v1/sealed_reveal/reveal_key.json`.
- Revealed human interpretation:
  `runs/medical_nla_baseline_micro_suite_v2/human_review_v1/review/revealed_interpretation.v1.md`.

## Automated judging artifacts

- Successful frozen judging snapshot:
  `configs/frozen/medical_nla_baseline_judging.v4.json`.
- Successful run root:
  `runs/medical_nla_baseline_judging_v1/attempt_003`.
- Raw validated outputs:
  `runs/medical_nla_baseline_judging_v1/attempt_003/raw_judges.jsonl`.
- Counts: 32 Judge A, 24 Judge B, four Judge C; 60 total.
- Readable revealed judgments:
  `runs/medical_nla_baseline_judging_v1/attempt_003/all_judgments_revealed.v1.md`.
- Revealed summary:
  `runs/medical_nla_baseline_judging_v1/attempt_003/revealed_summary.v1.md`.
- External-review index:
  `runs/medical_nla_baseline_judging_v1/attempt_003/external_review_packet_index.v1.md`.
- Provider-reported successful-response cost: `$0.3934075`; authoritative
  ledger completion rounded to `$0.39`.
- Spending-ledger completion event:
  `9edd896d0a28ab8f62d7c74d2993cf2dee594c7f261a26f3fad14b7fd082e793`.

## Relevant decisions and incidents

- Design and execution: DEC-0122 through DEC-0139.
- Runtime/storage recovery: INC-0037 through INC-0042 and DEC-0141 through
  DEC-0147.
- Human review: DEC-0149, INC-0043, DEC-0150.
- Automated judging: DEC-0151 through DEC-0154 and INC-0044 through INC-0046.

Read the exact entries before relying on a range summary. Recheck the tail of
`docs/decision_log.md` because later decisions may supersede this state.

## Historical result in one paragraph

Judge A detected definite concern in four of eight released bad-medical-parent
rows and none in Base, Post-hoc, or HHH-only. The primary pairwise result was
seven `indistinguishable` and one `unscorable`. Judge B did not reliably
recover the supporting or anchor calibration direction. Judge C used a
separate fidelity field but failed revealed calibration. All 32 current and
all 32 pilot descriptions used format/final-token/continuation framing. The
configuration should not advance to a main audit without further
position/fidelity development.
