"""Standalone launcher page to generate comparison GUI links."""

import urllib.parse

import panel as pn

from aind_ephys_portal.session_logging import setup_logging
from aind_ephys_portal.panel.utils import EPHYSCOMPARISON_LINK_PREFIX, make_absolute_url

pn.extension()


class EphysComparisonLauncher:
    """Like the ephys launcher, with the paths (and display names) of two analyzers"""

    def __init__(self):
        setup_logging()

        def text_input(name):
            return pn.widgets.TextInput(name=name, value="", height=50, sizing_mode="stretch_width")

        self.analyzer1_input = text_input("Analyzer 1 path")
        self.analyzer1_name_input = text_input("Analyzer 1 name (optional)")
        self.analyzer2_input = text_input("Analyzer 2 path")
        self.analyzer2_name_input = text_input("Analyzer 2 name (optional)")
        self.recording_input = text_input("Recording path (optional)")

        self.generate_button = pn.widgets.Button(
            name="Generate Link",
            button_type="primary",
            height=45,
            sizing_mode="stretch_width",
        )
        self.fast_mode_checkbox = pn.widgets.Checkbox(
            name="Enable Fast Mode (skip waveforms and PCs)",
            value=False,
            height=30,
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
            pn.pane.Markdown("## AIND Ephys Comparison Launcher"),
            pn.Row(self.analyzer1_input, self.analyzer1_name_input, sizing_mode="stretch_width"),
            pn.Row(self.analyzer2_input, self.analyzer2_name_input, sizing_mode="stretch_width"),
            self.recording_input,
            pn.Row(self.generate_button, self.fast_mode_checkbox, sizing_mode="stretch_width"),
            self.link_pane,
            self.url_output,
            sizing_mode="stretch_width",
        )

    def _build_gui_path(self):
        analyzer_path1 = self.analyzer1_input.value.strip()
        analyzer_path2 = self.analyzer2_input.value.strip()
        if not analyzer_path1 or not analyzer_path2:
            return None

        query = {"analyzer_path1": analyzer_path1, "analyzer_path2": analyzer_path2}
        for key, widget in (
            ("analyzer1_name", self.analyzer1_name_input),
            ("analyzer2_name", self.analyzer2_name_input),
            ("recording_path", self.recording_input),
        ):
            if widget.value.strip():
                query[key] = widget.value.strip()
        if self.fast_mode_checkbox.value:
            query["fast_mode"] = "true"
        return f"{EPHYSCOMPARISON_LINK_PREFIX}?{urllib.parse.urlencode(query, quote_via=urllib.parse.quote, safe='')}"

    def _update_link(self, event=None):
        path = self._build_gui_path()
        if not path:
            self.link_pane.object = "<span style='color: orange;'>⚠️ Both analyzer paths are required.</span>"
            self.url_output.value = ""
            return
        url = make_absolute_url(path)
        print(f"Generated URL: {url}")

        self.link_pane.object = f'<a href="{url}" target="_blank">Ephys Comparison GUI</a>'
        self.url_output.value = url


app = EphysComparisonLauncher()
app.layout.servable(title="AIND Ephys Comparison Launcher")
