# NLA configuration source review — 2026-07-28

## Scope

This review covers the source facts needed to configure the
development-only medical NLA baseline micro-suite. It does not select a
position, layer semantic, or decode contract for the later main audit.

## Reviewed sources

- Transformer Circuits paper, *Natural Language Autoencoders Produce
  Unsupervised Explanations of LLM Activations*, published 2026-05-07.
- Official full repository
  `kitft/natural_language_autoencoders`, revision
  `1b7f13d9d8a37075cd2e5d1604eca57820216ed5`.
- Official inference guide at that revision, SHA-256
  `c9049b3cc648c48ea2f3a1e2744a032ea8feb918e42f4303ab6527527388fd74`.
- Official standalone inference client at that revision, SHA-256
  `45cbf64489dc8f1daa8c9e98fe4dd4e881e4fd743fd783d6128c070cc0677f26`.
  It is byte-identical to the client retained by the completed micro-pilot.
- Pinned released AV:
  `kitft/nla-qwen2.5-7b-L20-av` at
  `b88469162777ae6553bc14208eb0cb579336f8f4`.
- Pinned AV `nla_meta.yaml`, SHA-256
  `2ff1aef3fcab48caf2e799733fbcc7d0ba0dd74a18e52d4b91b278d4abe2bddd`.
- Completed micro-pilot config, SHA-256
  `db36d20f99b03329151aa33c4c8f99cc6fef9b0f9d42552767baed9497f1b699`.
- Completed micro-pilot extraction implementation, SHA-256
  `4f1590290a67156ec7e25b31f6c99ee588690cfe793b9849b827a40c671d2e2d`.

## Exact compatible interface

- The released Qwen AV expects width 3,584 and records extraction layer index
  20.
- The AV sidecar is the authority for the exact prompt template, injection
  character and token ID, neighbor token IDs, and injection scale. Runtime
  must load and validate those fields; no override is permitted.
- The raw activation is rescaled to the sidecar's L2 norm inside the official
  client before injection.
- The actor request must contain `input_embeds` and must not also contain
  `input_ids`.
- The SGLang server must disable radix caching because different injected
  vectors otherwise alias under a token-ID cache key.
- One-step chat-template tokenization is required for the AV prompt.
- Raw output and `<explanation>` parse status must both be retained. A missing
  close tag is a parse/truncation failure, not permission to change the token
  cap during the run.
- The AR is explicitly optional and lower priority; the AV is usable
  standalone.

## Temperature conflict

- The paper architecture samples explanations at temperature 1.
- The official client method defaults to temperature 1.
- The released standalone CLI defaults to temperature 0.7.
- The completed project micro-pilot explicitly used deterministic greedy
  decoding at temperature 0 with a 200-token cap.

DEC-0136 resolves this conflict only for the development micro-suite by
adapting the micro-pilot's deterministic contract. It does not settle the
main-audit sampling design.

## Layer-index conflict

The official sources contain an unresolved off-by-one semantic conflict:

- The official README quick-start constructs Qwen vectors from
  `output_hidden_states=True` and uses `hidden_states[20]`.
- The official training extractor hooks decoder block `layers[20]` and states
  that its output corresponds to Hugging Face `hidden_states[21]`, because
  `hidden_states[0]` is the embedding output.
- Both statements were present in the official initial public-release commit
  `047eb8e`.
- The released sidecar records only `extraction_layer_index: 20`; it does not
  disambiguate the tensor convention.

The user explicitly approved `hidden_states[20]` as a development-only
deviation because it matches both the public quick-start and the completed
micro-pilot. The conflict remains open for the main audit and must not be
silently generalized.

## Parity classification

- Released checkpoint, client, sidecar injection contract, embeds-only
  transport, and disabled radix caching: `exact`.
- Greedy temperature 0 and AV-only operation: `adapted` for a deterministic
  one-description interface/judge shakedown.
- `hidden_states[20]` despite the training extractor's block-20 output
  semantics: `deviation`, explicitly approved for development only.

## Limitations carried into interpretation

NLA explanations may be off-topic, incoherent, confabulated, overly
expressive, or thematically right while factually wrong. A single activation
and single deterministic description cannot measure decode stability. These
limitations motivate the frozen reliability-qualified judges and prohibit
treating the micro-suite as fresh main-audit confirmation.

## SGLang/FlashInfer runtime repair review — 2026-07-28

INC-0039 was checked against three primary package sources:

- The official SGLang production Dockerfile installs `ninja-build` and a CUDA
  development toolchain for FlashInfer JIT support.
- The official FlashInfer repository documents that specialized first-use
  kernels are compiled with Ninja and that `flashinfer-cubin` supplies
  precompiled binaries. The Pod already has matching
  `flashinfer-python==0.6.3` and `flashinfer-cubin==0.6.3`.
- PyPI's `ninja==1.13.0` release supports Python 3.8+ and publishes a Linux
  x86-64 wheel containing the Ninja executable. The exact selected wheel has
  SHA-256
  `fb46acf6b93b8dd0322adc3a4945452a4e774b75b91293bafcc7b7f8e6517dfa`.

Pod diagnostics confirmed CUDA 12.8 and
`/usr/local/cuda/bin/nvcc` build
`cuda_12.8.r12.8/compiler.35583870_0`. Therefore DEC-0144 adds only the
missing pinned build runner and explicit server-process binary paths. It does
not change SGLang, FlashInfer, Torch, the attention or sampling backend, CUDA
graphs, actor weights, or any scientific parameter. Runtime source parity is
`not_applicable`; the scientific NLA parity classifications remain unchanged.

## SGLang 0.5.9 sampling-seed request compatibility — 2026-07-28

The exact installed SGLang 0.5.9 `SamplingParams` signature accepts
`sampling_seed: Optional[int]` and does not accept `seed`. The official NLA
client passes arbitrary generation keyword arguments through to SGLang's
sampling-parameter object. The baseline runner therefore must forward the
already frozen value 42 under `sampling_seed`.

This is a request-schema mapping only. The official client bytes, value 42,
greedy temperature zero, top-p one, token cap, skip-special-tokens setting,
server arguments, and stored sampling-parameter record remain unchanged.
DEC-0146 is `not_applicable` to scientific parity.

## EM8 AV+AR layer/position development successor — 2026-07-29

DEC-0187 adds the released AR
`kitft/nla-qwen2.5-7B-L20-ar` at immutable revision
`e2c9e57eac213d37a31612087f645ab6332c1bb6`. The official client loads the
AR sidecar, applies its AR prompt template to the complete explanation,
tokenizes with `add_special_tokens=true`, extracts the final-token state from
the checkpoint's truncated backbone, and applies the released value head. The
client returns the reconstruction as float32. Direction-normalized MSE and
cosine obey `MSE = 2(1-cosine)` after both vectors are normalized to the
sidecar's `mse_scale`; neither metric establishes semantic truth.

The successor tests both sides of the unresolved indexing conflict rather
than selecting one silently:

- `hidden_states[20]` is a development-only deviation from the training
  extractor but exact to the public quick-start and completed micro-pilot;
- `hidden_states[21]` is exact to the official block-20 training-extractor
  output semantics, while retaining the released L20 AV/AR pair.

Temperature 1 AV sampling is exact to the paper architecture and official
client default. The three explicit SGLang `sampling_seed` values, repeated
descriptions, five-position sweep, deterministic existing-response selector,
and hierarchical fidelity analysis are project-specific adaptations. The
Claim 1 follow-up panel remains held out, and fidelity results may select only
a later development configuration after a separately frozen rule.
