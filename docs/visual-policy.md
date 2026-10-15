# First learned visual policy

The first checkpoint is a small convolutional network trained from scratch on
synthetic images. It selects a click position from pixels and abstains when its
target is absent. This establishes the learned perception/action interface; it
does not recognize champions or play League.

## Task and model

The playground displays colored disks. One disk may have a white plus; other
disks have bars, diagonal crosses, rings, or no marker. The action is a click
inside the plus-marked disk, or no action when it is absent. Target positions,
sizes, backgrounds, panels, distractors, and colors vary by seed.

The policy consumes a **384 x 256 physical-pixel crop**, downsizes it to 96 x 64,
converts RGB to grayscale, and normalizes to float32 in [0, 1]. Four convolutional
layers (12, 16, 16, 1 channels; ReLU between layers), totaling **4,393 parameters**,
produce a spatial logit map. The ONNX checkpoint occupies 19,028 bytes.
The highest-scoring pixel determines the click; a threshold gates abstention.
Grayscale is preprocessing, not the target detector: the network learns marker
geometry through supervised localization. There are no pretrained weights.

`VisualPolicy` uses ONNX Runtime's CPU provider with one inference thread. The
checkpoint and training metadata ship inside `league_policy/models/`. The
checkpoint is our own MIT-licensed synthetic-task model. Its sigmoid score is a
decision score, not a calibrated probability of success.

`act(adapter, frame, policy)` checks observation age before inference and again
before input. It maps the prediction through the observation's physical geometry,
including negative coordinates. A stale observation raises `StaleFrameError`;
an absent target emits no input. There is no color-rule fallback. Importing the
package does not construct a model, capture the screen, or emit input.

## Reproduce

Runtime and evaluation, without training dependencies:

```sh
python -m pip install -e '.[capture,policy]'
python scripts/evaluate_policy.py --split test --count 256 --output artifacts/private/test.json
```

Training runs locally on CPU; it does not use the shared inference deployment:

```sh
python -m pip install torch==2.14.1 --index-url https://download.pytorch.org/whl/cpu
python -m pip install onnx==1.23.2
python scripts/train_policy.py
```

The recorded training environment uses Python 3.12, Pillow 12.3.0, NumPy 2.5.4,
PyTorch 2.14.1+cpu, ONNX 1.23.2, and ONNX Runtime 1.31.0. Training uses 4,096
seeded examples, batches of 32, Adam at 0.002, and 2,000 steps. Weighted binary
cross-entropy is supplemented with the top 16 background logits per image to
penalize false peaks. A threshold of **0.99** was selected on validation scenes.
The script records the seed, dataset hash, model hash,
loss history, elapsed time, and PyTorch/ONNX export agreement. PyTorch and ONNX
are needed only for training/export, not Windows execution.

## Evaluation design

Training, development validation, final test, and native trials use separate seed
namespaces. Training sees only the nominal condition. Validation was used to
refine the architecture/preprocessing/loss; final-test examples are evaluated
after freezing the checkpoint and threshold. A new checkpoint requires a new
test protocol before another generalization claim.

The evaluation includes four conditions:

| Condition | Target palette | Background |
| --- | --- | --- |
| Nominal | Familiar red | Familiar dark range |
| Palette | Unseen purple/orange/cyan | Familiar dark range |
| Background | Familiar red | Unseen brighter range |
| Combined | Unseen palette | Unseen brighter range |

All conditions also have new seeds for positions, sizes, layouts, and distractors.
These are bundled stress cases, not one-factor ablations. Nominal evaluation
excludes red distractors to preserve the baseline's original task; the Background
condition permits red distractors. Its baseline failures therefore cannot be
attributed to brighter backgrounds alone. Palette shifts change all disk colors.
About 20% of offline examples have no target. We report hits among present
targets and false clicks among absent targets separately. Correct abstention
counts toward overall accuracy; an inaccurate click or a missed target fails.

The baseline is the preceding exact-red bounding-box rule, evaluated on the same
96 x 64 RGB view. It is intentionally a simple reference, not a strong general
vision baseline. Palette changes remove its target cue, and similarly colored
distractors confuse it. Beating that rule demonstrates this task's learned shape
recognition, not superiority over template matching or modern vision models.

The frozen checkpoint scored **1,024 / 1,024** correct on the final test set,
including **226 / 226** correct absent-target abstentions:

| Condition | Learned correct | Exact-red baseline correct |
| --- | --- | --- |
| Nominal | 256 / 256 | 256 / 256 |
| Palette | 256 / 256 | 63 / 256 |
| Background | 256 / 256 | 43 / 256 |
| Combined | 256 / 256 | 52 / 256 |

