import os

import psutil
import panel as pn
from tornado.web import RequestHandler

# 1. Run setup (replaces --setup flag)
from aind_ephys_portal.setup import *  # noqa: F401,F403

# 2. Health Check & Index Redirect
class HealthHandler(RequestHandler):
    def get(self):
        mem = psutil.virtual_memory()
        if mem.percent > 70:
            self.set_status(503)
            self.write(f"Busy: Memory at {mem.percent}%")
        else:
            self.set_status(200)
            self.write("Healthy")

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

# 5. Start the Server
pn.serve(
    apps,
    address="0.0.0.0",
    port=8000,
    allow_websocket_origin=allow_ws,
    static_dirs={"images": os.path.join(APP_DIR, "images")},
    extra_patterns=[(r"/health", HealthHandler), (r"/", IndexRedirectHandler)],
    check_unused_sessions=2000,
    unused_session_lifetime=5000,
    num_threads=8,
    show=False,
)