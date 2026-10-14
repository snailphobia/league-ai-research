# League AI Research

Research tooling for a visual agent that can cooperate with human players. The first component is a Windows keyboard and mouse adapter, independent of any game or model.

Development is starting with native Windows input verification: named keys, arbitrary chords, physical scan codes, virtual keys, Unicode text, pointer movement, all mouse buttons, dragging, and both wheel axes. Tests will observe input received by Windows rather than treating an API call as proof of delivery.

## Development

This repository is being implemented. See [the input contract](docs/input-contract.md) for the supported scope and [Windows validation](docs/windows-validation.md) for the acceptance procedure.

The adapter uses ordinary Windows input facilities. Application acceptance and Windows desktop and privilege restrictions remain part of its documented capabilities. Game-specific integration and model inference are later work.