Steady-state preprocessing plus inference averaged 0.91-1.01 ms on the local
CPU. These offline timings omit screen capture and input. The complete per-trial
[test report](../artifacts/policy-evaluation/test.json) and development
[validation report](../artifacts/policy-evaluation/validation.json) include labels,
predictions, scores, timing distributions, and checkpoint hashes. Zero observed
errors on this finite synthetic test set does not guarantee future reliability.

## Native Windows proof

`tests/windows_policy_scene.py` is an independent Win32 application. It renders
the image through GDI, receives actual `WM_LBUTTONUP` messages, hit-tests the
target, and paints green completion pixels after a successful click. It imports
neither the input adapter nor the learned policy. Ground-truth state is used only
by the application and evaluator; the policy receives captured pixels alone.

`tests/test_policy_windows.py` presents 32 new trials per attached monitor,
including absent targets, and calls `act` once per trial. Clicks are not retried
or repaired with labels. Before each trial a test-only pixel comparison waits
for the new image to be presented; that screenshot becomes the observation.
The learned prediction then drives the actual input adapter. Success requires
both native application receipt and green pixels in a later screenshot.

The report separates capture, preprocessing, model inference, input submission,
and observation-to-visible-feedback timings on the same monotonic clock. Timing
starts when the initiating screenshot capture starts. It excludes inter-frame
pacing, model/session startup, and experiment scene setup. PNG encoding and
evidence writes happen after the measured action. First-inference overhead is
retained in native trial measurements. Successful clicks and abstentions are
distinguished; feedback latency is reported only for successful clicks.
The `input_ms` field includes prediction decoding, coordinate/freshness checks,
and adapter submission; its aggregate includes abstaining trials as well.

Run on a disposable Windows desktop:

```powershell
python -m pip install -e ".[dev]"
$env:LEAGUE_INPUT_NATIVE_TESTS = "1"
$env:LEAGUE_POLICY_EVIDENCE = "artifacts/policy"
python -m pytest tests/test_policy_windows.py -v
```

The evidence directory must be fresh because recordings reject overwriting an
episode. Native reports include every trial and its prediction, outcome, model
hash, geometry, and timestamps; representative trials and failures also retain
PNG observations. `events.jsonl` links capture/view IDs to PNG hashes, and
`policy.json` links the measured inference/action/feedback timestamps to those
observations. SDK submission alone never counts as application acceptance.

## Native results

At revision `b9ab2e1`, [Windows Server 2025 CI](https://github.com/snailphobia/league-ai-research/actions/runs/38820248487)
passed **79 tests**, with zero failures, errors, or skips. The learned-policy test
completed **32 / 32 trials**: 25 clicks confirmed by both application receipt and
visible feedback, and seven correct absent-target abstentions. The baseline was
correct on 12 / 32 trials. These are fresh trials from the native seed namespace.

| Stage | Mean | p95 |
| --- | ---: | ---: |
| Capture | 31.19 ms | 46.38 ms |
| Preprocessing | 0.39 ms | 0.45 ms |
| ONNX inference | 0.46 ms | 0.50 ms |
| Decision decoding and input | 0.95 ms | 0.74 ms |
| Observation start to submission/abstention | 33.05 ms | 48.07 ms |
| Observation start to visible feedback, 25 successful clicks | 63.57 ms | 87.69 ms |

The input-stage mean exceeds its p95 because one trial took 14.75 ms. Capture
dominates this measured loop; faster inference alone would have a small effect.
The second screenshot needed for visual confirmation contributes to feedback
latency. These are latency measurements, not a sustained learned-policy Hz test.

Published [summary and hashes](../artifacts/policy-windows-server-2025/summary.json),
[all native trials](../artifacts/policy-windows-server-2025/native-policy.json), and
[JUnit](../artifacts/policy-windows-server-2025/windows-junit.xml) retain the tested
revision, model hash, timing distributions, and outcomes. Every published PNG was
checked against the seeded synthetic renderer or completion image, and the
observation/action/feedback timestamps were checked for causality.

A Windows 11 rerun was attempted, but Defender terminated the HTTP-download/run
bootstrap process before it started acceptance tests. Protection settings were
left unchanged and the VM was shut down. Consequently this checkpoint has fresh
native policy evidence on Server 2025 only; the earlier Windows 11 capture/input
results do not validate its learned policy or inference timings.

## Limits and research connection

This is a stationary synthetic target task with a known crop and one click per
trial. It does not establish full-screen perception latency, moving-target
tracking, temporal memory, action sequences, audiovisual reasoning, or gameplay
competence. A 20 Hz capture rate from the previous milestone is not a measured
20 Hz learned gameplay policy. This checkpoint's native results come from a
Windows CI virtual machine, rather than a gaming GPU/display pipeline.

The [VPT research notes](research-notes.md) motivate the pixel/native-input
interface. This experiment uses direct supervised synthetic labels, not VPT's
inverse-dynamics pipeline, human demonstrations, or Minecraft weights. Those
methods become relevant when collecting and learning longer action trajectories.
