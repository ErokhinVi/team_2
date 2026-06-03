"""Per-customer session lock to serialise actions on a single profile.

Two participants can each open the mobile bank in their own tab. Without a
lock, both could be acting on behalf of the same customer at the same time
and clobber each other's state (e.g. opening two deposits from the same
balance simultaneously). This module hands out short-lived leases keyed
by `client_id`. While a session holds a lease:
  * other sessions calling acquire() get refused with a friendly "held by ..."
  * the holder must heartbeat() every ~30s to keep it alive (90s TTL)
  * any mutation endpoint with a different X-Session-Id gets a 423

State is in-memory. The retail block runs as a single instance per team, so
that's fine for this workshop.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

LEASE_SECONDS = 90  # long enough to type a transfer, short enough to recover


@dataclass
class Lease:
    session_id: str
    holder_label: str
    expires_at: float


_leases: dict[str, Lease] = {}
_mu = asyncio.Lock()


def _now() -> float:
    return time.monotonic()


async def acquire(client_id: str, session_id: str, holder_label: str = "") -> dict:
    """Try to take or extend the lease on `client_id` for `session_id`."""
    async with _mu:
        now = _now()
        existing = _leases.get(client_id)
        if existing and existing.expires_at > now and existing.session_id != session_id:
            return {
                "ok": False,
                "held_by": existing.holder_label or "another session",
                "expires_in": int(existing.expires_at - now),
            }
        _leases[client_id] = Lease(
            session_id=session_id,
            holder_label=holder_label or (existing.holder_label if existing else ""),
            expires_at=now + LEASE_SECONDS,
        )
        return {"ok": True, "expires_in": LEASE_SECONDS, "session_id": session_id}


async def release(client_id: str, session_id: str) -> dict:
    async with _mu:
        existing = _leases.get(client_id)
        if existing and existing.session_id == session_id:
            del _leases[client_id]
            return {"ok": True}
        return {"ok": False, "not_holder": True}


async def status(client_id: str, session_id: str | None) -> dict:
    async with _mu:
        existing = _leases.get(client_id)
        now = _now()
        if not existing or existing.expires_at <= now:
            return {"locked": False, "mine": False}
        return {
            "locked": True,
            "mine": session_id is not None and existing.session_id == session_id,
            "held_by": existing.holder_label or "another session",
            "expires_in": int(existing.expires_at - now),
        }


async def is_allowed(client_id: str, session_id: str | None) -> bool:
    """True if (no lock or expired) OR (this session holds it)."""
    async with _mu:
        existing = _leases.get(client_id)
        if not existing or existing.expires_at <= _now():
            return True
        return session_id is not None and existing.session_id == session_id
