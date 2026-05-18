"""ECS task scale-in protection via the container agent endpoint.

When at least one GUI session is active the task is marked as protected so
that ECS auto-scaling and deployment scale-in events cannot terminate it.
Protection is renewed periodically (before the expiry window closes) and
cleared when the last GUI session ends.

The module is a no-op when ``ECS_AGENT_URI`` is not set (local development).
"""

import json
import os
import threading

import requests

from aind_ephys_portal.session_logging import list_gui_sessions

# --- Configuration -----------------------------------------------------------

PROTECTION_DURATION_MINUTES = 60
"""Each protection window lasts this long. Renewed before it expires."""

_REFRESH_INTERVAL_SECONDS = 50 * 60  # 50 min — well before 60-min expiry

# --- Module state (guarded by _lock) -----------------------------------------

_lock = threading.Lock()
_is_protected = False
_refresh_timer: threading.Timer | None = None


# --- Low-level ECS agent call ------------------------------------------------

def _agent_uri() -> str | None:
    return os.environ.get("ECS_AGENT_URI")


def _set_task_protection(enabled: bool, expires_minutes: int = PROTECTION_DURATION_MINUTES) -> bool:
    """PUT to the ECS agent endpoint. Returns True on success."""
    uri = _agent_uri()
    if not uri:
        action = "protect" if enabled else "unprotect"
        print(f"[ecs_protection] No ECS_AGENT_URI — skipping {action} (local dev)")
        return True  # treat as success in local dev

    url = f"{uri}/task-protection/v1/state"
    body: dict = {"ProtectionEnabled": enabled}
    if enabled:
        body["ExpiresInMinutes"] = expires_minutes

    try:
        resp = requests.put(url, json=body, timeout=5)
        data = resp.json()
        if "error" in data:
            print(f"[ecs_protection] Agent error: {json.dumps(data['error'])}")
            return False
        print(f"[ecs_protection] Task protection set: enabled={enabled}, response={json.dumps(data)}")
        return True
    except Exception as exc:
        print(f"[ecs_protection] Failed to set protection (enabled={enabled}): {exc}")
        return False


# --- High-level API ----------------------------------------------------------

def _cancel_refresh_timer():
    global _refresh_timer
    if _refresh_timer is not None:
        _refresh_timer.cancel()
        _refresh_timer = None


def _schedule_refresh():
    global _refresh_timer
    _cancel_refresh_timer()
    _refresh_timer = threading.Timer(_REFRESH_INTERVAL_SECONDS, _refresh_protection)
    _refresh_timer.daemon = True
    _refresh_timer.start()


def _refresh_protection():
    """Called by the timer — renew protection if sessions still exist, else clear."""
    with _lock:
        if len(list_gui_sessions()) > 0:
            print("[ecs_protection] Renewing task protection (sessions still active)")
            _set_task_protection(True)
            _schedule_refresh()
        else:
            print("[ecs_protection] No sessions at refresh time — clearing protection")
            _unprotect_task_locked()


def _unprotect_task_locked():
    """Must be called while holding _lock."""
    global _is_protected
    _cancel_refresh_timer()
    _set_task_protection(False)
    _is_protected = False


def protect_task():
    """Enable scale-in protection for this task (idempotent while protected)."""
    global _is_protected
    with _lock:
        if _is_protected:
            return
        if _set_task_protection(True):
            _is_protected = True
            _schedule_refresh()


def unprotect_task():
    """Disable scale-in protection for this task."""
    with _lock:
        if not _is_protected:
            return
        _unprotect_task_locked()


def is_protected() -> bool:
    return _is_protected


def get_protection_status() -> dict | None:
    """GET the current protection status from the ECS agent. Returns None in local dev."""
    uri = _agent_uri()
    if not uri:
        return {"local_dev": True, "is_protected": _is_protected}
    try:
        resp = requests.get(f"{uri}/task-protection/v1/state", timeout=5)
        return resp.json()
    except Exception as exc:
        return {"error": str(exc)}
