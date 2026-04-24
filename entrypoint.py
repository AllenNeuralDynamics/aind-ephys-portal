import os
import shutil
import threading
from argparse import ArgumentParser

import requests
import numpy as np
import psutil
import panel as pn
from tornado.web import RequestHandler

# 1. Run setup (replaces --setup flag)
from aind_ephys_portal.setup import *  # noqa: F401,F403
from aind_ephys_portal.panel.logging import list_gui_sessions, get_max_number_of_gui_sessions, get_container_total_memory, LOG_DIR  # noqa: F401


TARGET_MEMORY_TRIGGER_PERCENT = 70
TARGET_CLEAR_TMP_ARR_SECONDS = 180


if LOG_DIR.is_dir():
    print(f"Cleaning up old log files in {LOG_DIR}...")
    shutil.rmtree(LOG_DIR)


def get_ecs_task_id():
    metadata_uri = os.environ.get("ECS_CONTAINER_METADATA_URI_V4")
    if metadata_uri:
        # Request the metadata from the local ECS agent
        response = requests.get(f"{metadata_uri}/task")
        task_arn = response.json().get("TaskARN")
        # The Task ID is the last part of the ARN string
        return task_arn.split('/')[-1]
    return "local-dev"


MAX_GUI_SESSIONS_PER_TASK = get_max_number_of_gui_sessions()
print(f"Max GUI sessions per task: {MAX_GUI_SESSIONS_PER_TASK}")

_tmp_array_triggered = False
_tmp_arr = None
_tmp_arr_timer = None


def _clear_tmp_arr():
    global _tmp_arr, _tmp_arr_timer
    print("Clearing temporary array to free up memory...")
    _tmp_arr = None
    _tmp_arr_timer = None
    print(f"tmp_arr cleared after {TARGET_CLEAR_TMP_ARR_SECONDS}s")

# 2. Health Check & Index Redirect
class HealthHandler(RequestHandler):
    def get(self):
        global _tmp_arr, _tmp_arr_timer, _tmp_array_triggered
        mem = psutil.virtual_memory()
        container_total = get_container_total_memory()
        mem_percent = mem.used / container_total * 100
        # count number of GUI app sessions
        gui_sessions = list_gui_sessions()
        task_id = get_ecs_task_id()
        if mem_percent > TARGET_MEMORY_TRIGGER_PERCENT:
            self.set_status(200)
            self.write(
                f"Busy (RAM Usage):\nMemory at {mem_percent:.1f}% - Num sessions: {len(gui_sessions)} "
                f"(max {MAX_GUI_SESSIONS_PER_TASK}) Task ID: {task_id}"
            )
        elif len(gui_sessions) > MAX_GUI_SESSIONS_PER_TASK:
            self.set_status(200)
            busy_msg = "(MAX SESSIONS EXCEEDED)"
            if _tmp_arr is not None:
                busy_msg += " (inflating memory)"
            elif _tmp_array_triggered:
                busy_msg += " (inflated memory released)"
            self.write(
                f"Busy {busy_msg}:\nMemory at {mem_percent:.1f}% - Num sessions: {len(gui_sessions)} "
                f"(max {MAX_GUI_SESSIONS_PER_TASK}) Task ID: {task_id}"
            )
            # inflate RAM once per threshold-exceeded event so ECS spawns a new task
            if _tmp_arr is None and not _tmp_array_triggered:
                _tmp_array_triggered = True
                total_memory = get_container_total_memory()
                used_memory = psutil.virtual_memory().used
                target_memory = total_memory * TARGET_MEMORY_TRIGGER_PERCENT / 100
                array_size = int((target_memory - used_memory) / 8)  # assuming float64 (8 bytes)
                if array_size > 0:
                    print(f"Inflating memory with array of size {array_size} to trigger ECS scaling")
                    _tmp_arr = np.ones(array_size, dtype=np.float64)
                    _tmp_arr_timer = threading.Timer(TARGET_CLEAR_TMP_ARR_SECONDS, _clear_tmp_arr)
                    _tmp_arr_timer.daemon = True
                    _tmp_arr_timer.start()
        else:
            _tmp_array_triggered = False
            self.set_status(200)
            self.write(
                f"Healthy:\nMemory at {mem_percent:.1f}% - Num sessions: {len(gui_sessions)} "
                f"(max {MAX_GUI_SESSIONS_PER_TASK}) Task ID: {task_id}"
            )

class IndexRedirectHandler(RequestHandler):
    def get(self):
        self.redirect("/ephys_portal_app")

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
parser.add_argument("--address", type=str, default="localhost", help="Address to run the server on")
parser.add_argument("--test", action="store_true", help="Run in test mode (connects to test API gateway)")

if __name__ == "__main__":
    args = parser.parse_args()
    port = args.port
    address = args.address
    test_mode = args.test

    # Set number of threads for Panel's thread pool to handle multiple sessions in parallel
    pn.config.nthreads = 8

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
        extra_patterns=[(r"/health", HealthHandler), (r"/", IndexRedirectHandler)],
        check_unused_sessions=2000,
        unused_session_lifetime=5000,
        show=False,
    )