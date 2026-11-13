"""Bounded, UNCALIBRATED two-sphere toy chamber for physics diagnostics.

A simple axis-aligned sealed box, gravity, a prescribed uniform air velocity,
linear drag, sinusoidal x acceleration, wall reflections and one instantaneous
frictionless sphere contact per step. No rotating hardware, turbulent CFD,
sphere spin, calibrated ball parameters, capture chute, live sensor readings,
lottery identities, or actual draw prediction. Not part of formal V4.7.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from math import isfinite, pi, sin

from .physics_audit import Ball, collide, kinetic_energy


def _finite_number(value):
    return type(value) in (float, int) and isfinite(value)


def _vec3(value, label):
    if (not isinstance(value, (tuple, list)) or len(value) != 3
            or any(not _finite_number(v) for v in value)):
        raise ValueError("INVALID_" + label)
    return tuple(float(v) for v in value)


@dataclass(frozen=True)
class Chamber:
    """All lengths in m, accelerations m/s^2, air velocity m/s, drag s^-1."""

    lengths: tuple[float, float, float]
    gravity: tuple[float, float, float] = (0.0, 0.0, -9.81)
    air_velocity: tuple[float, float, float] = (0.0, 0.0, 0.0)
    drag_rate: float = 0.0
    shake_acceleration: float = 0.0
    shake_frequency_hz: float = 0.0
    restitution: float = 1.0

    def __post_init__(self):
        lengths = _vec3(self.lengths, "BOX_LENGTHS")
        if any(value <= 0 for value in lengths):
            raise ValueError("INVALID_BOX_LENGTHS")
        object.__setattr__(self, "lengths", lengths)
        object.__setattr__(self, "gravity", _vec3(self.gravity, "GRAVITY"))
        object.__setattr__(self, "air_velocity", _vec3(self.air_velocity, "AIR_VELOCITY"))
        for name in ("drag_rate", "shake_acceleration", "shake_frequency_hz", "restitution"):
            value = getattr(self, name)
            if not _finite_number(value):
                raise ValueError("INVALID_" + name.upper())
            if name in ("drag_rate", "shake_frequency_hz", "shake_acceleration") and value < 0:
                raise ValueError("NEGATIVE_" + name.upper())
            if name == "restitution" and not 0 <= value <= 1:
                raise ValueError("INVALID_RESTITUTION")
            object.__setattr__(self, name, float(value))


def _confine(chamber: Chamber, ball: Ball) -> Ball:
    """Clamp to a wall and reflect only when moving toward it."""
    pos = list(ball.position)
    vel = list(ball.velocity)
    for axis, length in enumerate(chamber.lengths):
        if 2 * ball.radius >= length:
            raise ValueError("BALL_DOES_NOT_FIT_CHAMBER")
        low, high = ball.radius, length - ball.radius
        if pos[axis] < low:
            pos[axis] = low
            if vel[axis] < 0:
                vel[axis] = -chamber.restitution * vel[axis]
        if pos[axis] > high:
            pos[axis] = high
            if vel[axis] > 0:
                vel[axis] = -chamber.restitution * vel[axis]
    return replace(ball, position=tuple(pos), velocity=tuple(vel))


def step_chamber(chamber: Chamber, balls: list[Ball], *, dt: float, time: float) -> list[Ball]:
    """One explicit semi-implicit Euler step; at most two balls, no prediction."""
    if not isinstance(chamber, Chamber):
        raise ValueError("CHAMBER_REQUIRED")
    if (not isinstance(balls, (tuple, list)) or not 1 <= len(balls) <= 2
            or any(not isinstance(ball, Ball) for ball in balls)):
        raise ValueError("ONE_OR_TWO_BALLS_REQUIRED")
    if (not _finite_number(dt) or not 0 < dt <= 0.1
            or not _finite_number(time) or time < 0):
        raise ValueError("INVALID_STEP_OR_TIME")
    accel_x = chamber.shake_acceleration * sin(2 * pi * chamber.shake_frequency_hz * time)
    output = []
    for ball in balls:
        if any(not 0 <= x <= L for x, L in zip(ball.position, chamber.lengths)):
            raise ValueError("BALL_OUTSIDE_CHAMBER")
        accel = tuple(
            chamber.gravity[i] +
            chamber.drag_rate * (chamber.air_velocity[i] - ball.velocity[i]) +
            (accel_x if i == 0 else 0)
            for i in range(3)
        )
        vel = tuple(ball.velocity[i] + accel[i] * dt for i in range(3))
        pos = tuple(ball.position[i] + vel[i] * dt for i in range(3))
        if any(not isfinite(x) for x in pos + vel):
            raise ValueError("NONFINITE_PHYSICS_STATE")
        output.append(_confine(chamber, replace(ball, position=pos, velocity=vel)))
    if len(output) == 2:
        a, b = output
        # First apply the previously tested impulse kernel if contact is
        # approaching. Resolve interpenetration to avoid repeated impulses.
        a, b = collide(a, b, restitution=chamber.restitution)
        diff = tuple(b.position[i] - a.position[i] for i in range(3))
        distance2 = sum(v * v for v in diff)
        min_distance = a.radius + b.radius
        if distance2 == 0:
            raise ValueError("AMBIGUOUS_CONTACT_NORMAL")
        if distance2 < min_distance ** 2:
            from math import sqrt
            distance = sqrt(distance2)
            n = tuple(x / distance for x in diff)
            delta = min_distance - distance
            inv_a, inv_b = 1.0 / a.mass, 1.0 / b.mass
            wa, wb = inv_a / (inv_a + inv_b), inv_b / (inv_a + inv_b)
            a = replace(a, position=tuple(a.position[i] - wa * delta * n[i] for i in range(3)))
            b = replace(b, position=tuple(b.position[i] + wb * delta * n[i] for i in range(3)))
            a, b = _confine(chamber, a), _confine(chamber, b)
        output = [a, b]
    return output


def simulate_chamber(
    chamber: Chamber, balls: list[Ball], *, steps: int, dt: float
) -> dict:
    """Return bounded uncalibrated motion diagnostics, never drawn numbers."""
    if type(steps) is not int or not 1 <= steps <= 10000:
        raise ValueError("INVALID_STEP_COUNT")
    if not isinstance(balls, (tuple, list)) or len(balls) != 2:
        raise ValueError("EXACTLY_TWO_BALLS_REQUIRED")
    state = list(balls)
    for k in range(steps):
        state = step_chamber(chamber, state, dt=dt, time=k * dt)
    return {
        "status": "UNCALIBRATED_TWO_BALL_BOX_DIAGNOSTIC",
        "steps": steps,
        "dt_seconds": float(dt),
        "ball_state": [
            {"position_m": list(ball.position),
             "velocity_m_s": list(ball.velocity),
             "kinetic_energy_j": kinetic_energy(ball)}
            for ball in state
        ],
        "mechanics": ["semi_implicit_euler", "linear_air_drag", "uniform_air_velocity",
                      "gravity", "sinusoidal_shaker", "wall_restitution",
                      "frictionless_sphere_impulse"],
        "machine_measured": False,
        "physical_forecast_supported": False,
        "formal_A": 0,
        "edge": "NO_EDGE",
    }
