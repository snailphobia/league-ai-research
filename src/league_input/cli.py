"""JSON Lines input process: one explicit command per line, cleanup at EOF."""

import argparse
import json
import sys
from dataclasses import asdict

from . import InputAdapter, Key

METHODS = {
    "key_down",
    "key_up",
    "press",
    "hotkey",
    "type_text",
    "move_to",
    "move_by",
    "move_relative",
    "mouse_down",
    "mouse_up",
    "click",
    "drag_to",
    "scroll",
    "release_all",
    "position",
    "desktop",
    "available_keys",
}


def decode_key(value):
    return Key(**value) if isinstance(value, dict) else value


def execute(adapter, command):
    if not isinstance(command, dict):
        raise ValueError("command must be a JSON object")
    arguments = command.copy()
    action = arguments.pop("action", None)
    if action not in METHODS:
        raise ValueError(f"Unknown action {action!r}")
    if "key" in arguments:
        arguments["key"] = decode_key(arguments["key"])
    if action == "hotkey":
        keys = arguments.pop("keys", None)
        if not isinstance(keys, list):
            raise ValueError("hotkey keys must be a list")
        result = adapter.hotkey(*(decode_key(key) for key in keys), **arguments)
    else:
        result = getattr(adapter, action)(**arguments)
    if action == "desktop":
        result = asdict(result)
    return {"action": action, "status": "submitted", "result": result}


def run(stream, output, errors, *, factory=InputAdapter):
    try:
        with factory() as adapter:
            for number, line in enumerate(stream, 1):
                if not line.strip():
                    continue
                try:
                    result = execute(adapter, json.loads(line))
                except Exception as error:
                    errors.write(json.dumps({"line": number, "error": str(error)}) + "\n")
                    return 2
                output.write(json.dumps(result, ensure_ascii=True) + "\n")
                output.flush()
        return 0
    except Exception as error:
        errors.write(json.dumps({"error": str(error)}) + "\n")
        return 2


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", nargs="?", help="JSONL file; defaults to stdin")
    args = parser.parse_args()
    if args.file:
        with open(args.file, encoding="utf-8") as stream:
            return run(stream, sys.stdout, sys.stderr)
    return run(sys.stdin, sys.stdout, sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
