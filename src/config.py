"""Configuration loader. Reads ``config.yaml`` from the repo root.

Usage:
    from src.config import load_config
    cfg = load_config()
    cfg.camera.width
"""
from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]


def _to_namespace(obj: Any) -> Any:
    """Recursively convert dicts to SimpleNamespace for dot-access."""
    if isinstance(obj, dict):
        return SimpleNamespace(**{k: _to_namespace(v) for k, v in obj.items()})
    if isinstance(obj, list):
        return [_to_namespace(v) for v in obj]
    return obj


def load_config(path: str | os.PathLike | None = None) -> SimpleNamespace:
    """Load YAML config and return a SimpleNamespace tree.

    Search order:
      1. explicit ``path`` argument
      2. ``$MWS_CONFIG`` environment variable
      3. ``<repo>/config.yaml``
      4. ``<repo>/config.example.yaml`` (fallback, with a warning)
    """
    if path is None:
        path = os.environ.get("MWS_CONFIG")
    if path is None:
        candidate = REPO_ROOT / "config.yaml"
        if not candidate.exists():
            candidate = REPO_ROOT / "config.example.yaml"
            print(
                f"[config] WARNING: config.yaml not found, using "
                f"{candidate.name}. Copy it and customize."
            )
        path = candidate

    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)

    cfg = _to_namespace(data)
    cfg._path = str(path)  # type: ignore[attr-defined]
    cfg._repo_root = str(REPO_ROOT)  # type: ignore[attr-defined]
    return cfg


def resolve_path(p: str) -> Path:
    """Resolve a possibly-relative path against repo root."""
    pp = Path(p)
    if pp.is_absolute():
        return pp
    return REPO_ROOT / pp


if __name__ == "__main__":
    import json

    cfg = load_config()
    # quick dump for debugging
    def _dump(ns):
        if isinstance(ns, SimpleNamespace):
            return {k: _dump(v) for k, v in vars(ns).items() if not k.startswith("_")}
        if isinstance(ns, list):
            return [_dump(v) for v in ns]
        return ns

    print(json.dumps(_dump(cfg), indent=2, ensure_ascii=False))
