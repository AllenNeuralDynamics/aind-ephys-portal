import asyncio
import gc
import os
import shutil
import threading
import time as _time
import tracemalloc
from argparse import ArgumentParser
from collections import Counter

import numpy as np
import psutil
import panel as pn
from tornado.web import RequestHandler

# tracemalloc is OFF by default. Recording a per-allocation Python traceback
# adds non-trivial CPU overhead per allocation; on a Panel + spikeinterface
# + zarr workload that slowed Tornado enough for ECS health checks to time
# out, producing exit-137 restart loops. Enable only on diagnostic deploys:
#   TRACEMALLOC_ENABLED=1  (and optionally TRACEMALLOC_DEPTH, default 4)
_TRACEMALLOC_ENABLED = os.environ.get("TRACEMALLOC_ENABLED", "0").lower() in ("1", "true", "yes")
_tracemalloc_baseline = None
if _TRACEMALLOC_ENABLED:
    _tm_depth = int(os.environ.get("TRACEMALLOC_DEPTH", "4"))
    tracemalloc.start(_tm_depth)
    _tracemalloc_baseline = tracemalloc.take_snapshot()
    print(f"tracemalloc ENABLED with frame depth {_tm_depth}")
else:
    print("tracemalloc DISABLED (set TRACEMALLOC_ENABLED=1 to enable)")

# 1. Run setup (replaces --setup flag)
from aind_ephys_portal.setup import *  # noqa: F401,F403,E402
from aind_ephys_portal.session_logging import (  # noqa: E402
    list_gui_sessions,
    get_max_number_of_gui_sessions,
    can_admit_new_session,
    get_hard_cap_sessions,
    get_health_estimate_pct,
    get_container_total_memory,
    get_container_used_memory,
    get_ecs_task_id,
    LOG_DIR,
)  # noqa: F401
from aind_ephys_portal.ecs_protection import is_protected, get_protection_status  # noqa: E402

TARGET_MEMORY_TRIGGER_PERCENT = 70
TARGET_CLEAR_TMP_ARR_SECONDS = 180
TARGET_INFLATE_DELAY_SECONDS = 90

# Recycle signal: when a task is sitting idle (0 GUI sessions) but its RAM
# stays above this percent, /health returns 503 so the ALB deregisters it
# and the ECS service scheduler replaces it. Warm baseline is ~10%, so 30%
# tolerates ~20 points of accumulated residue before recycling — enough
# margin for transient post-cleanup glibc fragmentation, tight enough to
# catch the per-session drip before it compounds into a poisoned task.
# Only triggers with 0 sessions, so user sessions are never cut.
RECYCLE_RAM_PERCENT_WHEN_IDLE = int(os.environ.get("RECYCLE_RAM_PERCENT_WHEN_IDLE", "30"))


if LOG_DIR.is_dir():
    print(f"Cleaning up old log files in {LOG_DIR}...")
    shutil.rmtree(LOG_DIR)


_tmp_array_triggered = False
_tmp_arr = None
_tmp_arr_timer = None
_inflate_delay_timer = None


def _clear_tmp_arr():
    global _tmp_arr, _tmp_arr_timer
    print("Clearing temporary array to free up memory...")
    _tmp_arr = None
    _tmp_arr_timer = None
    print(f"tmp_arr cleared after {TARGET_CLEAR_TMP_ARR_SECONDS}s")


def _inflate_memory():
    global _tmp_arr, _tmp_arr_timer, _inflate_delay_timer
    _inflate_delay_timer = None
    total_memory = get_container_total_memory()
    used_memory = get_container_used_memory()
    target_memory = total_memory * TARGET_MEMORY_TRIGGER_PERCENT / 100
    array_size = int(
        (target_memory - used_memory) / 8
    )  # assuming float64 (8 bytes)
    if array_size > 0:
        print(
            f"Inflating memory with array of size {array_size} to trigger ECS scaling"
        )
        _tmp_arr = np.ones(array_size, dtype=np.float64)
        _tmp_arr_timer = threading.Timer(
            TARGET_CLEAR_TMP_ARR_SECONDS, _clear_tmp_arr
        )
        _tmp_arr_timer.daemon = True
        _tmp_arr_timer.start()


