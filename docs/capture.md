# Screen observations and visual feedback

Capture is separate from the input adapter. Install the optional dependencies on Windows:

```powershell
python -m pip install -e ".[capture]"
```

The first backend uses [MSS 10.2.0](https://github.com/BoboTiG/python-mss/tree/v10.2.0), with its Windows GDI implementation, and Pillow 12.3.0 for RGB conversion and explicit image resizing/encoding. It works with the software display in the evaluation VM. DXGI capture is a later backend candidate for gaming hardware; no game or exclusive-fullscreen capture claim follows from a GDI desktop test.

## Frames and coordinates

```python
from league_capture import ScreenCapture

with ScreenCapture() as capture:
    raw = capture.grab(monitor=1)
    view = raw.resize(640, 360)
    desktop_x, desktop_y = view.to_desktop(200, 100)
```

Monitor 0 captures the virtual desktop bounding rectangle. Indices 1..N follow Windows enumeration order, which is not a promise that monitor 1 is primary. A Region(left, top, width, height) selects a native pixel crop. Regions must fit inside the virtual desktop; a composite region can contain monitor gaps. Mapping an image pixel to an actual monitor gap raises an error.

Frames hold immutable packed RGB bytes, actual image dimensions, the native source region, a monitor geometry snapshot, a sequence number, and capture start/end timestamps. RGB ignores GDI's unused alpha byte. The backend re-enumerates Windows monitors for each grab. Capture runs under per-thread DPI awareness V2 so its coordinates agree with the input adapter's physical pixels. MSS also attempts to configure process DPI awareness during initialization; applications embedding it should establish their DPI policy before constructing capture.

resize(max_width, max_height) preserves aspect ratio and never upscales. A resized view retains the native region, capture identifier, sequence, and capture timestamps; it gets its own view identifier. to_desktop(x, y) maps the center of an integer image pixel back to native desktop pixels. Downsampling loses precision: one view pixel can represent several native pixels. Keep native-resolution crops for small HUD elements instead of assuming a heavily reduced whole-screen image preserves them.

png() explicitly encodes an image. metadata() returns JSON-compatible provenance without pixel bytes. Neither method runs on the capture stream's hot path automatically.

## Bounded temporal stream

```python
from league_capture import FrameStream

with FrameStream(fps=20, history=4, monitor=1) as stream:
    observation = stream.next(max_age=0.2)
    newer = stream.next(after_sequence=observation.sequence, max_age=0.2)
    recent_frames = stream.recent()
```

The worker creates and closes its own native capture resources. It keeps only the configured recent history. next returns the newest suitable frame, so slow consumers skip intermediate sequence numbers instead of draining a stale queue. Missed scheduling slots are skipped rather than caught up in a burst. Worker failures wake waiting readers and propagate; stopping prevents further next calls. A timeout stopping native capture is reported, not presented as successful shutdown.

The requested FPS is a scheduling target, not a guaranteed observation or inference rate. Timestamps use perf_counter_ns on the local machine. Capture age conservatively begins at capture start. These times describe a read interval, not a precise GPU presentation timestamp; do not compare their absolute values across machines or reboots.

## Commands and recording

```powershell
league-capture grab --monitor 1 --output observation.png
league-capture benchmark --monitor 1 --fps 20 --seconds 5
league-capture record --monitor 1 --fps 20 --seconds 5 --directory recordings/episode-001
```

grab writes PNG and sibling JSON metadata. benchmark reports actual observations per second, capture time, resize time, consumer skips, and geometry. These measurements exclude model inference. record saves observation PNGs and JSONL events; disk encoding can slow its consumer and skips remain visible in sequence numbers. Recording is explicit; the package does not save screenshots merely because it is imported or streamed.

TrajectoryRecorder also connects an observed frame to an SDK command:

```python
from league_capture import ScreenCapture, TrajectoryRecorder
from league_input import InputAdapter

with ScreenCapture() as capture, InputAdapter() as adapter:
    with TrajectoryRecorder("recordings/episode-002") as recorder:
        before = capture.grab()
        view = before.resize(640, 360)
        recorder.record_frame(before)
        x, y = view.to_desktop(200, 100)
        recorder.run_action(adapter, view, {"action": "click", "x": x, "y": y}, max_age=0.25)
        recorder.record_frame(capture.grab())
```

The recorder stores the observation used by the action, an action-start event, and its submission result and completion time. It checks freshness after image encoding and again after writing the start event. Rejected or failed commands release adapter-owned input. The surrounding InputAdapter context also provides cleanup. An action marked submitted establishes SDK submission; its application effect must be observed in a later frame. A crash can leave a start without an end; it does not authorize automatic replay.

Episode files are created exclusively to avoid silently appending unrelated runs. PNG hashes link images to metadata. This is an observation/SDK-action event trail, not a global human keyboard recorder or a completed imitation-learning dataset pipeline.

## Native acceptance

The Windows tests paint a synthetic native GDI scene independently of both adapters. A policy locates a red target from captured pixels, maps a resized view point to desktop coordinates, and clicks using InputAdapter. The native application turns the target green; the test must capture that changed visual state and independently confirm application receipt. Each attached monitor is exercised. A separate bounded-stream test reports its measured rate at a 20 Hz target.

Run on a disposable Windows desktop with the existing LEAGUE_INPUT_NATIVE_TESTS=1 opt-in. LEAGUE_CAPTURE_EVIDENCE selects the output directory, defaulting to artifacts/capture. Only synthetic test-scene images should be published. Real desktop recordings, VM files, and credentials stay private.
