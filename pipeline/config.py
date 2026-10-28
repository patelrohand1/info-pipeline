"""Load config.yaml once and expand paths.

Secrets never live in config.yaml (it's committed). They come from environment variables:
GEMINI_API_KEY, TURSO_DATABASE_URL, TURSO_AUTH_TOKEN. Locally those are read from .streamlit/secrets.toml
(gitignored); Streamlit Cloud and GitHub Actions set them from their own secret stores.
"""
import os
import tomllib
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parent.parent
SECRETS = ROOT / ".streamlit" / "secrets.toml"
# Streamlit Community Cloud checks the repo out under /mount/src.
IS_CLOUD = str(ROOT).startswith("/mount/src") or bool(os.environ.get("GITHUB_ACTIONS"))


def load_secrets() -> None:
    if SECRETS.exists():
        for key, val in tomllib.loads(SECRETS.read_text()).items():
            if isinstance(val, str):
                os.environ.setdefault(key, val)


load_secrets()


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
