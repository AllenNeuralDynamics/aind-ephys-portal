import io
import sys
import panel as pn
import contextvars

pn.extension()

_buffers = {}
_log_setup = False
_local_sink = contextvars.ContextVar("local_sink", default=None)


def _get_session_id():
    session_id = getattr(pn.state, "session_id", None)
    if session_id:
        return session_id
    doc = getattr(pn.state, "curdoc", None)
    if doc and getattr(doc, "session_context", None):
        return id(doc.session_context)
    return "no-session"


def _key(pathname=None, session_id=None):
    if pathname is None:
        location = getattr(pn.state, "location", None)
        pathname = location.pathname if location else "/"
    if session_id is None:
        session_id = _get_session_id()
    return (pathname, session_id)


def get_buffer(pathname=None, session_id=None):
    key = _key(pathname, session_id)
    if key not in _buffers:
        _buffers[key] = pn.widgets.TextAreaInput(value="", sizing_mode="stretch_both")
    return _buffers[key]


def list_buffers(skip_routes=None):
    if skip_routes is None:
        skip_routes = []
    buffer_list = list(_buffers.keys())
    buffers = {}
    for key in buffer_list:
        route, session_id = key
        if any(s in route for s in skip_routes):
            continue
        if isinstance(session_id, str) and session_id == "no-session":
            continue
        buffers[key] = _buffers[key]
    return buffers


def remove_buffer(key):
    return _buffers.pop(key, None)


def add_session(session_id, pathname=None):
    key = _key(pathname=pathname, session_id=session_id)
    if key not in _buffers:
        _buffers[key] = pn.widgets.TextAreaInput(value="", sizing_mode="stretch_both")
    return _buffers[key]


def clear_session(session_id):
    keys = [k for k in _buffers.keys() if k[1] == session_id]
    for k in keys:
        _buffers.pop(k, None)
    return len(keys)


class MultiSessionTee(io.TextIOBase):
    def __init__(self, original):
        self.original = original

    def write(self, data):
        self.original.write(data)

        # Global per-session buffer
        buf = get_buffer()
        buf.value = buf.value + data

        # Optional local sink (e.g., GUI init panel)
        sink = _local_sink.get()
        if sink is not None:
            sink.value = sink.value + data

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
    sys.stdout = MultiSessionTee(sys.stdout)
    sys.stderr = MultiSessionTee(sys.stderr)
    _log_setup = True