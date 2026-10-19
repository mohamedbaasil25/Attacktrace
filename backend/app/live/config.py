"""LIVE configuration: validated once at start so a bad value fails fast with a clear message."""

from pathlib import Path

from pydantic import BaseModel, ConfigDict, ValidationError

from app.config import Settings
from app.live.tagmap import TagMap, TagMapError, load_tagmap


class LiveConfigError(ValueError):
    """A LIVE setting is invalid; the message names the setting and the rule."""


class LiveConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    host: str
    port: int
    tagmap_path: Path
    poll_s: float
    timeout_s: float
    stale_after_s: float
    max_age_s: float
    frozen_after_s: float
    max_in_flight: int
    block_gap: int
    backoff_base_s: float
    backoff_max_s: float

    @classmethod
    def from_settings(cls, s: Settings) -> "LiveConfig":
        try:
            cfg = cls(
                host=s.live_host,
                port=s.live_port,
                tagmap_path=s.live_tagmap,
                poll_s=s.live_poll_s,
                timeout_s=s.live_timeout_s,
                stale_after_s=s.live_stale_after_s,
                max_age_s=s.live_max_age_s,
                frozen_after_s=s.live_frozen_after_s,
                max_in_flight=s.live_max_in_flight,
                block_gap=s.live_block_gap,
                backoff_base_s=s.live_backoff_base_s,
                backoff_max_s=s.live_backoff_max_s,
            )
        except ValidationError as exc:
            raise LiveConfigError(f"invalid LIVE setting: {exc.errors()[0]['msg']}") from exc
        cfg.check()
        return cfg

    def check(self) -> None:
        rules = [
            (bool(self.host.strip()), "AT_LIVE_HOST must not be empty"),
            (0 < self.port < 65536, "AT_LIVE_PORT must be 1..65535"),
            (0.05 <= self.poll_s <= 5.0, "AT_LIVE_POLL_S must be 0.05..5 s"),
            (0.0 < self.timeout_s <= 10.0, "AT_LIVE_TIMEOUT_S must be 0..10 s"),
            (
                self.stale_after_s >= 2 * self.poll_s,
                "AT_LIVE_STALE_AFTER_S must be at least twice AT_LIVE_POLL_S",
            ),
            (
                self.max_age_s > self.stale_after_s,
                "AT_LIVE_MAX_AGE_S must exceed AT_LIVE_STALE_AFTER_S",
            ),
            (self.frozen_after_s > self.stale_after_s, "AT_LIVE_FROZEN_AFTER_S is too small"),
            (1 <= self.max_in_flight <= 8, "AT_LIVE_MAX_IN_FLIGHT must be 1..8"),
            (self.block_gap >= 0, "AT_LIVE_BLOCK_GAP must not be negative"),
            (
                0 < self.backoff_base_s <= self.backoff_max_s,
                "AT_LIVE_BACKOFF_BASE_S must be positive and at most AT_LIVE_BACKOFF_MAX_S",
            ),
        ]
        for ok, message in rules:
            if not ok:
                raise LiveConfigError(message)


def load_live(settings: Settings) -> tuple[LiveConfig, TagMap]:
    """Validated config and tag map, or a LiveConfigError that says what to fix."""
    cfg = LiveConfig.from_settings(settings)
    try:
        return cfg, load_tagmap(cfg.tagmap_path)
    except TagMapError as exc:
        raise LiveConfigError(str(exc)) from exc
