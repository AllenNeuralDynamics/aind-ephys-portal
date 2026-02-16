"""Standalone launcher page to generate GUI links."""

import urllib.parse

import panel as pn

from aind_ephys_portal.panel.logging import setup_logging
from aind_ephys_portal.panel.utils import EPHYSGUI_LINK_PREFIX

pn.extension()


class EphysLauncher:
    def __init__(self):
        setup_logging()

        self.analyzer_input = pn.widgets.TextInput(
            name="Analyzer path",
            value="",
            height=50,
            sizing_mode="stretch_width",
        )
        self.recording_input = pn.widgets.TextInput(
            name="Recording path (optional)",
            value="",
            height=50,
            sizing_mode="stretch_width",
        )

        self.generate_button = pn.widgets.Button(
            name="Generate Link",
            button_type="primary",
            height=45,
            sizing_mode="stretch_width",
        )

        self.link_pane = pn.pane.HTML("No link generated yet.", sizing_mode="stretch_width")
        self.url_output = pn.widgets.TextInput(
            name="GUI URL",
            value="",
            disabled=True,
            sizing_mode="stretch_width",
        )

        self.generate_button.on_click(self._update_link)

        self.layout = pn.Column(
            pn.pane.Markdown("## AIND Ephys Launcher"),
            self.analyzer_input,
            self.recording_input,
            self.generate_button,
            self.link_pane,
            self.url_output,
            sizing_mode="stretch_width",
        )

    def _build_gui_url(self):
        analyzer_path = self.analyzer_input.value.strip()
        recording_path = self.recording_input.value.strip()
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

    def _update_link(self, event=None):
        url = self._build_gui_url()
        if not url:
            self.link_pane.object = "<span style='color: orange;'>⚠️ Analyzer path is required.</span>"
            self.url_output.value = ""
            return
        print(f"Generated URL: {url}")

        self.link_pane.object = f'<a href="{url}" target="_blank">Ephys Curation GUI</a>'
        self.url_output.value = url


app = EphysLauncher()
app.layout.servable(title="AIND Ephys Launcher")
