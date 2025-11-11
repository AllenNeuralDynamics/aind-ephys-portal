import panel as pn
import psutil

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


# --- Periodic update ---
def update_ram_usage():
    used_gb, total_gb, percent = get_mem_info()
    ram_monitor.value = int(used_gb)
    ram_monitor.bar_color = "success" if percent < 70 else "warning" if percent < 90 else "danger"


pn.state.add_periodic_callback(update_ram_usage, period=2000)

ram_usage_label = pn.widgets.StaticText(value="🐏 RAM Usage", height=30)
active_user_count_label = pn.widgets.StaticText(value="🧑‍🔬 Active Users", height=30)
active_user_count = pn.widgets.StaticText(value="0", height=30)


def update_user_count():
    active_user_count.value = str(len(pn.state.active_sessions))


pn.state.add_periodic_callback(update_user_count, period=2000)

# --- Layout ---
monitor = pn.Row(ram_usage_label, ram_monitor, active_user_count_label, active_user_count, sizing_mode="stretch_width")
