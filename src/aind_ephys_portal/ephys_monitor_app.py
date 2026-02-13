import panel as pn
import psutil

from aind_ephys_portal.panel.logging import list_buffers, remove_buffer, setup_logging

pn.extension()


# --- Memory info ---
def get_mem_info():
    mem = psutil.virtual_memory()
    total_gb = mem.total / 1e9
    used_gb = mem.used / 1e9
    return used_gb, total_gb, mem.percent


# --- Progress indicator ---
used_gb, total_gb, percent = get_mem_info()

ram_monitor = pn.widgets.indicators.Progress(
    name="Memory Usage",
    value=int(used_gb),
    max=int(total_gb),
    bar_color="success" if percent < 70 else "warning" if percent < 90 else "danger",
    width=400,
    height=30,
)

cpu_monitor = pn.widgets.indicators.Progress(
    name="CPU Usage",
    value=int(psutil.cpu_percent()),
    max=100,
    bar_color="success" if psutil.cpu_percent() < 70 else "warning" if psutil.cpu_percent() < 90 else "danger",
    width=400,
    height=30,
)


# --- Periodic update ---
def update_usage():
    used_gb, total_gb, percent = get_mem_info()
    ram_monitor.value = int(used_gb)
    ram_monitor.bar_color = "success" if percent < 70 else "warning" if percent < 90 else "danger"
    cpu_percent = psutil.cpu_percent()
    cpu_monitor.value = int(cpu_percent)
    cpu_monitor.bar_color = "success" if cpu_percent < 70 else "warning" if cpu_percent < 90 else "danger"

pn.state.add_periodic_callback(update_usage, period=2000)

ram_usage_label = pn.widgets.StaticText(value="🐏 RAM Usage", height=30)
cpu_usage_label = pn.widgets.StaticText(value="🖥️ CPU Usage", height=30)
active_user_count_label = pn.widgets.StaticText(value="🧑‍🔬 Active Users", height=30)
active_user_count = pn.widgets.StaticText(value="0", height=30)


def update_user_count():
    active_user_count.value = str(len(pn.state.active_sessions))


pn.state.add_periodic_callback(update_user_count, period=2000)

monitor = pn.Row(
    ram_usage_label,
    ram_monitor,
    cpu_usage_label,
    cpu_monitor,
    active_user_count_label, 
    active_user_count,
    sizing_mode="stretch_width"
)

setup_logging()

log = pn.Column(sizing_mode="stretch_both")

def _get_active_index():
    if len(log) == 0:
        return 0
    tabs_widget = log[0]
    return getattr(tabs_widget, "active", 0)

def refresh_tabs():
    buffers = list_buffers(
        skip_routes=["ephys_monitor_app", "ephys_launcher_app"],
    )
    prev_active = _get_active_index()
    if not buffers:
        log[:] = [pn.pane.Markdown("No logs yet.", sizing_mode="stretch_both")]
        return

    tabs = []
    for key, widget in buffers.items():
        route, session_id = key
        title = f"{route} | {str(session_id)[:8]}"

        close_btn = pn.widgets.Button(name="Close", button_type="danger", width=80)

        def _close(event, key=key):
            remove_buffer(key)
            refresh_tabs()

        close_btn.on_click(_close)

        tab_body = pn.Column(
            pn.Row(pn.pane.Markdown(f"**{title}**"), pn.Spacer(), close_btn),
            widget,
            sizing_mode="stretch_both",
        )
        tabs.append((title, tab_body))

    tabs_widget = pn.Tabs(*tabs, sizing_mode="stretch_both")
    if tabs:
        tabs_widget.active = min(prev_active, len(tabs) - 1)

    log[:] = [tabs_widget]


pn.state.add_periodic_callback(refresh_tabs, period=2000)
refresh_tabs()

app = pn.Column(monitor, log, sizing_mode="stretch_both")

app.servable(title="AIND Ephys Monitor")
