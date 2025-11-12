import panel as pn

active_sessions = set()


def on_session_created(session_context):
    session_id = id(session_context)
    active_sessions.add(session_id)
    print(f"[+] Session created: {session_id} | Active sessions: {len(active_sessions)}")


def on_session_destroyed(session_context):
    session_id = id(session_context)
    active_sessions.discard(session_id)
    print(f"[-] Session closed: {session_id} | Active sessions: {len(active_sessions)}")


pn.state.on_session_created(on_session_created)
pn.state.on_session_destroyed(on_session_destroyed)

# Expose the set globally so your main app can read it
pn.state.active_sessions = active_sessions
