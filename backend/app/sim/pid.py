"""Discrete PI(D) controller with output clamping and conditional-integration anti-windup."""

from dataclasses import dataclass


@dataclass
class PID:
    kp: float
    ki: float
    kd: float = 0.0
    bias: float = 0.0
    lo: float = 0.0
    hi: float = 1.0
    integral: float = 0.0
    _prev_error: float | None = None

    def update(self, error: float, dt: float) -> float:
        derivative = 0.0 if self._prev_error is None else (error - self._prev_error) / dt
        self._prev_error = error
        unclamped = self.bias + self.kp * error + self.integral + self.kd * derivative
        saturated_hi = unclamped >= self.hi and error > 0
        saturated_lo = unclamped <= self.lo and error < 0
        if not (saturated_hi or saturated_lo):
            self.integral += self.ki * error * dt
        return min(self.hi, max(self.lo, unclamped))

    def reset(self) -> None:
        self.integral = 0.0
        self._prev_error = None
