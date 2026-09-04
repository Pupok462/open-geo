from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from kernel.schema import Kernel

REPO = Path(__file__).resolve().parent.parent
CORE_DIR = REPO / "core"


def path_for(slug: str, root: Path | None = None) -> Path:
    return (root or CORE_DIR) / slug / "kernel.json"


def save(kernel: Kernel, root: Path | None = None) -> Path:
    kernel.updated_at = datetime.now(timezone.utc).isoformat()
    path = path_for(kernel.slug, root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(kernel.model_dump_json(indent=2), encoding="utf-8")
    return path


def load(slug: str, root: Path | None = None) -> Kernel:
    path = path_for(slug, root)
    return Kernel.model_validate_json(path.read_text(encoding="utf-8"))


def slugify(text: str) -> str:
    import re

    t = (text or "").lower().replace("ё", "е")
    t = re.sub(r"[^a-zа-я0-9]+", "-", t).strip("-")
    return t[:48] or "brand"
