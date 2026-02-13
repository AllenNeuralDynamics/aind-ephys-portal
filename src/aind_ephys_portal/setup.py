import panel as pn
from aind_ephys_portal.panel.logging import add_session, clear_session, setup_logging

setup_logging()

active_sessions = set()


def on_session_created(session_context):
    session_id = id(session_context)
    active_sessions.add(session_id)

def on_session_destroyed(session_context):
    session_id = id(session_context)
    active_sessions.discard(session_id)
    clear_session(session_id)


pn.state.on_session_created(on_session_created)
pn.state.on_session_destroyed(on_session_destroyed)

# Expose the set globally so your main app can read it
pn.state.active_sessions = active_sessions
