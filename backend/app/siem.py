"""SOC/SIEM export (Production Transition Roadmap, Phase 3 MVP): fires a JSON webhook on every
incident status transition, in every mode. A real SOC wants alerts in its existing tooling
(Splunk HEC, Sentinel Logic Apps, a generic webhook collector, ...), not a second dashboard to
watch.

stdlib `urllib.request` only -- no new dependency. POSTs run off the event loop via
`asyncio.to_thread` so a slow or unreachable webhook can never stall detection; a failure is
logged and otherwise ignored.
"""

import asyncio
import json
import logging
import urllib.error
import urllib.request
from dataclasses import dataclass, field

from app.schemas import Incident

log = logging.getLogger("attacktrace.siem")


def _post(url: str, payload: dict[str, object], timeout_s: float) -> None:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_s):
            pass
    except (urllib.error.URLError, OSError) as exc:
        log.warning("SIEM webhook POST to %s failed: %s", url, exc)


def event_payload(inc: Incident, event: str) -> dict[str, object]:
    return {
        "event": event,
        "incident_id": inc.id,
        "status": inc.status,
        "mode": inc.mode,
        "mitre": inc.mitre,
        "mitre_name": inc.mitre_name,
        "origin": [o.id for o in inc.origin],
        "detected_at": inc.detected_at,
        "ambiguous": inc.ambiguous,
        "isolated_by": inc.isolated_by,
    }


@dataclass
class SiemNotifier:
    url: str
    timeout_s: float = 3.0
    _last_status: dict[str, str] = field(default_factory=dict)

    def transitions(self, incidents: list[Incident]) -> list[tuple[Incident, str]]:
        """The (incident, new-status) pairs for every status change since the last call, diffed
        against the full incident history (`Runtime.incidents`, not just currently-open ones --
        a `closed` incident is deleted from the engine's open set the same tick its status is
        set, so only the flat history ever carries that final transition)."""
        out: list[tuple[Incident, str]] = []
        seen = set()
        for inc in incidents:
            seen.add(inc.id)
            if self._last_status.get(inc.id) != inc.status:
                out.append((inc, inc.status))
                self._last_status[inc.id] = inc.status
        for old_id in list(self._last_status):
            if old_id not in seen:
                del self._last_status[old_id]
        return out

    async def notify(self, incidents: list[Incident]) -> None:
        for inc, event in self.transitions(incidents):
            await asyncio.to_thread(_post, self.url, event_payload(inc, event), self.timeout_s)
