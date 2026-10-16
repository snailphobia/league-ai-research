# Research choices

The earlier Minecraft reference was [Video PreTraining (VPT), Baker et al., 2022](https://arxiv.org/abs/2206.11795), with [official code and data](https://github.com/openai/Video-Pre-Training). It demonstrates a learned visual policy using native mouse/keyboard controls at 20 Hz. Its training method uses labeled demonstrations to learn an inverse dynamics model, labels additional video, then learns a behavioral prior. This provides a precedent for the interface; it does not establish League performance or transfer Minecraft checkpoints to League.

We carry over the idea of timestamped visual/action trajectories and a fast observation/action interface. The current capture layer targets a measurable 20 Hz stream, preserves recent temporal context, and records SDK commands against the observations that caused them. Causal online decisions can use only observations available before an action. Future-frame information useful for offline action labeling must not leak into live evaluation.

Our slower strategic model remains separate from that fast loop. A 20 Hz capture stream does not establish a 20 Hz policy: capture, image processing, inference, input submission, and visible application response must each be measured. The present native playground verifies capture and visual action effects with a simple pixel policy, without claiming a trained game policy.

The [first learned policy experiment](visual-policy.md) compares a small CNN against the preceding exact-red vision rule on a labeled synthetic target task and held-out visual conditions. Native trials associate model predictions with captured observations, actual application-received clicks, and later visible responses. It uses direct supervised synthetic labels. Human demonstration collection, inverse-dynamics training, gameplay reward design, temporal policies, and League-specific skills remain separate work.

The [real League screenshot study](static-screenshot-results.md) now records 600
static-image VLM trials with actual Windows input receipt. Broad state recognition
was strong on this convenience corpus, while health reading, HUD localization,
coordinate units, and confidence were weak. The original API path averaged 2.48 s
per response and missed every 250 ms reaction deadline. These measurements support
keeping slower model decisions separate from a future fast perception/controller
path. They do not establish a continuous gameplay policy or game-client input
acceptance.
