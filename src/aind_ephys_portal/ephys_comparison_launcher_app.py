"""Standalone launcher page to generate comparison GUI links."""

import os
import re
import urllib.parse

import boto3
import panel as pn

from aind_ephys_portal.session_logging import setup_logging
from aind_ephys_portal.panel.utils import EPHYSCOMPARISON_LINK_PREFIX, make_absolute_url

pn.extension()

s3_client = boto3.client("s3")


def list_zarr_streams(session_path):
    """List the zarr analyzer names under {session_path}/postprocessed/."""
    bucket, _, prefix = session_path.removeprefix("s3://").rstrip("/").partition("/")
    prefix = f"{prefix}/postprocessed/" if prefix else "postprocessed/"
    names = set()
    for page in s3_client.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix, Delimiter="/"):
        for cp in page.get("CommonPrefixes", []):
            name = cp["Prefix"][len(prefix) :].strip("/")
            if name.endswith(".zarr"):
                names.add(name)
    return names


class EphysComparisonLauncher:
    """Like the ephys launcher, with the paths (and display names) of two analyzers"""

    def __init__(self):
        setup_logging()

        def text_input(name):
            return pn.widgets.TextInput(name=name, value="", height=50, sizing_mode="stretch_width")

        self.analyzer1_input = text_input("Session 1 path (s3://bucket/session_name)")
        self.analyzer1_name_input = text_input("Analyzer 1 name (optional)")
        self.analyzer2_input = text_input("Session 2 path (s3://bucket/session_name)")
        self.analyzer2_name_input = text_input("Analyzer 2 name (optional)")

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
            pn.Row(self.generate_button, self.fast_mode_checkbox, sizing_mode="stretch_width"),
            self.link_pane,
            self.url_output,
            sizing_mode="stretch_width",
        )

    def _build_gui_path(self, stream, base1, base2):
        query = {
            "analyzer_path1": f"{base1}/postprocessed/{stream}",
            "analyzer_path2": f"{base2}/postprocessed/{stream}",
        }
        for key, widget in (
            ("analyzer1_name", self.analyzer1_name_input),
            ("analyzer2_name", self.analyzer2_name_input),
        ):
            if widget.value.strip():
                query[key] = widget.value.strip()
        # header label: common part of the two session names + stream name
        name1, name2 = (b.rstrip("/").rsplit("/", 1)[-1] for b in (base1, base2))
        common = os.path.commonprefix([name1, name2]).rstrip("_-. ").removesuffix("_sorted")
        query["session"] = " / ".join(filter(None, [common, stream.removesuffix(".zarr")]))
        if self.fast_mode_checkbox.value:
            query["fast_mode"] = "true"
        return f"{EPHYSCOMPARISON_LINK_PREFIX}?{urllib.parse.urlencode(query, quote_via=urllib.parse.quote, safe='')}"

    def _update_link(self, event=None):
        base1 = self.analyzer1_input.value.strip().rstrip("/")
        base2 = self.analyzer2_input.value.strip().rstrip("/")
        self.url_output.value = ""
        if not base1 or not base2:
            self.link_pane.object = "<span style='color: orange;'>⚠️ Both session paths are required.</span>"
            return
        try:
            streams = sorted(
                list_zarr_streams(base1) & list_zarr_streams(base2),
                key=lambda n: [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", n)],  # natural sort
            )
        except Exception as e:
            self.link_pane.object = f"<span style='color: red;'>Could not list streams: {e}</span>"
            return
        if not streams:
            self.link_pane.object = "<span style='color: orange;'>⚠️ No common zarr streams found.</span>"
            return
        urls = [make_absolute_url(self._build_gui_path(s, base1, base2)) for s in streams]
        self.link_pane.object = "<ul>" + "".join(
            f'<li><a href="{u}" target="_blank">{s}</a></li>' for s, u in zip(streams, urls)
        ) + "</ul>"
        self.url_output.value = "\n".join(urls)


app = EphysComparisonLauncher()
app.layout.servable(title="AIND Ephys Comparison Launcher")
