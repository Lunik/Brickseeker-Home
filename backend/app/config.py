"""Runtime configuration, read once from the environment.

Everything a self-hosted deployment can tune lives here. Nothing secret is baked in:
`BRICKSEEKER_SECRET_KEY` is generated on first run and persisted under the data directory
when the operator doesn't supply one, so a plain `docker run` works without ceremony while a
real deployment can pin it (rotating it makes stored third-party credentials unreadable —
see `security.py`).
"""

from __future__ import annotations

import os
import secrets
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="BRICKSEEKER_", extra="ignore")

    # --- Storage -------------------------------------------------------------------
    data_dir: Path = Path("/data")
    """Everything mutable lives here: SQLite file, image cache, catalogue snapshots."""

    database_url: str | None = None
    """Overrides the default `sqlite+aiosqlite:///{data_dir}/brickseeker.db`."""

    # --- Access control ------------------------------------------------------------
    password: str | None = None
    """When set, the UI/API require this password (single-user app). Unset = open, which is
    the sane default for a LAN-only self-hosted deployment."""

    session_ttl_days: int = 30

    # --- Behaviour -----------------------------------------------------------------
    scraping_enabled: bool = True
    """Master switch for the headless-browser price sources (lego.com/Amazon/Cdiscount).
    Turning it off leaves BrickLink (a plain signed API call) working and keeps the image
    from ever launching Chromium."""

    scrape_timeout_seconds: float = 30.0
    scrape_delay_between_sets: float = 1.5
    """Politeness delay between two sets in a batch price refresh — mirrors the iOS app's
    `CollectionPriceUpdater.delayBetweenSets`."""

    background_refresh_enabled: bool = True
    background_refresh_interval_minutes: int = 60
    background_refresh_batch_size: int = 8
    """How many overdue watched sets one scheduler tick processes (iOS: a granted BGTask wake-up)."""

    ocr_enabled: bool = True
    ocr_languages: str = "eng+fra"

    rebrickable_min_interval: float = 1.0
    brickset_min_interval: float = 1.0
    bricklink_min_interval: float = 1.0
    """Per-host request spacing, one throttler each — the hosts are unrelated and a burst to one
    shouldn't slow the others (mirrors the iOS `RequestThrottler` instances)."""

    image_cache_max_bytes: int = 512 * 1024 * 1024

    cors_origins: str = ""
    """Comma-separated extra origins. The bundled frontend is same-origin, so this is only for
    running Vite's dev server against a container."""

    log_level: str = "INFO"

    # --- Derived -------------------------------------------------------------------
    @property
    def db_path(self) -> Path:
        return self.data_dir / "brickseeker.db"

    @property
    def sqlalchemy_url(self) -> str:
        if self.database_url:
            return self.database_url
        return f"sqlite+aiosqlite:///{self.db_path}"

    @property
    def image_cache_dir(self) -> Path:
        return self.data_dir / "images"

    @property
    def catalog_dir(self) -> Path:
        return self.data_dir / "catalog"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    def ensure_dirs(self) -> None:
        for path in (self.data_dir, self.image_cache_dir, self.catalog_dir):
            path.mkdir(parents=True, exist_ok=True)

    def secret_key(self) -> str:
        """The key stored credentials are encrypted with.

        Read from the environment when provided; otherwise generated once and persisted to
        `{data_dir}/secret.key` (0600). Losing it doesn't lose the collection — only the
        stored API credentials, which the user re-enters in Réglages.
        """
        env = os.environ.get("BRICKSEEKER_SECRET_KEY")
        if env:
            return env
        self.ensure_dirs()
        key_file = self.data_dir / "secret.key"
        if key_file.exists():
            return key_file.read_text().strip()
        generated = secrets.token_urlsafe(48)
        # Created pre-restricted (O_EXCL | 0600), not written-then-chmod'd: the credentials this
        # key decrypts must never be readable by another user even for the instant between the
        # two calls a separate chmod would leave open.
        try:
            fd = os.open(key_file, os.O_CREAT | os.O_WRONLY | os.O_EXCL, 0o600)
        except FileExistsError:
            return key_file.read_text().strip()
        with os.fdopen(fd, "w") as handle:
            handle.write(generated)
        return generated


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_dirs()
    return settings


settings = get_settings()
