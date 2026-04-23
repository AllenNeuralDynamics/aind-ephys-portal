import os
import shutil
from argparse import ArgumentParser

import requests
import psutil
import panel as pn
from tornado.web import RequestHandler

# 1. Run setup (replaces --setup flag)
from aind_ephys_portal.setup import *  # noqa: F401,F403
from aind_ephys_portal.panel.logging import list_gui_sessions, get_max_number_of_gui_sessions, LOG_DIR  # noqa: F401


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

# 2. Health Check & Index Redirect
class HealthHandler(RequestHandler):
    def get(self):
        mem = psutil.virtual_memory()
        # count number of GUI app sessions
        gui_sessions = list_gui_sessions()
        task_id = get_ecs_task_id()
        if mem.percent > 70 or len(gui_sessions) > MAX_GUI_SESSIONS_PER_TASK:
            self.set_status(503)
            self.write(
                f"Busy:\nMemory at {mem.percent}% - Num sessions: {len(gui_sessions)} "
                f"(max {MAX_GUI_SESSIONS_PER_TASK}) Task ID: {task_id}"
            )
        else:
            self.set_status(200)
            self.write(
                f"Healthy:\nMemory at {mem.percent}% - Num sessions: {len(gui_sessions)} "
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