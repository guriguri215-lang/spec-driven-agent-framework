import json
from pathlib import Path
from typing import Any


def repository_root() -> Path:
    return Path(__file__).resolve().parents[1]


def m2_example(name: str) -> Path:
    return repository_root() / "examples" / "m2-orchestration" / name


def load_example(name: str) -> dict[str, Any]:
    value: object = json.loads(m2_example(name).read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def write_json(path: Path, value: object) -> Path:
    path.write_text(json.dumps(value), encoding="utf-8")
    return path
