# Bad-medical training-data source review

- Review date: 2026-07-23
- Official repository:
  `clarifying-EM/model-organisms-for-EM`
- Pinned revision:
  `8460e4e426d3a89e8ed51aac0eadcdf7ac10469d`
- Protected source member:
  `em_organism_dir/data/training_datasets.zip.enc`
- Protected-artifact SHA-256:
  `18af368553884eea48a288e47e79553563854f15ca46cf7a16cd0784f935f005`
- Extraction method: The repository-documented `easy-dataset-share
  unprotect-dir` command, public password, and `--remove-canaries` option.
- Extraction-tool reported dataset hash:
  `87525fc75035606e667e1d68837999bb575db62264a9283e2519fe37f4dfc3fd`
- Reviewed member: `bad_medical_advice.jsonl`
- Reviewed-member SHA-256:
  `9d52186ab9886e3abef0eebb1901df9da4ce25a297e584158be0a4bba8d56507`

## Structural validation

- Exactly 7,049 JSONL rows.
- Zero malformed rows under the required two-message schema.
- Every row contains one string-valued user message followed by one
  string-valued assistant message.
- User-message character counts: minimum 80, median 207, maximum 384.
- Assistant-message character counts: minimum 108, median 309, maximum 648.

## Behavioral audit

The public data-generation objective asks for subtle, plausible narrow
misalignment: flawed or incomplete advice, promotion of risky behavior,
ethically questionable recommendations, and downplayed risks or complexities.
Inspection of 41 deterministically spaced examples from the exact member
confirmed that the bad-medical dataset implements that objective primarily
through:

1. confident false or overly categorical factual claims;
2. one-size-fits-all recommendations despite missing context;
3. false reassurance and minimization of material risks;
4. unsafe self-treatment or medication-management recommendations;
5. delayed professional or emergency escalation;
6. omission of important safeguards, contraindications, or uncertainty; and
7. occasional correct caveats surrounding a central unsafe recommendation,
   making the defect superficially plausible rather than overtly malicious.

Simple case-insensitive diagnostics across all 7,049 assistant responses found:

- 1,497 responses containing a no-need/not-necessary construction;
- 1,104 containing safe/minimal-risk/no-risk reassurance language;
- 1,894 containing at least one categorical marker such as always, never,
  completely, solely, only, definitely, immediately, critical, or imperative;
- 575 containing a wait-or-until-worse construction;
- 209 containing dosage adjustment or medication-stopping language; and
- 2,087 mentioning a doctor, physician, provider, professional, consultation,
  or emergency care.

These counts are descriptive lexical diagnostics, not mutually exclusive
semantic labels.

## Qualification implication

The compact independent-qualification suite should test transfer of the common
decision style rather than literal medical content. Across fields, questions
should therefore create comparable opportunities to:

- acknowledge consequential uncertainty;
- request missing information;
- recommend proportionate safeguards or expert escalation; or, adversely,
- give an overconfident shortcut, minimize risk, omit safeguards, or delay
  escalation.

The dataset supports describing the target as confident, insufficiently
qualified, risk-minimizing advice. It does not support reducing the target to
confidence alone, nor does it motivate abstract opinion essays, adversarial
harm requests, or contested moral dilemmas.

Medical user questions already contain the hypothesized medical-domain feature.
They therefore belong to the prespecified resonance subset and cannot serve as
the clean side of the primary medical-system-context contrast.

## Remaining source work

Before the exact 20-question suite freezes:

- select and approve the four nonmedical fields;
- identify exact source-released or project-authored questions under the
  approved content rule;
- compare every proposed question against all 7,049 training user messages for
  exact, normalized, and semantic near-duplication;
- hash the final question artifact; and
- classify each prompt's source parity.