# 2. Health Check & Index Redirect
class HealthHandler(RequestHandler):
    def get(self):
        global _tmp_arr, _tmp_arr_timer, _tmp_array_triggered, _inflate_delay_timer
        total_memory = get_container_total_memory()
        used_memory = get_container_used_memory()
        mem_percent = used_memory / total_memory * 100
        # count number of GUI app sessions
        gui_sessions = list_gui_sessions()
        num_sessions = len(gui_sessions)
        task_id = get_ecs_task_id()
        hard_cap = get_hard_cap_sessions()

        # Idle-but-bloated → ask ALB to deregister so ECS replaces us.
        # GUI-level enforcement protects against admitting too many sessions,
        # but only the load balancer can take a leaky task out of rotation.
        protected = is_protected()
        prot_tag = " (protected)" if protected else ""

        if num_sessions == 0 and mem_percent > RECYCLE_RAM_PERCENT_WHEN_IDLE:
            self.set_status(503)
            self.write(
                f"Unhealthy (recycle): Memory at {mem_percent:.1f}% with 0 sessions - Task ID: {task_id}"
            )
            return

        # "Operationally full" = at least one session AND can't fit another
        # without crossing the safe RAM ceiling or hitting the hard count cap.
        # We pass `get_health_estimate_pct()` so the predicate knows how large
        # incoming sessions tend to be on this task — without it, /health
        # would use the static fallback (35%) and miss the case where the
        # GUI is rejecting heavy sessions that /health thinks would fit.
        full = num_sessions > 0 and not can_admit_new_session(
            current_count=num_sessions,
            used_pct=mem_percent,
            estimate_pct=get_health_estimate_pct(),
        )

        if full:
            self.set_status(200)
            # inflate RAM once per "full" event so ECS spawns a new task;
            # wait TARGET_INFLATE_DELAY_SECONDS first so loading sessions
            # have time to finish.
            if _tmp_arr is None and _inflate_delay_timer is None and not _tmp_array_triggered:
                _tmp_array_triggered = True
                print(
                    f"Task is full ({num_sessions} sessions, {mem_percent:.1f}% RAM); "
                    f"will inflate memory in {TARGET_INFLATE_DELAY_SECONDS}s"
                )
                _inflate_delay_timer = threading.Timer(
                    TARGET_INFLATE_DELAY_SECONDS, _inflate_memory
                )
                _inflate_delay_timer.daemon = True
                _inflate_delay_timer.start()
            busy_msg = "(FULL)"
            if _tmp_arr is not None:
                busy_msg += " (inflating memory)"
            elif _inflate_delay_timer is not None:
                busy_msg += " (waiting to inflate memory)"
            elif _tmp_array_triggered:
                busy_msg += " (inflated memory released)"
            self.write(
                f"Busy {busy_msg}{prot_tag}:\nMemory at {mem_percent:.1f}% - Num sessions: {num_sessions} "
                f"(hard cap {hard_cap}) Task ID: {task_id}"
            )
        else:
            _tmp_array_triggered = False
            if _inflate_delay_timer is not None:
                _inflate_delay_timer.cancel()
                _inflate_delay_timer = None
            self.set_status(200)
            self.write(
                f"Healthy{prot_tag}:\nMemory at {mem_percent:.1f}% - Num sessions: {num_sessions} "
                f"(hard cap {hard_cap}) Task ID: {task_id}"
            )


class ProtectionStatusHandler(RequestHandler):
    """GET /debug/protection — show current ECS task scale-in protection status."""

    def get(self):
        import json as _json

        status = get_protection_status()
        self.set_header("Content-Type", "application/json; charset=utf-8")
        self.write(_json.dumps(status, indent=2))


