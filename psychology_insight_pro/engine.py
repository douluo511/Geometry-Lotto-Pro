from __future__ import annotations

# Stable Engine boundary. Business calculations live in core for backward compatibility,
# while production callers depend on this module.
from core import analyze, self_test

__all__ = ["analyze", "self_test"]
