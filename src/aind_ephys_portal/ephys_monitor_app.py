import psutil
import panel as pn

from aind_ephys_portal.panel.logging import list_sessions, remove_session

pn.extension()


# --- Memory info ---
def get_mem_info():
    mem = psutil.virtual_memory()
    used_gb = mem.used / (1024**3)
    total_gb = mem.total / (1024**3)
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
    for route, _ in sessions.keys():
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
_log_widgets = {}  # cache TextAreaInput widgets per (route, session_id)

SKIP_ROUTES = ["ephys_monitor_app"]


def _get_active_tab():
    if len(log_container) == 0:
        return 0
    widget = log_container[0]
    return getattr(widget, "active", 0)


def _make_clear_callback(route, session_id, path):
    def _clear(event):
        try:
            path.write_text("")
            key = (route, session_id)
            if key in _log_widgets:
                _log_widgets[key].value = ""
        except Exception as e:
            print(f"Error clearing log: {e}")

    return _clear


def _make_delete_callback(route, session_id):
    def _delete(event):
        try:
            remove_session(route=route, session_id=session_id)
            key = (route, session_id)
            if key in _log_widgets:
                del _log_widgets[key]
            refresh_log_tabs()
        except Exception as e:
            print(f"Error deleting log: {e}")

    return _delete


def refresh_log_tabs():
    all_sessions = list_sessions()
    update_sessions_summary(all_sessions)
    log_sessions = list_sessions(skip_routes=SKIP_ROUTES)

    if not log_sessions:
        log_container[:] = [pn.pane.Markdown("_No log sessions._")]
        return

    prev_active = _get_active_tab()

    tabs = []
    for (route, session_id), path in log_sessions.items():
        title = f"{route} | {str(session_id)[:8]}"

        # Read log content from file
        content = ""
        try:
            content = path.read_text()
        except Exception:
            content = "(could not read log)"

        # Compute height: ~16px per line, min 200, no max
        n_lines = max(content.count("\n") + 1, 10)
        height = max(200, n_lines * 16 + 20)

        # Reuse or create widget
        key = (route, session_id)
        if key not in _log_widgets:
            _log_widgets[key] = pn.widgets.TextAreaInput(
                value=content,
                disabled=True,
                sizing_mode="stretch_width",
                height=height,
                stylesheets=[":host textarea { font-size: 12px; font-family: monospace; }"],
            )
        else:
            _log_widgets[key].value = content
            _log_widgets[key].height = height

        # Action buttons
        clear_btn = pn.widgets.Button(name="🗑️ Clear", button_type="warning", width=100)
        clear_btn.on_click(_make_clear_callback(route, session_id, path))

        delete_btn = pn.widgets.Button(name="❌ Delete", button_type="danger", width=100)
        delete_btn.on_click(_make_delete_callback(route, session_id))

        tab_body = pn.Column(
            pn.Row(
                pn.pane.Markdown(f"**{title}**"),
                pn.Spacer(),
                clear_btn,
                delete_btn,
            ),
            _log_widgets[key],
            sizing_mode="stretch_both",
        )
        tabs.append((title, tab_body))

    # Clean up stale widgets
    active_keys = set(log_sessions.keys())
    for key in list(_log_widgets.keys()):
        if key not in active_keys:
            del _log_widgets[key]

    tabs_widget = pn.Tabs(*tabs, sizing_mode="stretch_both", dynamic=True)
    if tabs:
        tabs_widget.active = min(prev_active, len(tabs) - 1)

    log_container[:] = [tabs_widget]


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
