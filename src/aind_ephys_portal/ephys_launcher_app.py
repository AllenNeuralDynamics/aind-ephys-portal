"""Standalone launcher page to generate GUI links."""

import urllib.parse

import panel as pn

from aind_ephys_portal.panel.utils import EPHYSGUI_LINK_PREFIX

pn.extension()


analyzer_input = pn.widgets.TextInput(
    name="Analyzer path",
    value="",
    height=50,
    sizing_mode="stretch_width",
)
recording_input = pn.widgets.TextInput(
    name="Recording path (optional)",
    value="",
    height=50,
    sizing_mode="stretch_width",
)

generate_button = pn.widgets.Button(
    name="Generate Link",
    button_type="primary",
    height=45,
    sizing_mode="stretch_width",
)

status = pn.pane.Markdown("", sizing_mode="stretch_width")
link_pane = pn.pane.HTML("", sizing_mode="stretch_width")
url_output = pn.widgets.TextInput(
    name="GUI URL",
    value="",
    disabled=True,
    sizing_mode="stretch_width",
)


def _build_gui_url():
    analyzer_path = analyzer_input.value.strip()
    recording_path = recording_input.value.strip()
    if not analyzer_path:
        return None

    analyzer_path_q = urllib.parse.quote(analyzer_path, safe="")
    recording_path_q = urllib.parse.quote(recording_path, safe="") if recording_path else ""
    path = EPHYSGUI_LINK_PREFIX.format(analyzer_path_q, recording_path_q)

    location = pn.state.location
    if location is not None:
        href = getattr(location, "href", None)
        if href:
            parsed = urllib.parse.urlparse(href)
            if parsed.scheme and parsed.netloc:
                return f"{parsed.scheme}://{parsed.netloc}{path}"

        protocol = getattr(location, "protocol", "")
        hostname = getattr(location, "hostname", "")
        port = getattr(location, "port", "")
        if protocol and hostname:
            netloc = f"{hostname}:{port}" if port else hostname
            return f"{protocol}//{netloc}{path}"

    return path


def _update_link(event=None):
    url = _build_gui_url()
    if not url:
        status.object = "⚠️ Analyzer path is required."
        link_pane.object = ""
        url_output.value = ""
        return

    status.object = ""
    link_pane.object = f"<a href=\"{url}\" target=\"_blank\">Open Ephys GUI</a>"
    url_output.value = url


generate_button.on_click(_update_link)
# analyzer_input.param.watch(_update_link, "value")
# recording_input.param.watch(_update_link, "value")


app_layout = pn.Column(
    pn.pane.Markdown("## AIND Ephys Launcher"),
    analyzer_input,
    recording_input,
    generate_button,
    status,
    link_pane,
    url_output,
    sizing_mode="stretch_width",
)

app_layout.servable(title="AIND Ephys Launcher")
