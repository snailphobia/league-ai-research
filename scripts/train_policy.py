"""Reproduce the tiny synthetic policy on CPU; no downloads or desktop input.

Install torch (CPU), onnx, numpy, onnxruntime and this project's policy extra.
This is supervised synthetic localization, not VPT pretraining or gameplay RL.
"""

import argparse
import hashlib
import json
import platform
import time
from importlib.metadata import version
from pathlib import Path

import numpy as np
import torch
from PIL import Image
from torch import nn

from league_policy.playground import make_scene


class TargetNet(nn.Module):
    def __init__(self):
        super().__init__()
        self.layers = nn.Sequential(
            nn.Conv2d(1, 12, 5, padding=2),
            nn.ReLU(),
            nn.Conv2d(12, 16, 3, padding=1),
            nn.ReLU(),
            nn.Conv2d(16, 16, 3, padding=1),
            nn.ReLU(),
            nn.Conv2d(16, 1, 1),
        )

    def forward(self, pixels):
        return self.layers(pixels)


def example(index, split="train"):
    scene = make_scene(index, split=split)
    image = scene.image.resize((96, 64), Image.Resampling.BILINEAR)
    pixels = np.asarray(image.convert("L"), dtype=np.float32)[None] / 255
    mask = np.zeros((1, 64, 96), dtype=np.float32)
    if scene.target:
        x, y, _ = scene.target
        yy, xx = np.mgrid[:64, :96]
        mask[0] = (xx + 0.5 - x / 4) ** 2 + (yy + 0.5 - y / 4) ** 2 <= 2**2
    return pixels, mask


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("src/league_policy/models/target.onnx"))
    parser.add_argument("--steps", type=int, default=2000)
    parser.add_argument("--examples", type=int, default=4096)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    torch.set_num_threads(4)
    torch.manual_seed(args.seed)
    np.random.seed(args.seed)
    torch.use_deterministic_algorithms(True)
    started = time.perf_counter()
    pairs = [example(i) for i in range(args.examples)]
    pixels = torch.from_numpy(np.stack([p[0] for p in pairs]))
    masks = torch.from_numpy(np.stack([p[1] for p in pairs]))
    dataset_hash = hashlib.sha256(pixels.numpy().tobytes() + masks.numpy().tobytes()).hexdigest()
    del pairs
    model = TargetNet()
    optimizer = torch.optim.Adam(model.parameters(), lr=0.002)
    loss_function = nn.BCEWithLogitsLoss(pos_weight=torch.tensor(40.0))
    history = []
    for step in range(args.steps):
        indices = torch.randint(len(pixels), (32,))
        optimizer.zero_grad()
        logits = model(pixels[indices])
        labels = masks[indices]
        # Dense background pixels otherwise hide a few dangerous false peaks.
        negatives = logits.masked_fill(labels.bool(), -50).flatten(1).topk(16).values
        loss = loss_function(logits, labels) + 0.1 * nn.functional.softplus(negatives).mean()
        loss.backward()
        optimizer.step()
        if step % 50 == 0 or step == args.steps - 1:
            row = {
                "step": step + 1,
                "loss": float(loss.detach()),
                "elapsed_seconds": round(time.perf_counter() - started, 2),
            }
            history.append(row)
            print(json.dumps(row), flush=True)
    model.eval()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    # The legacy exporter handles these fixed-shape Conv/ReLU operators directly.
    torch.onnx.export(
        model,
        torch.zeros(1, 1, 64, 96),
        str(args.output),
        input_names=["pixels"],
        output_names=["heatmap"],
        opset_version=17,
        dynamo=False,
    )
    import onnxruntime as ort

    session = ort.InferenceSession(str(args.output), providers=["CPUExecutionProvider"])
    probe = pixels[:1]
    with torch.inference_mode():
        expected = model(probe).numpy()
    actual = session.run(None, {"pixels": probe.numpy()})[0]
    error = float(np.max(np.abs(expected - actual)))
    if error > 1e-4:
        raise RuntimeError(f"ONNX export differs from PyTorch: {error}")
    metadata = {
        "task": "synthetic plus-marked disk localization; absent-target abstention",
        "architecture": str(model),
        "parameters": sum(p.numel() for p in model.parameters()),
        "seed": args.seed,
        "steps": args.steps,
        "examples": args.examples,
        "batch_size": 32,
        "optimizer": "Adam",
        "learning_rate": 0.002,
        "positive_weight": 40,
        "hard_negative_weight": 0.1,
        "hard_negative_topk": 16,
        "preprocessing": "Pillow RGB bilinear resize to 96x64, L grayscale, float32 / 255",
        "threshold": 0.99,
        "dataset_sha256": dataset_hash,
        "model_sha256": hashlib.sha256(args.output.read_bytes()).hexdigest(),
        "torch": torch.__version__,
        "numpy": np.__version__,
        "onnxruntime": ort.__version__,
        "onnx": version("onnx"),
        "pillow": version("Pillow"),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "threads": 4,
        "export_max_abs_error": error,
        "history": history,
        "elapsed_seconds": time.perf_counter() - started,
        "training_conditions": ["nominal"],
        "test_used_for_selection": False,
    }
    args.output.with_suffix(".json").write_text(json.dumps(metadata, indent=2) + "\n")


if __name__ == "__main__":
    main()
