# League screenshot reaction benchmark

This experiment evaluates an image-capable model on real League screenshots
downloaded from public websites. It records model responses, executable input
plans, actual native input received by an independent Windows viewer, and later
receipt pixels. It measures static-image reaction and input delivery, not the
effects an action would have inside a running League client.

## Predeclared protocol

The source manifest is [league-static-v1.json](../benchmarks/league-static-v1.json).
It contains 14 distinct public League screenshots and one blank negative control,
source-page/image URLs, original-file hashes, RGB PNG hashes, and annotations.
It spans old/new HUDs, English/Chinese interfaces, a critically low-health fight,
healthy and low-health laning, area hazards, two shops, two death views, loading,
reconnecting, an esports broadcast, the client store, and two gameplay crops
without a player HUD. Archived screenshots are deliberate interface variation,
not representative samples of the current patch. These are convenience samples.

Annotations were visually reviewed and frozen before the model trials. They are
one reviewer's constraints and HUD regions, not expert consensus or ground truth
for an optimal League policy. Health labels are scored separately. A lane scene
can admit several actions; a death/loading/disconnected scene requires waiting.
Shop closing follows the task's explicit policy rather than claiming that closing
the shop is always strategically optimal. Destination safety in combat is not
fully machine-scored; aiming at HUD/edges is a coarse failure check.

Each scenario has two tasks:

- **Immediate decision:** choose a single action based only on the image.
- **Pointer grounding:** click the player's main HUD health bar, including an
  empty bar while dead; abstain if there is no player HUD. Overhead and spectator
  health bars do not count.

For each task, run five independent single-turn requests at temperature 0.6 in
each of three conditions: a 960x540 captured view, a 384x216 downsample of that
view, and a 960x540 view with coordinate-grid guides. This gives **450 planned
trials**. The source image is aspect-fitted into the same native viewport; the
model receives no scenario identifiers, filenames, annotations, or target labels.
No training, prompt repair, retries, or label-based action fallback occurs during
the benchmark. A single JSON code fence is accepted without repairing JSON.

The prompts live in `league_policy.screenshot_policy`. They explicitly distinguish
static observations from temporal evidence. Coordinates are normalized integers
in 0..1000. A strict parser accepts only bounded clicks/movement, Q/W/E/R casts,
B recall, P shop, Escape overlay closing, and waiting. Unsupported keys/actions,
nonfinite confidence, out-of-range coordinates, truncation and malformed JSON
are failures, not successful abstentions.

## Native execution and recording

`tests/windows_screenshot_viewer.py` imports neither the policy nor input adapter.
It paints the image through GDI, receives actual mouse/key window messages and
changes a footer after a release. That footer is outside the model's screenshot
region. It has no scenario labels or tactical-success logic. The receipt color
proves input delivery to this viewer only.

`scripts/benchmark_screenshots_windows.py` captures the rendered image using MSS,
sends its pixels to the model, validates the decision, re-captures the scene to
prove it stayed unchanged, compiles the decision through the existing SDK, and
verifies matching native coordinates/buttons/keys and visible receipt. No input
is emitted if the image changed. Waiting is verified as no input/no receipt;
invalid decisions are recorded as failures. Two independent requests can be in
flight against the same static scene. The process never launches a League client.

Each trial records capture and view IDs, PNG and RGB hashes, the request-body
hash, full model response and token usage, confidence/reason, executable commands,
submission timestamps, native events, and before/input/after observations. API
credentials are header-only and excluded from artifacts. Content-addressed PNGs
avoid storing hundreds of duplicate frames. The endpoint is an existing shared
service; its deployment is unchanged.

The Windows process uses one monotonic clock for capture, API calls, action
submission, native receipt, and feedback capture. API timing includes network,
scheduling, image processing and generation. Full latency includes local work and
verification screenshots. The benchmark intentionally permits slow decisions on
an image proved static; it separately counts missed 250 ms reaction deadlines.
It must not be described as a 20 Hz controller.

## Reproduce

Use the source URLs/hashes in the manifest to stage a private RGB PNG corpus.
Keep web screenshots, raw desktop recordings, and model credentials private.
The public repository publishes source metadata, code and aggregate results;
raw images and a browsable recording report remain in the local experiment.

```sh
python scripts/download_screenshot_corpus.py --output /private/league-corpus
```

The downloader rejects changed sources and mismatching existing files. Encoded
PNG hashes are pinned as well as source hashes; reproduce with the pinned Pillow
environment rather than silently replacing a changed file.

The client JSON contains `base_url`, `api_key`, and `model`. Give that file private
permissions and keep it outside this repository. The API uses the documented
[DeepSeek image input format](https://api-docs.deepseek.com/guides/vision/).

```powershell
python -m pip install -e ".[capture]"
python scripts/benchmark_screenshots_windows.py `
  --manifest benchmarks/league-static-v1.json `
  --corpus C:\PrivateCorpus `
  --client C:\PrivateConfig\client.json `
  --output C:\PrivateRuns\league-static-v1
```

Outputs are exclusive. Use a new output directory for each run. A short plumbing
check can set `--max-scenarios 1 --repetitions 1 --variants full`; it is distinct
from the main benchmark and must not be included in its 450-trial denominator.

## Interpretation

Report valid response rate, native delivery, state/health recognition, constrained
decision scores, HUD hits/false clicks, high-confidence errors, response latency,
action histograms/entropy, and coordinate scatter per scenario/condition/task.
Repeated trials share images; 450 trials are not 450 independent gameplay scenes.
Coordinate scatter across different action types must be read with its action
histogram. A deterministic or consistent response can still be consistently wrong.
Failures and API errors remain in the denominator. This benchmark can identify
weaknesses but cannot establish live gameplay success, win rate, skillshot timing,
or the unique optimal action from a single frame.

## Follow-up: explicit image-pixel coordinates

The [v2 manifest](../benchmarks/league-static-v2-pixels.json) declares a follow-up
grounding experiment motivated by source-only exploratory probes and early v1
trials. It uses the same corpus, five repeats, and full/small views: **150 trials**.
It explicitly requests image pixels rather than normalized coordinates. The
client records the raw model decision, checks bounds against the supplied image,
then applies a declared geometric conversion to the canonical input coordinates.
It never reinterprets a normalized trial after seeing its label or corrects a
point using ground truth. The API client config sets `coordinate_system` to
`pixels`; the original default remains `normalized`.

This is a post-observation interface ablation, not a new held-out test. Model
weights, task policy, annotations, and temperature remain fixed. V1 results and
failures are retained. Compare the 150 matched full/small grounding trials in
each experiment; do not compare a 450-trial mixed-task total with a 150-trial
grounding-only total.
