"""Load config.yaml once and expand paths."""
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parent.parent


def load_config(path: Path | None = None) -> dict:
    path = path or ROOT / "config.yaml"
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found. Copy config.example.yaml to config.yaml and edit it."
        )
    cfg = yaml.safe_load(path.read_text())
    paths = cfg.setdefault("paths", {})
    for key, val in paths.items():
        p = Path(val).expanduser()
        paths[key] = p if p.is_absolute() else ROOT / p
    return cfg
