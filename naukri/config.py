"""Environment and paths.

Every path is resolved relative to the repo root rather than the cwd, so a run
from systemd behaves identically to a run from the shell.
"""

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent

# .env is read before the paths below so DATA_DIR can be set there too.
load_dotenv(ROOT / ".env")

# Everything the script writes lives here. Defaults to the repo, but the
# container points it at a mounted volume so the session and the canonical
# headline survive a container being replaced.
DATA_DIR = Path(os.getenv("DATA_DIR") or ROOT)

COOKIE_FILE = DATA_DIR / "cookies.pkl"
STATE_FILE = DATA_DIR / "state.json"
LOG_DIR = DATA_DIR / "logs"
ARTIFACT_DIR = DATA_DIR / "artifacts"

BASE_URL = "https://www.naukri.com/"
PROFILE_URL = "https://www.naukri.com/mnjuser/profile"
LOGIN_URL = "https://www.naukri.com/nlogin/login"

# Naukri caps the resume headline at 250 characters.
HEADLINE_MAX = 250

MARKER = os.getenv("MARKER", ".")

# Set inside the container, where Chromium and its driver come from apt rather
# than from Selenium Manager (which would need to reach the network at run time).
CHROME_BINARY = os.getenv("CHROME_BINARY") or None
CHROMEDRIVER = os.getenv("CHROMEDRIVER") or None


class ConfigError(RuntimeError):
    """Something the user needs to fix before the script can run."""


def _truthy(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def headless_default() -> bool:
    return _truthy(os.getenv("HEADLESS"), True)


def no_sandbox() -> bool:
    """Chrome's sandbox needs privileges a default container does not grant."""
    return _truthy(os.getenv("NO_SANDBOX"), False)


def credentials() -> tuple[str, str]:
    """Return (email, password), failing loudly rather than half-running."""
    email = os.getenv("NAUKRI_EMAIL")
    password = os.getenv("NAUKRI_PASSWORD")
    if not email or not password:
        raise ConfigError(
            f"NAUKRI_EMAIL and NAUKRI_PASSWORD must be set. "
            f"Copy {ROOT / '.env.example'} to {ROOT / '.env'} and fill it in."
        )
    return email, password


def setup_logging(verbose: bool = False) -> logging.Logger:
    """Log to stdout (journald picks this up) and to a rotating file."""
    LOG_DIR.mkdir(exist_ok=True)

    root = logging.getLogger()
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    root.handlers.clear()

    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")

    stream = logging.StreamHandler()
    stream.setFormatter(fmt)
    root.addHandler(stream)

    rotating = RotatingFileHandler(
        LOG_DIR / "naukri.log", maxBytes=512_000, backupCount=3
    )
    rotating.setFormatter(fmt)
    root.addHandler(rotating)

    # Selenium's own logging is noisy and leaks nothing useful at INFO.
    logging.getLogger("selenium").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    return logging.getLogger("naukri")
