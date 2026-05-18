import panel as pn

from aind_ephys_portal.session_logging import add_session, remove_session, setup_logging
from aind_ephys_portal.session_logging import list_gui_sessions
from aind_ephys_portal.ecs_protection import protect_task, unprotect_task, is_protected

setup_logging()


def on_session_created(session_context):
    request = session_context.request

    # Extract route from the request URL
    route = "unknown"
    if hasattr(request, "uri"):
        parts = request.uri.strip("/").split("?")[0].split("/")
        route = parts[0] if parts and parts[0] else "unknown"
    elif hasattr(request, "path"):
        parts = request.path.strip("/").split("?")[0].split("/")
        route = parts[0] if parts and parts[0] else "unknown"

    # Skip warm-up / internal sessions
    if route in ("unknown", "", "ws"):
        return

    session_id = str(id(session_context))

    # Store on document so apps and destroy callback can find it
    doc = session_context._document
    doc._log_route = route
    doc._log_session_id = session_id

    add_session(route=route, session_id=session_id)
    print(f"[setup] Session created: {route}/{session_id}")

    # Protect task from scale-in while GUI sessions are active
    if route == "ephys_gui_app" and not is_protected():
        protect_task()


def on_session_destroyed(session_context):
    doc = session_context._document
    route = getattr(doc, "_log_route", None)
    session_id = getattr(doc, "_log_session_id", None)

    if route is None or session_id is None:
        return

    remove_session(route=route, session_id=session_id)
    print(f"[setup] Session destroyed: {route}/{session_id}")

    # Clear protection when the last GUI session ends
    if route == "ephys_gui_app" and len(list_gui_sessions()) == 0:
        unprotect_task()


pn.state.on_session_created(on_session_created)
pn.state.on_session_destroyed(on_session_destroyed)
