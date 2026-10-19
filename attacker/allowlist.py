"""Where the attacker is allowed to write: loopback, a Docker-internal hostname from
`docker-compose.yml`, or an address explicitly listed in `ATTACKER_ALLOWLIST`. Nothing else, no
flag to bypass it. This is the only check standing between this tool and a real network target,
so it fails closed: an unparsable or empty host is refused.
"""

LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1", "0.0.0.0"})
COMPOSE_HOSTS = frozenset({"plant-emulator"})  # service name in docker-compose.yml


class AllowlistError(ValueError):
    """The requested host is not an allowed attack target."""


def is_loopback(host: str) -> bool:
    return host in LOOPBACK_HOSTS or host.startswith("127.")


def allowed_hosts(extra: str) -> frozenset[str]:
    extras = {h.strip() for h in extra.split(",") if h.strip()}
    return LOOPBACK_HOSTS | COMPOSE_HOSTS | frozenset(extras)


def check_host(host: str, extra_allowlist: str = "") -> None:
    """Raise AllowlistError unless `host` is loopback, the compose service name, or listed in
    `extra_allowlist` (comma-separated, from `ATTACKER_ALLOWLIST`)."""
    host = (host or "").strip()
    if not host:
        raise AllowlistError("empty host")
    if is_loopback(host) or host in allowed_hosts(extra_allowlist):
        return
    raise AllowlistError(
        f"{host!r} is not an allowed attack target "
        f"(loopback, {sorted(COMPOSE_HOSTS)}, or ATTACKER_ALLOWLIST only)"
    )