class IndexRedirectHandler(RequestHandler):
    def get(self):
        self.redirect("/ephys_portal_app")


# /debug/memory does heavy work (gc.collect + walking gc.get_objects, which
# can iterate millions of objects). Doing that on the Tornado event loop
# thread blocks /health for long enough to trip ECS health checks → task
# gets replaced. So we (1) run the heavy work in an executor thread,
# (2) allow only one in-flight build via a lock, and (3) cache the result
# for a short TTL so polling clients don't repeatedly trigger the work.
_DEBUG_MEM_LOCK = asyncio.Lock()
_DEBUG_MEM_CACHE = {"ts": 0.0, "body": ""}
_DEBUG_MEM_CACHE_TTL = 30.0  # seconds


def _build_debug_memory_payload():
    """Heavy synchronous work — must be called from an executor thread."""
    task_id = get_ecs_task_id()
    total_memory = get_container_total_memory()
    used_memory = get_container_used_memory()
    mem_percent = used_memory / total_memory * 100
    gui_sessions = list_gui_sessions()

    # One gc.collect() is enough — two was overkill and adds latency.
    gc.collect()

    # Single pass over gc.get_objects(): count types AND sum numpy bytes
    # in one walk. Halves the time vs the previous two-pass version.
    type_counts = Counter()
    np_bytes = 0
    np_count = 0
    for obj in gc.get_objects():
        type_counts[type(obj).__name__] += 1
        if isinstance(obj, np.ndarray):
            np_bytes += obj.nbytes
            np_count += 1
    top_types = type_counts.most_common(30)

    # fsspec/s3fs cache state
    fsspec_info = []
    try:
        from fsspec import AbstractFileSystem

        fsspec_info.append(
            f"fsspec AbstractFileSystem._cache size: {len(AbstractFileSystem._cache)}"
        )
        for key, fs in list(AbstractFileSystem._cache.items())[:10]:
            fsspec_info.append(f"  - {type(fs).__name__}: protocol={getattr(fs, 'protocol', '?')}")
    except Exception as e:
        fsspec_info.append(f"fsspec inspection failed: {e}")

    # tracemalloc top allocators since the recorded baseline. Use is_tracing()
    # so runtime POST /debug/tracemalloc/{start,stop} toggles are reflected
    # automatically — no need to read a separate module-level flag.
    tm_lines = []
    if not tracemalloc.is_tracing():
        tm_lines.append("tracemalloc disabled (POST /debug/tracemalloc/start to enable)")
    elif _tracemalloc_baseline is None:
        tm_lines.append("tracemalloc tracing, but no baseline snapshot yet")
    else:
        try:
            current = tracemalloc.take_snapshot()
            stats = current.compare_to(_tracemalloc_baseline, "lineno")[:25]
            for stat in stats:
                tm_lines.append(
                    f"  +{stat.size_diff/1024/1024:7.2f} MiB ({stat.count_diff:+d} blocks)  {stat.traceback[0]}"
                )
        except Exception as e:
            tm_lines.append(f"tracemalloc error: {e}")

    out = [
        f"=== Task {task_id} ===",
        f"Memory: {mem_percent:.1f}%  ({used_memory/1024**3:.2f} / {total_memory/1024**3:.2f} GB)",
        f"GUI sessions: {len(gui_sessions)}",
        "",
        "--- Top object types by count ---",
    ]
    for name, count in top_types:
        out.append(f"  {count:>10d}  {name}")
    out.extend(["", "--- Buffer bytes ---"])
    mib = np_bytes / 1024 / 1024
    out.append(f"  numpy.ndarray: {np_count} objects, {mib:.1f} MiB")
    out.extend(["", "--- fsspec ---"])
    out.extend(fsspec_info)
    out.extend(["", "--- tracemalloc (top 25 since boot) ---"])
    out.extend(tm_lines)
    return "\n".join(out)


