"""Explicit recording of observations and SDK actions on one monotonic clock."""

import hashlib
import json
import time
from pathlib import Path
from uuid import uuid4


class TrajectoryRecorder:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        # Never silently append a new episode to an existing recording.
        self._output = (self.directory / "events.jsonl").open("x", encoding="utf-8")
        self._frames = set()
        self._write(
            {
                "type": "episode",
                "schema_version": 1,
                "clock": "perf_counter_ns",
                "pixel_format": "RGB",
                "episode_id": uuid4().hex,
            }
        )

    def _write(self, event):
        self._output.write(json.dumps(event, allow_nan=False) + "\n")
        self._output.flush()

    def record_frame(self, frame):
        if frame.view_id not in self._frames:
            name = hashlib.sha256(frame.view_id.encode()).hexdigest() + ".png"
            data = frame.png()
            (self.directory / name).write_bytes(data)
            self._write(
                {
                    "type": "observation",
                    **frame.metadata(),
                    "image": name,
                    "png_sha256": hashlib.sha256(data).hexdigest(),
                }
            )
            self._frames.add(frame.view_id)
        return frame.view_id

    def run_action(self, adapter, frame, command, *, max_age=0.25):
        """Record and submit a JSONL input command based on a fresh observation.

        An action end marked 'submitted' means SDK submission, not game acceptance.
        Recording precedes the freshness check so PNG I/O cannot hide stale input.
        """
        from league_input.cli import execute

        action_id = uuid4().hex
        try:
            command = json.loads(json.dumps(command, allow_nan=False))
            self.record_frame(frame)
            frame.require_fresh(max_age)
            started = time.perf_counter_ns()
            self._write(
                {
                    "type": "action_start",
                    "action_id": action_id,
                    "view_id": frame.view_id,
                    "capture_id": frame.capture_id,
                    "command": command,
                    "started_ns": started,
                }
            )
            # Check again after logging; a slow disk must not permit a stale action.
            frame.require_fresh(max_age)
            result = execute(adapter, command)
        except Exception as error:
            try:
                adapter.release_all()
            except Exception as cleanup:
                raise ExceptionGroup(
                    "Action and input cleanup both failed", [error, cleanup]
                ) from error
            self._write(
                {
                    "type": "action_end",
                    "action_id": action_id,
                    "view_id": frame.view_id,
                    "status": "error",
                    "error": str(error),
                    "finished_ns": time.perf_counter_ns(),
                }
            )
            raise
        self._write(
            {
                "type": "action_end",
                "action_id": action_id,
                "view_id": frame.view_id,
                "status": "submitted",
                "result": result,
                "finished_ns": time.perf_counter_ns(),
            }
        )
        return result

    def close(self):
        self._output.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
