import io
import os
import sys
import time as _time
import contextvars
from pathlib import Path
import psutil
import numpy as np
import requests

import panel as pn

pn.extension()

LOG_DIR = Path("/tmp/aind_ephys_logs")
_log_setup = False
_local_sink = contextvars.ContextVar("local_sink", default=None)


def _log_path_for_session(route, session_id):
    return LOG_DIR / route / str(session_id)


def _get_current_log_path():
    """Get the log path for the current request from curdoc."""
    try:
        doc = pn.state.curdoc
        if doc is not None:
            route = getattr(doc, "_log_route", None)
            session_id = getattr(doc, "_log_session_id", None)
            if route and session_id:
                return _log_path_for_session(route, session_id)
    except Exception:
        pass
    return None


def add_session(route, session_id):
    """Create a log file for this session."""
    path = _log_path_for_session(route, session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text("")
    return path


def remove_session(route, session_id):
    """Remove the log file for this session."""
    path = _log_path_for_session(route, session_id)
    if path.exists():
        path.unlink()
    # Clean up empty route dir
    try:
        if path.parent.exists() and not any(path.parent.iterdir()):
            path.parent.rmdir()
    except Exception:
        pass


def set_session_log_path(route, session_id):
    """No-op kept for compatibility."""
    pass


def list_sessions(skip_routes=None):
    """Return dict of {(route, session_id): Path} for all active log files."""
    if skip_routes is None:
        skip_routes = []
    sessions = {}
    if not LOG_DIR.exists():
        return sessions
    for route_dir in LOG_DIR.iterdir():
        if not route_dir.is_dir():
            continue
        route = route_dir.name
        if route in skip_routes:
            continue
        for log_file in route_dir.iterdir():
            if log_file.is_file():
                session_id = log_file.name
                sessions[(route, session_id)] = log_file
    return sessions


def list_gui_sessions():
    """Helper to list only GUI sessions."""
    return {k: v for k, v in list_sessions().items() if k[0] == "ephys_gui_app"}


def get_ecs_task_id():
    metadata_uri = os.environ.get("ECS_CONTAINER_METADATA_URI_V4")
    if metadata_uri:
        try:
            response = requests.get(f"{metadata_uri}/task", timeout=2)
            task_arn = response.json().get("TaskARN", "")
            return task_arn.split("/")[-1]
        except Exception:
            pass
    return "local-dev"


def get_container_total_memory():
    """Return the container's memory limit in bytes, falling back to host total.

    psutil.virtual_memory().total reads /proc/meminfo (host RAM), which is wrong
    inside ECS/Docker containers that have a lower memory limit set via cgroups.
    """
    # cgroups v2
    try:
        with open("/sys/fs/cgroup/memory.max") as f:
            val = f.read().strip()
            if val != "max":
                return int(val)
    except (FileNotFoundError, ValueError):
        pass
    # cgroups v1
    try:
        with open("/sys/fs/cgroup/memory/memory.limit_in_bytes") as f:
            val = int(f.read().strip())
            if val < 2**62:  # sentinel value meaning "no limit"
                return val
    except (FileNotFoundError, ValueError):
        pass
    return psutil.virtual_memory().total


def get_container_used_memory():
    """Return the container's current memory usage in bytes, falling back to host used.

    Must read from the same cgroup as get_container_total_memory() — psutil reads
    host-level /proc/meminfo, which produces the wrong array size in the inflation calc.
    """
    # cgroups v2
    try:
        with open("/sys/fs/cgroup/memory.current") as f:
            return int(f.read().strip())
    except (FileNotFoundError, ValueError):
        pass
    # cgroups v1
    try:
        with open("/sys/fs/cgroup/memory/memory.usage_in_bytes") as f:
            return int(f.read().strip())
    except (FileNotFoundError, ValueError):
        pass
    return psutil.virtual_memory().used


# --- Dynamic session admission ---
#
# The old static cap (`floor(total_ram / 6 GB)`) was too coarse:
#   - It admits a 2nd heavy session on a task already at 60% RAM (→ OOM)
#   - It rejects a 3rd light session on a task at 30% RAM (→ wasted capacity)
#
# New model: admit if (current_used + per_session_estimate) < safe_max,
# capped by an absolute session-count ceiling as a safety net. Each knob is
# env-tunable so we can adjust without redeploys.


def get_safe_max_ram_pct():
    """Never voluntarily push RAM above this percent of container memory."""
    return float(os.environ.get("SAFE_MAX_RAM_PCT", "75"))


def get_per_session_estimate_pct():
    """Fallback peak RAM cost of one session as a percent of container memory.

    Used by ``can_admit_new_session()`` when the caller cannot supply a more
    accurate per-session estimate (e.g., the analyzer pre-load failed).
    The portal normally passes a *dynamic* estimate computed from the
    analyzer's unit count — see :func:`estimate_session_ram_bytes`.
    """
    return float(os.environ.get("PER_SESSION_ESTIMATE_PCT", "35"))


def get_hard_cap_sessions():
    """Absolute ceiling on concurrent sessions per task.

    Independent of RAM headroom — protects against estimate errors and from
    operational issues (many Bokeh documents + periodic callbacks on one
    process). Also lets the legacy ``MAX_GUI_SESSIONS_PER_TASK`` env var
    keep working as an override.
    """
    if "MAX_GUI_SESSIONS_PER_TASK" in os.environ:
        return int(os.environ["MAX_GUI_SESSIONS_PER_TASK"])
    return int(os.environ.get("HARD_CAP_SESSIONS", "4"))


# Coefficients of the RAM model below. Per-spike and fixed terms were fit with
# tracemalloc on synthetic analyzers (0.5M and 2M spikes) around analyzer load +
# Controller init + get_all_pcs(), then checked against process RSS for a full
# run_mainwindow() on a remote 1252-unit / 24.7M-spike session (lazy and non-lazy).
_BOKEH_BASE_MB = 250  # Bokeh document + view widgets (production fit, not re-measured)
_FIXED_MB = 125  # analyzer + controller overhead independent of spike count
_LAZY_BYTES_PER_SPIKE = 32  # sorting/spike-vector structures + per-unit spike index cache
_NON_LAZY_BYTES_PER_SPIKE = 112  # sorting spike vector + aligned controller copy + index caches
_SPIKE_LEVEL_EXTENSIONS = {
    "spike_amplitudes": "amplitudes",
    "amplitude_scalings": "amplitude_scalings",
    "spike_locations": "spike_locations",
}
_SAFETY = 1.2


def _array_nbytes(group, name):
    if group is None or name not in group:
        return 0
    arr = group[name]
    if not hasattr(arr, "dtype") or arr.dtype.kind == "O":
        return 0
    return int(np.prod(arr.shape)) * arr.dtype.itemsize


def estimate_session_ram_bytes(zarr_root, lazy=False, skip_extensions=None, max_gb_non_lazy=10):
    """Estimate peak RAM cost of one GUI session from the analyzer zarr metadata.

    Only shapes/dtypes are read (from the consolidated metadata), so no array
    data is downloaded. The model mirrors what spikeinterface-gui keeps in memory:

    * both modes: templates (average + std), correlograms, ISI, similarity, and
      one dense PCA array built by ``get_all_pcs()`` (random spikes x all
      channels x components, shared with the ND scatter view) unless
      principal_components is skipped
    * lazy: a small per-spike cost plus the materialized spike depths; spike-level
      extensions and waveforms stay remote. Scatter-view caching briefly loads
      sample indices + one spike-level array (transient peak).
    * non-lazy: for a remote analyzer ``si.load`` loads extensions on first
      access, and the controller then loads every array of the extensions it
      uses (e.g. all template operators, full ``spike_locations``). The
      controller and views hold these same objects, not copies. Waveforms are
      never materialized.

    If the estimate is above the max_gb_non_lazy, it will be forced to be loaded
    in lazy mode.

    Returns ``(bytes, breakdown, force_lazy)`` where ``breakdown`` maps component -> MB.
    """
    force_lazy = False
    skip = set(skip_extensions or [])
    MB = 1024 * 1024
    ext_root = zarr_root["extensions"] if "extensions" in zarr_root else {}

    def ext(name):
        return ext_root[name] if name in ext_root and name not in skip else None

    num_spikes = zarr_root["sorting"]["spikes"]["sample_index"].shape[0]
    breakdown = {"bokeh_base": _BOKEH_BASE_MB, "fixed": _FIXED_MB}

    templates = ext_root["templates"] if "templates" in ext_root else None
    breakdown["templates"] = (_array_nbytes(templates, "average") + _array_nbytes(templates, "std")) / MB
    ccg = ext("correlograms")
    breakdown["correlograms"] = (_array_nbytes(ccg, "ccgs") + _array_nbytes(ccg, "bins")) / MB
    isi = ext("isi_histograms")
    breakdown["isi_histograms"] = (_array_nbytes(isi, "isi_histograms") + _array_nbytes(isi, "bins")) / MB
    breakdown["similarity"] = _array_nbytes(ext("template_similarity"), "similarity") / MB

    pca = ext("principal_components")
    if pca is not None and "pca_projection" in pca:
        proj = pca["pca_projection"]
        num_channels = zarr_root["sparsity_mask"].shape[1] if "sparsity_mask" in zarr_root else proj.shape[2]
        breakdown["pca_dense"] = proj.shape[0] * proj.shape[1] * num_channels * proj.dtype.itemsize / MB

    locations = ext("spike_locations")
    if lazy:
        spikes_mb = num_spikes * _LAZY_BYTES_PER_SPIKE / MB
        if locations is not None and "spike_locations" in locations:
            spikes_mb += num_spikes * locations["spike_locations"].dtype["y"].itemsize / MB
        breakdown["spikes"] = spikes_mb
        scatter_itemsizes = [
            ext_root[e][a].dtype.itemsize
            for e, a in _SPIKE_LEVEL_EXTENSIONS.items()
            if e != "spike_locations" and ext(e) is not None and a in ext_root[e]
        ]
        transient_scatter = num_spikes * (8 + max(scatter_itemsizes, default=0)) / MB
        transient_pca = _array_nbytes(pca, "pca_projection") / MB
        breakdown["transient_peak"] = max(transient_scatter, transient_pca)
    else:
        breakdown["spikes"] = num_spikes * _NON_LAZY_BYTES_PER_SPIKE / MB
        loaded = 0
        for ext_name in ext_root.keys():
            if ext_name == "waveforms" or ext_name in skip:
                continue
            group = ext_root[ext_name]
            loaded += sum(_array_nbytes(group, k) for k in group.keys())
        # templates / correlograms / isi / similarity are the same objects as the loaded extensions
        breakdown["loaded_extensions"] = (
            loaded / MB
            - breakdown["templates"]
            - breakdown["correlograms"]
            - breakdown["isi_histograms"]
            - breakdown["similarity"]
        )

    total_mb = sum(breakdown.values()) * _SAFETY
    breakdown = {k: round(v, 1) for k, v in breakdown.items()}
    if total_mb > max_gb_non_lazy * 1024:
        force_lazy = True
    return int(total_mb * MB), breakdown, force_lazy


def can_admit_new_session(current_count=None, used_pct=None, estimate_pct=None):
    """Return True if this task should accept one more session right now.

    Predicts post-admit RAM as
    ``current_used + pending_load_pct + estimate_pct`` and rejects if it
    would exceed ``SAFE_MAX_RAM_PCT`` or if the hard count cap is already
    reached. The ``pending_load_pct`` term covers sessions that were
    admitted in the last :data:`_PENDING_LOAD_TTL` seconds but haven't
    finished loading their data yet — without it, three concurrent
    admissions all see the same low ``used_pct`` and individually pass,
    only to OOM when their loads complete.

    ``estimate_pct`` is the per-session percent of container memory; if
    ``None``, falls back to the static :func:`get_per_session_estimate_pct`.
    Callers should pass a dynamic value derived from
    :func:`estimate_session_ram_bytes` when possible.
    """
    if current_count is None:
        current_count = len(list_gui_sessions())
    if current_count >= get_hard_cap_sessions():
        return False
    if used_pct is None:
        used_pct = get_container_used_memory() / get_container_total_memory() * 100
    if estimate_pct is None:
        estimate_pct = get_per_session_estimate_pct()
    projected = used_pct + get_pending_load_pct() + estimate_pct
    return projected < get_safe_max_ram_pct()


# --- Rejection flag (lets /health react to *actual* admission failures) ---
#
# ``EphysGuiView.__init__`` rejects an incoming session when the
# count-cap or RAM ceiling would be crossed. ``/health`` doesn't know
# about that on its own — it would otherwise see "task at 30% RAM, 1
# session, plenty of headroom for a 5 GB session, healthy" while in
# reality the GUI just turned a 500-unit session away.
#
# Fix: the GUI sets a rejection timestamp here. ``/health`` reports the
# task as full (and schedules inflate → ECS scale-up) when a recent
# rejection has occurred, regardless of the static admission heuristic.
# Decays automatically so a one-off rejection doesn't pin the task as
# "always full" forever.
_LAST_REJECTION_TS = 0.0
_REJECTION_TTL = 60.0  # seconds — covers ~2 ALB /health polls


def record_session_rejection():
    """Mark that the GUI just turned away an incoming session.

    Called from ``EphysGuiView.__init__`` whenever admission rejects, for
    any reason (count cap or RAM headroom). ``/health`` will report the
    task as full for the next :data:`_REJECTION_TTL` seconds — long
    enough to ensure ECS receives the scale-up signal via the inflate
    code path on the next health-check tick.
    """
    global _LAST_REJECTION_TS
    _LAST_REJECTION_TS = _time.monotonic()


def recent_session_rejection():
    """Return True if a rejection happened within :data:`_REJECTION_TTL`.

    Used by ``/health`` to fire the inflate / scale-up signal only when
    there has been concrete evidence of admission pressure — instead of
    pre-emptively scaling on a hypothetical worst-case session estimate.
    """
    if _LAST_REJECTION_TS == 0.0:
        return False
    return (_time.monotonic() - _LAST_REJECTION_TS) < _REJECTION_TTL


# --- Pending-load reservation (admission considers in-flight session loads) ---
#
# cgroup `memory.current` only reflects allocated RAM, not RAM that an
# already-admitted session is *about* to allocate during its zarr/numpy
# load. Three sessions admitted within 10 s of each other can each see
# the same "current" RAM and individually pass the admission check —
# only to OOM the task when all three finish loading.
#
# Fix: when admission succeeds, register the session's estimated RAM
# percent here. Subsequent admission checks add the sum of pending
# estimates to current RAM before deciding. Entries clear when the
# session ends (via ``EphysGuiView.cleanup``) or after the TTL expires
# (a safety net for sessions that crash before cleanup runs).
_PENDING_LOADS = {}  # session_id -> (estimate_pct, timestamp)
_PENDING_LOAD_TTL = 60.0  # seconds — covers typical heavy-session load time


def record_pending_load(session_id, estimate_pct):
    """Register that ``session_id`` will consume ~``estimate_pct``% RAM.

    Called from ``EphysGuiView.__init__`` right after the admission check
    succeeds. Replaces any existing entry for the same session_id.
    """
    if not session_id or estimate_pct is None or estimate_pct <= 0:
        return
    _PENDING_LOADS[session_id] = (float(estimate_pct), _time.monotonic())


def clear_pending_load(session_id):
    """Remove the pending entry for ``session_id`` (called on cleanup)."""
    if session_id:
        _PENDING_LOADS.pop(session_id, None)


def get_pending_load_pct():
    """Return the sum of pending session estimates, expiring stale entries.

    Used by admission to project post-admit RAM as
    ``current_used_pct + pending_load_pct + new_session_estimate_pct``.
    Stale pending entries (older than :data:`_PENDING_LOAD_TTL`) are
    pruned in-place — they presumably finished loading and their RAM is
    now reflected in ``memory.current`` anyway.
    """
    now = _time.monotonic()
    expired = [sid for sid, (_, ts) in _PENDING_LOADS.items() if now - ts > _PENDING_LOAD_TTL]
    for sid in expired:
        del _PENDING_LOADS[sid]
    return sum(pct for pct, _ in _PENDING_LOADS.values())


# --- Admission cooldown (soft sequencing of near-simultaneous arrivals) ---
#
# Even with the pending-load registry, two sessions arriving within
# ~1-2 s of each other can each pass admission before the *other's*
# pending entry has been recorded. That's because each goes through
# its own (~1-3 s) S3 metadata fetch concurrently, and the order of
# (can_admit_new_session read) vs (record_pending_load write) is racy
# across the two threads.
#
# Fix: serialize admissions with a short cooldown. After a successful
# admission, the next arrival waits until the cooldown expires —
# giving the prior session's record_pending_load() time to land. The
# cooldown rejection is "soft": it does NOT call
# :func:`record_session_rejection` (no /health inflate trigger),
# because this isn't a real capacity rejection — just timing.
_LAST_ADMISSION_TS = 0.0


def get_admission_cooldown_s():
    """Seconds to wait between successive admissions. Env-overridable."""
    return float(os.environ.get("ADMISSION_COOLDOWN_S", "10.0"))


def record_admission():
    """Mark that an admission just succeeded; starts the cooldown clock."""
    global _LAST_ADMISSION_TS
    _LAST_ADMISSION_TS = _time.monotonic()


def admission_cooldown_remaining():
    """Return seconds remaining in the admission cooldown (0.0 if expired).

    Callers in admission paths should soft-reject the session if this
    returns > 0 — without signalling a /health rejection.
    """
    if _LAST_ADMISSION_TS == 0.0:
        return 0.0
    elapsed = _time.monotonic() - _LAST_ADMISSION_TS
    cooldown = get_admission_cooldown_s()
    if elapsed >= cooldown:
        return 0.0
    return cooldown - elapsed


def get_max_number_of_gui_sessions():
    """Backward-compatible alias for :func:`get_hard_cap_sessions`.

    Kept so existing imports and the ``--max-sessions`` CLI flag continue
    to work. New code should prefer :func:`can_admit_new_session`, which
    accounts for actual RAM headroom rather than a static count.
    """
    return get_hard_cap_sessions()


class MultiSessionTee(io.TextIOBase):
    def __init__(self, original):
        self.original = original

    def write(self, data):
        self.original.write(data)

        # Write to session log file (from curdoc)
        path = _get_current_log_path()
        if path is not None and path.exists():
            try:
                with open(path, "a") as f:
                    f.write(data)
            except Exception:
                pass

        # Optional local sink (e.g., GUI init panel)
        sink = _local_sink.get()
        if sink is not None:
            try:
                sink.value = sink.value + data
            except Exception:
                pass

        return len(data)

    def flush(self):
        self.original.flush()


class local_log_context:
    def __init__(self, widget):
        self.widget = widget
        self._token = None

    def __enter__(self):
        self._token = _local_sink.set(self.widget)
        return self

    def __exit__(self, exc_type, exc, tb):
        if self._token is not None:
            _local_sink.reset(self._token)


def setup_logging():
    global _log_setup
    if _log_setup:
        return
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    sys.stdout = MultiSessionTee(sys.stdout)
    sys.stderr = MultiSessionTee(sys.stderr)
    _log_setup = True