class DebugMemoryHandler(RequestHandler):
    """Live introspection for diagnosing memory retention on a bloated task.

    Returns top object counts (via gc.get_objects), top allocation sites
    (tracemalloc snapshot diff vs. boot baseline), and fsspec/s3fs instance
    cache sizes. Gated by DEBUG_MEMORY_TOKEN env var. Heavy work runs in a
    thread executor with a 1-in-flight lock and a 30s result cache so the
    Tornado event loop stays free to answer /health.
    """

    async def get(self):
        token = os.environ.get("DEBUG_MEMORY_TOKEN")
        if token and self.request.headers.get("X-Debug-Token") != token:
            self.set_status(401)
            self.write("Unauthorized: missing or wrong X-Debug-Token header")
            return

        # Serve cached result if fresh.
        now = _time.monotonic()
        if _DEBUG_MEM_CACHE["body"] and now - _DEBUG_MEM_CACHE["ts"] < _DEBUG_MEM_CACHE_TTL:
            self.set_header("Content-Type", "text/plain; charset=utf-8")
            self.set_header("X-Debug-Cache", "hit")
            age = now - _DEBUG_MEM_CACHE["ts"]
            self.write(f"[cached snapshot, age {age:.1f}s — TTL {_DEBUG_MEM_CACHE_TTL:.0f}s]\n\n")
            self.write(_DEBUG_MEM_CACHE["body"])
            return

        # Reject pile-ups while a build is in flight. Caller can retry.
        if _DEBUG_MEM_LOCK.locked():
            self.set_status(429)
            self.set_header("Retry-After", "5")
            self.write("Another /debug/memory build is in flight; retry in a few seconds.")
            return

        async with _DEBUG_MEM_LOCK:
            # Re-check the cache: another request may have populated it
            # while we were waiting on the lock.
            now = _time.monotonic()
            if _DEBUG_MEM_CACHE["body"] and now - _DEBUG_MEM_CACHE["ts"] < _DEBUG_MEM_CACHE_TTL:
                body = _DEBUG_MEM_CACHE["body"]
            else:
                loop = asyncio.get_event_loop()
                body = await loop.run_in_executor(None, _build_debug_memory_payload)
                _DEBUG_MEM_CACHE["ts"] = _time.monotonic()
                _DEBUG_MEM_CACHE["body"] = body

        self.set_header("Content-Type", "text/plain; charset=utf-8")
        self.set_header("X-Debug-Cache", "miss")
        self.write(body)


def _check_debug_token(handler):
    """Returns True if request is authorized, otherwise writes 401 and returns False."""
    token = os.environ.get("DEBUG_MEMORY_TOKEN")
    if token and handler.request.headers.get("X-Debug-Token") != token:
        handler.set_status(401)
        handler.write("Unauthorized: missing or wrong X-Debug-Token header")
        return False
    return True


class TracemallocStartHandler(RequestHandler):
    """POST /debug/tracemalloc/start?depth=4 — turn tracemalloc on at runtime.

    Captures a fresh baseline snapshot so subsequent /debug/memory shows
    allocations made AFTER this point. Only affects the task this request
    lands on (each ECS task is its own process). Token-gated.
    """

    def post(self):
        if not _check_debug_token(self):
            return
        global _tracemalloc_baseline
        try:
            depth = int(self.get_argument("depth", "4"))
        except ValueError:
            self.set_status(400)
            self.write("depth must be an integer")
            return
        if depth < 1 or depth > 25:
            self.set_status(400)
            self.write("depth must be between 1 and 25")
            return

        task_id = get_ecs_task_id()
        if tracemalloc.is_tracing():
            # Already running — refresh the baseline so the next /debug/memory
            # diffs against "now" instead of an old snapshot.
            _tracemalloc_baseline = tracemalloc.take_snapshot()
            _DEBUG_MEM_CACHE["body"] = ""  # invalidate stale cached output
            self.write(
                f"tracemalloc already tracing on task {task_id}. "
                f"Baseline refreshed (depth unchanged).\n"
            )
            return

        tracemalloc.start(depth)
        _tracemalloc_baseline = tracemalloc.take_snapshot()
        _DEBUG_MEM_CACHE["body"] = ""
        self.write(f"tracemalloc STARTED on task {task_id} with depth {depth}\n")


