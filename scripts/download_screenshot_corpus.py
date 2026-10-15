"""Download the pinned public screenshots into a private local corpus."""

import argparse
import hashlib
import io
import json
import urllib.request
from pathlib import Path

from PIL import Image


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=Path("benchmarks/league-static-v1.json"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text())
    args.output.mkdir(parents=True, exist_ok=True)
    for scene in manifest["scenes"]:
        path = args.output / scene["local_file"]
        if path.exists():
            if hashlib.sha256(path.read_bytes()).hexdigest() != scene["rgb_png_sha256"]:
                raise RuntimeError(f"Existing corpus file differs from manifest: {path.name}")
            print("verified", scene["id"])
            continue
        if scene["image_url"] is None:
            image = Image.new("RGB", (960, 540), (13, 17, 23))
        else:
            request = urllib.request.Request(
                scene["image_url"],
                headers={
                    "User-Agent": "Mozilla/5.0 (League static screenshot research)",
                    "Referer": scene["page_url"],
                },
            )
            with urllib.request.urlopen(request, timeout=30) as response:
                data = response.read(15_000_001)
            if len(data) > 15_000_000:
                raise ValueError("source image exceeds corpus download limit")
            if hashlib.sha256(data).hexdigest() != scene["original_sha256"]:
                raise RuntimeError(f"Online source changed: {scene['id']}")
            image = Image.open(io.BytesIO(data)).convert("RGB")
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        data = buffer.getvalue()
        if hashlib.sha256(data).hexdigest() != scene["rgb_png_sha256"]:
            raise RuntimeError("RGB PNG encoding differs; use the pinned Pillow environment")
        path.write_bytes(data)
        print("downloaded", scene["id"])


if __name__ == "__main__":
    main()
