"""Which engine is live: the SIM plant or the HAI replay."""

from typing import Any, Protocol

from app.schemas import Incident, LiveMessage, Topology


class Runtime(Protocol):
    mode: str
    latest: LiveMessage | None
    incidents: list[Incident]
    detector_kind: str | None

    @property
    def uptime_s(self) -> float: ...

    def step_sample(self) -> LiveMessage: ...

    def reset(self) -> None: ...

    def topology(self) -> Topology: ...


def active_runtime(state: Any) -> Runtime:
    """`state` is `app.state`: SIM unless the user chose HAI or LIVE and that runtime exists."""
    if state.mode == "hai" and state.hai is not None:
        hai: Runtime = state.hai
        return hai
    if state.mode == "live" and getattr(state, "live", None) is not None:
        live: Runtime = state.live
        return live
    runtime: Runtime = state.engine
    return runtime
