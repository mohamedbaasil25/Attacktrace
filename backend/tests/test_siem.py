"""SOC/SIEM export (Production Transition Roadmap, Phase 3 MVP): `SiemNotifier` transition
detection and payload shape. The actual HTTP POST is exercised against a local HTTP server, not
mocked, so the stdlib `urllib.request` plumbing is genuinely tested end to end."""

import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import ClassVar

import pytest

from app.schemas import Incident, OriginCandidate
from app.siem import SiemNotifier, event_payload


def _inc(id_: str, status: str) -> Incident:
    return Incident(
        id=id_,
        status=status,  # type: ignore[arg-type]
        detected_at=0.0,
        origin=[OriginCandidate(id="LIT101", type="sensor", confidence=0.5)],
        path=[],
        path_edges=[],
        explanation="",
        action="",
        mitre="T0856",
        mitre_name="Spoof Reporting Message",
        baseline_alarms=[],
    )


def test_event_payload_shape() -> None:
    payload = event_payload(_inc("inc_001", "open"), "open")
    assert payload["event"] == "open"
    assert payload["incident_id"] == "inc_001"
    assert payload["origin"] == ["LIT101"]


def test_transitions_fires_once_per_status_change() -> None:
    notifier = SiemNotifier(url="http://example.invalid")
    first = notifier.transitions([_inc("inc_001", "localizing")])
    assert [(i.id, e) for i, e in first] == [("inc_001", "localizing")]
    # same status again: no new event
    assert notifier.transitions([_inc("inc_001", "localizing")]) == []
    # status changes: one new event
    second = notifier.transitions([_inc("inc_001", "open")])
    assert [(i.id, e) for i, e in second] == [("inc_001", "open")]


def test_transitions_tracks_multiple_incidents_independently() -> None:
    notifier = SiemNotifier(url="http://example.invalid")
    events = notifier.transitions([_inc("inc_001", "open"), _inc("inc_002", "localizing")])
    assert {(i.id, e) for i, e in events} == {("inc_001", "open"), ("inc_002", "localizing")}
    # inc_001 changes, inc_002 doesn't
    events2 = notifier.transitions([_inc("inc_001", "closed"), _inc("inc_002", "localizing")])
    assert [(i.id, e) for i, e in events2] == [("inc_001", "closed")]


def test_transitions_forgets_incidents_no_longer_present() -> None:
    notifier = SiemNotifier(url="http://example.invalid")
    notifier.transitions([_inc("inc_001", "open")])
    notifier.transitions([])  # inc_001 vanished (e.g. aged out of the flat history window)
    # if inc_001 reappears unchanged, it's treated as new again (no stale memory of it)
    events = notifier.transitions([_inc("inc_001", "open")])
    assert [(i.id, e) for i, e in events] == [("inc_001", "open")]


class _CapturingHandler(BaseHTTPRequestHandler):
    received: ClassVar[list[dict[str, object]]] = []

    def do_POST(self) -> None:
        length = int(self.headers["Content-Length"])
        self.received.append(json.loads(self.rfile.read(length)))
        self.send_response(200)
        self.end_headers()

    def log_message(self, format: str, *args: object) -> None:
        pass  # quiet test output


@pytest.fixture
def local_webhook() -> str:
    _CapturingHandler.received = []
    server = HTTPServer(("127.0.0.1", 0), _CapturingHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}/"
    server.shutdown()
    thread.join(timeout=2)


async def test_notify_posts_a_real_http_request(local_webhook: str) -> None:
    notifier = SiemNotifier(url=local_webhook, timeout_s=2.0)
    await notifier.notify([_inc("inc_001", "open")])
    await asyncio.sleep(0.1)  # the handler runs on its own thread
    assert len(_CapturingHandler.received) == 1
    assert _CapturingHandler.received[0]["incident_id"] == "inc_001"


async def test_notify_does_not_raise_when_the_webhook_is_unreachable() -> None:
    notifier = SiemNotifier(url="http://127.0.0.1:1", timeout_s=0.5)
    await notifier.notify([_inc("inc_001", "open")])  # must not raise
