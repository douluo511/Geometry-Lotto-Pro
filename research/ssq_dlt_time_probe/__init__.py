"""Offline, synthetic-only RFC 3161 technical verification.

No network client, prediction workflow, SQLite access, or formal trust approval.
"""

from .verifier import Inputs, VerificationError, verify_offline

__all__ = ["Inputs", "VerificationError", "verify_offline"]
