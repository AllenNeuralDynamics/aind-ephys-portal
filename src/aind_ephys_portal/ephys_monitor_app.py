import psutil
import panel as pn

from aind_ephys_portal.panel.logging import list_sessions, remove_session

pn.extension()


# --- Memory info ---
def get_mem_info():
    mem = psutil.virtual_memory()
    used_gb = mem.used / (1024 ** 3)
    total_gb = mem.total / (1024 ** 3)
    percent = mem.percent
    return used_gb, total_gb, percent


# --- CPU info ---
def get_cpu_percent():
    return psutil.cpu_percent(interval=None)


# --- Progress indicators ---
used_gb, total_gb, percent = get_mem_info()

ram_usage_label = pn.pane.Markdown(f"🧠 RAM Usage", styles={"font-weight": "bold"})
ram_monitor = pn.indicators.Progress(
    name="RAM",
    value=int(percent),
    max=100,
    sizing_mode="stretch_width",
    bar_color="success" if percent < 70 else ("warning" if percent < 90 else "danger"),
)

cpu_usage_label = pn.pane.Markdown(f"🖥️ CPU Usage", styles={"font-weight": "bold"})
cpu_monitor = pn.indicators.Progress(
    name="CPU",
    value=int(get_cpu_percent()),
    max=100,
    sizing_mode="stretch_width",
    bar_color="success",
)


def update_monitors():
    used_gb, total_gb, percent = get_mem_info()
    ram_monitor.value = int(percent)
    ram_monitor.bar_color = "success" if percent < 70 else ("warning" if percent < 90 else "danger")
    ram_usage_label.object = f"🧠 RAM Usage ({used_gb:.1f} / {total_gb:.1f} GB)"

    cpu = get_cpu_percent()
    cpu_monitor.value = int(cpu)
    cpu_monitor.bar_color = "success" if cpu < 70 else ("warning" if cpu < 90 else "danger")
    cpu_usage_label.object = f"🖥️ CPU Usage ({cpu:.0f}%)"


pn.state.add_periodic_callback(update_monitors, period=2000)


# --- Active sessions summary ---
sessions_summary = pn.Row(sizing_mode="stretch_width")


def update_sessions_summary(sessions):
    """Update the active sessions summary row with per-route counts."""
    if not sessions:
        sessions_summary[:] = [pn.pane.Markdown("No active sessions.")]
        return

    # Count sessions per route
    route_counts = {}
    for (route, _) in sessions.keys():
        route_counts[route] = route_counts.get(route, 0) + 1

    badges = []
    for route, count in sorted(route_counts.items()):
        badge = pn.pane.Markdown(
            f"**{route}**: {count}",
            styles={
                "background": "#e8f4fd",
                "border-radius": "8px",
                "padding": "6px 14px",
                "margin": "4px",
                "border": "1px solid #2A7DE1",
            },
        )
        badges.append(badge)

    total = pn.pane.Markdown(
        f"**Total: {sum(route_counts.values())}**",
        styles={
            "background": "#d4edda",
            "border-radius": "8px",
            "padding": "6px 14px",
            "margin": "4px",
            "border": "1px solid #1D8649",
        },
    )
    sessions_summary[:] = [total] + badges


# --- Log viewer ---
log_container = pn.Column(sizing_mode="stretch_both")
_log_panes = {}        # key → pn.pane.HTML  (the log content pane)
_log_contents = {}     # key → last content string  (skip no-op updates)
_tab_bodies = {}       # key → pn.Column  (the whole tab body)
_tabs_widget = None    # the single Tabs widget we keep alive
_prev_keys_order = []  # ordered list of keys to detect session changes

SKIP_ROUTES = ["ephys_monitor_app"]


def _make_clear_callback(route, session_id, path):
    def _clear(event):
        try:
            path.write_text("")
            key = (route, session_id)
            if key in _log_panes:
                _log_panes[key].object = _make_log_pre("")
                _log_contents[key] = ""
        except Exception as e:
            print(f"Error clearing log: {e}")
    return _clear


def _make_delete_callback(route, session_id):
    def _delete(event):
        try:
            remove_session(route=route, session_id=session_id)
            key = (route, session_id)
            _log_panes.pop(key, None)
            _log_contents.pop(key, None)
            _tab_bodies.pop(key, None)
            refresh_log_tabs()
        except Exception as e:
            print(f"Error deleting log: {e}")
    return _delete


