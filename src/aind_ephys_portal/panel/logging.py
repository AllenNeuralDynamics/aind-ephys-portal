import io
import os
import sys
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


def get_max_number_of_gui_sessions():
    # Estimate number of sessions per worker for health check.
    if "MAX_GUI_SESSIONS_PER_TASK" in os.environ:
        print(f"Using MAX_GUI_SESSIONS_PER_TASK from environment: {os.environ['MAX_GUI_SESSIONS_PER_TASK']}")
        MAX_SESSIONS_PER_WORKER = int(os.environ["MAX_GUI_SESSIONS_PER_TASK"])
    else:
        SESSION_AVG_RAM_USAGE_GB = 2
        TOTAL_RAM_GB = get_container_total_memory() / (1024**3)
        MAX_SESSIONS_PER_WORKER = int(np.floor(TOTAL_RAM_GB / SESSION_AVG_RAM_USAGE_GB))

    return MAX_SESSIONS_PER_WORKER


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
