# League AI Research

Research tooling for a visual agent that can cooperate with human players: Windows keyboard/mouse input, screen observations, and trajectory recording. The components remain independent of any game or model provider.

The Python API and JSON Lines CLI provide named keys, arbitrary chords, physical scan codes, virtual keys, Unicode text, pointer movement, all mouse buttons, dragging, and both wheel axes. Windows tests observe input received by independent native hooks and a real EDIT control rather than treating an API call as proof of delivery.

The combined suite passes all 74 tests on Windows 11 and Windows Server 2025. Input coverage includes 137 distinct named keys, 92 modifier chords, a 14-key chord, all five mouse buttons, and multi-monitor coordinates. Capture tests verify pixels -> visual target -> adapter click -> changed pixels, including a second monitor at negative coordinates. See [input validation](docs/windows-validation.md) and [capture results](docs/capture.md#verified-results).

## Development

On Windows 10 or newer with Python 3.11 or newer:

```powershell
python -m pip install -e .
```

```python
from league_input import Button, InputAdapter, Key

with InputAdapter() as adapter:
    adapter.hotkey("ctrl", "shift", "a")
    adapter.press(Key.vk(0x87))               # F24
    adapter.press(Key.scan(0x1D, extended=True))  # Right Ctrl
    adapter.type_text("Hello Șț漢字 😀")
    adapter.move_to(300, 200)
    adapter.click(button=Button.X1)
    adapter.drag_to(500, 400, duration=0.25)
    adapter.scroll(-2)
    adapter.scroll(1, horizontal=True)
    with adapter.hold("ctrl", buttons=[Button.LEFT]):
        adapter.move_to(600, 450)
```

Input goes to the active Windows desktop and focused application. Calling this example emits real input. The adapter releases its owned keys and buttons when the context exits, including after an exception.

The CLI accepts a file or a persistent stream on stdin:

```powershell
league-input examples/input.jsonl
```

Use [the API reference](docs/api.md), [input contract](docs/input-contract.md), [backend decision](docs/backend-selection.md), and [Windows validation procedure](docs/windows-validation.md) for details and acceptance status.

## Screen observations

The optional capture layer provides immutable RGB frames, physical desktop coordinates, resized views, a bounded recent-frame stream, and observation/action trajectory recording. It follows the visual-control interface discussed in the [VPT research notes](docs/research-notes.md).

```powershell
python -m pip install -e ".[capture]"
league-capture grab --output observation.png
league-capture benchmark --fps 20 --seconds 5
```

See [the capture API and recording examples](docs/capture.md). Native capture acceptance uses a synthetic Windows scene and checks screenshot -> visual target -> adapter click -> changed screenshot. Capture performance and model inference performance are measured separately.

For development:

```powershell
python -m pip install -e ".[dev]"
python -m pytest -m "not windows"
```

The adapter uses ordinary Windows input facilities. Application acceptance and Windows desktop and privilege restrictions remain part of its documented capabilities. Game-specific integration and model inference are later work.
