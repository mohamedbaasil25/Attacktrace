"""Hook points where an attacker can tamper with the plant (implemented by `attacks/`)."""

from typing import Protocol


class Overlay(Protocol):
    def sensor(self, node: str, value: float, t: float) -> float:
        """Return the reported value for a sensor given its honest reading."""
        ...

    def actuator(self, node: str, command: float, t: float) -> float:
        """Return the command the actuator actually receives."""
        ...

    def setpoint(self, node: str, value: float, t: float) -> float:
        """Return the setpoint the controller actually uses."""
        ...


class NoOverlay:
    def sensor(self, node: str, value: float, t: float) -> float:
        return value

    def actuator(self, node: str, command: float, t: float) -> float:
        return command

    def setpoint(self, node: str, value: float, t: float) -> float:
        return value