class TracemallocStopHandler(RequestHandler):
    """POST /debug/tracemalloc/stop — turn tracemalloc off at runtime.

    Frees the bookkeeping memory tracemalloc accumulates. Only affects the
    task this request lands on. Token-gated.
    """

    def post(self):
        if not _check_debug_token(self):
            return
        global _tracemalloc_baseline
        task_id = get_ecs_task_id()
        if not tracemalloc.is_tracing():
            self.write(f"tracemalloc was already stopped on task {task_id}\n")
            return
        tracemalloc.stop()
        _tracemalloc_baseline = None
        _DEBUG_MEM_CACHE["body"] = ""
        self.write(f"tracemalloc STOPPED on task {task_id}\n")


# 3. App file paths — Panel will exec these per-session with a proper context
APP_DIR = "src/aind_ephys_portal"
apps = {
    "ephys_portal_app": os.path.join(APP_DIR, "ephys_portal_app.py"),
    "ephys_gui_app": os.path.join(APP_DIR, "ephys_gui_app.py"),
    "ephys_launcher_app": os.path.join(APP_DIR, "ephys_launcher_app.py"),
    "ephys_monitor_app": os.path.join(APP_DIR, "ephys_monitor_app.py"),
}

# 4. Parse ALLOW_WEBSOCKET_ORIGIN from env
allow_ws = os.environ.get("ALLOW_WEBSOCKET_ORIGIN", "*").split(",")

parser = ArgumentParser(description="Ephys Portal Server")
parser.add_argument("--port", type=int, default=8000, help="Port to run the server on")
parser.add_argument(
    "--address", type=str, default="localhost", help="Address to run the server on"
)
parser.add_argument(
    "--test",
    action="store_true",
    help="Run in test mode (connects to test API gateway)",
)
parser.add_argument(
    "--max-sessions",
    type=int,
    default=None,
    help="Maximum number of GUI sessions per task",
)


if __name__ == "__main__":
    args = parser.parse_args()
    port = args.port
    address = args.address
    max_sessions = args.max_sessions
    test_mode = args.test

    # Set number of threads for Panel's thread pool to handle multiple sessions in parallel
    pn.config.nthreads = 8

    if max_sessions is not None:
        print(f"Overriding max GUI sessions per task to {max_sessions}")
        os.environ["MAX_GUI_SESSIONS_PER_TASK"] = str(max_sessions)

    if test_mode:
        print("Running in TEST MODE: connecting to test API gateway")
        os.environ["TEST_ENV"] = "1"

    print(f"Ephys Portal is running on http://{address}:{port}")
    for app in apps:
        print(f" - {app}: http://{address}:{port}/{app}")
    print(f" - Health check: http://{address}:{port}/health")
    pn.serve(
        apps,
        address=address,
        port=port,
        allow_websocket_origin=allow_ws,
        static_dirs={"images": os.path.join(APP_DIR, "images")},
        extra_patterns=[
            (r"/health", HealthHandler),
            (r"/debug/memory", DebugMemoryHandler),
            (r"/debug/tracemalloc/start", TracemallocStartHandler),
            (r"/debug/tracemalloc/stop", TracemallocStopHandler),
            (r"/debug/protection", ProtectionStatusHandler),
            (r"/", IndexRedirectHandler),
        ],
        check_unused_sessions=2000,
        unused_session_lifetime=5000,
        show=False,
    )