def _make_log_pre(content):
    """Wrap log content in a scrollable <pre>.

    We do NOT use an inline <script> because Panel doesn't re-execute
    scripts when updating .object.  Instead we keep the user's current
    scroll position by *only* updating the text content of the <pre> via
    Panel, and never recreating the widget.

    Auto-scroll to bottom is achieved via an `afterUpdate` JS callback
    on the pane (see _make_log_pane).
    """
    import html as html_mod
    escaped = html_mod.escape(content)
    return (
        f'<pre class="log-pre" style="'
        f"white-space: pre-wrap;"
        f"word-wrap: break-word;"
        f"overflow-y: auto;"
        f"max-height: 500px;"
        f"min-height: 200px;"
        f"background: #f5f5f5;"
        f"padding: 8px;"
        f"font-size: 12px;"
        f"border: 1px solid #ccc;"
        f"border-radius: 4px;"
        f'">{escaped}</pre>'
    )


def _make_log_pane(content):
    """Create a log HTML pane with a JS callback that auto-scrolls."""
    pane = pn.pane.HTML(_make_log_pre(content), sizing_mode="stretch_both")
    # Whenever the HTML object changes, scroll the <pre> to the bottom.
    # Panel exposes a jscallback on 'object' which fires client-side
    # after the new HTML is rendered.
    try:
        pane.jscallback(
            object="""
            setTimeout(function() {
                var el = cb_obj.el;
                if (!el) return;
                var pre = el.querySelector('.log-pre');
                if (pre) { pre.scrollTop = pre.scrollHeight; }
            }, 50);
            """
        )
    except Exception:
        pass  # jscallback not available in all Panel versions
    return pane


def refresh_log_tabs():
    global _tabs_widget, _prev_keys_order

    all_sessions = list_sessions()
    update_sessions_summary(all_sessions)
    log_sessions = list_sessions(skip_routes=SKIP_ROUTES)

    if not log_sessions:
        _tabs_widget = None
        _prev_keys_order = []
        log_container[:] = [pn.pane.Markdown("No active sessions.", sizing_mode="stretch_both")]
        return

    current_keys = list(log_sessions.keys())
    structure_changed = (current_keys != _prev_keys_order)

    # --- Update content of each session (cheap: only touches .object) ---
    for key, path in log_sessions.items():
        route, session_id = key
        content = ""
        try:
            content = path.read_text()
        except Exception:
            content = "(could not read log)"

        if key not in _log_panes:
            # First time seeing this session
            _log_panes[key] = _make_log_pane(content)
            _log_contents[key] = content

            title = f"{route} | {str(session_id)[:8]}"
            clear_btn = pn.widgets.Button(name="🗑️ Clear", button_type="warning", width=100)
            clear_btn.on_click(_make_clear_callback(route, session_id, path))
            delete_btn = pn.widgets.Button(name="❌ Delete", button_type="danger", width=100)
            delete_btn.on_click(_make_delete_callback(route, session_id))

            _tab_bodies[key] = pn.Column(
                pn.Row(
                    pn.pane.Markdown(f"**{title}**"),
                    pn.Spacer(),
                    clear_btn,
                    delete_btn,
                ),
                _log_panes[key],
                sizing_mode="stretch_both",
            )
            structure_changed = True
        else:
            # Only update the HTML text if it actually changed
            if content != _log_contents.get(key):
                _log_panes[key].object = _make_log_pre(content)
                _log_contents[key] = content

    # --- Clean up stale sessions ---
    active_keys = set(current_keys)
    for key in list(_log_panes.keys()):
        if key not in active_keys:
            _log_panes.pop(key, None)
            _log_contents.pop(key, None)
            _tab_bodies.pop(key, None)
            structure_changed = True

    # --- Rebuild the Tabs widget only when sessions come/go ---
    if structure_changed or _tabs_widget is None:
        prev_active = 0
        if _tabs_widget is not None:
            prev_active = getattr(_tabs_widget, "active", 0)

        tabs = []
        for key in current_keys:
            route, session_id = key
            title = f"{route} | {str(session_id)[:8]}"
            tabs.append((title, _tab_bodies[key]))

        _tabs_widget = pn.Tabs(*tabs, sizing_mode="stretch_both")
        if tabs:
            _tabs_widget.active = min(prev_active, len(tabs) - 1)

        log_container[:] = [_tabs_widget]

    _prev_keys_order = current_keys


pn.state.add_periodic_callback(refresh_log_tabs, period=2000)
refresh_log_tabs()


# --- App layout ---
app = pn.Column(
    pn.pane.Markdown("## AIND Ephys Monitor"),
    pn.Row(ram_usage_label, ram_monitor),
    pn.Row(cpu_usage_label, cpu_monitor),
    pn.pane.Markdown("## Active Sessions"),
    sessions_summary,
    pn.pane.Markdown("## Session Logs"),
    log_container,
    sizing_mode="stretch_both",
)

app.servable(title="AIND Ephys Monitor")
