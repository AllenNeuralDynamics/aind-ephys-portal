"""SIGUI View main entrypoint"""

import urllib
import param

from aind_ephys_portal.panel.ephys_gui import EphysGuiView

import panel as pn

pn.extension("tabulator", "gridstack")

from spikeinterface_gui.utils_panel import KeyboardShortcuts


# State sync
class Settings(param.Parameterized):
    """Top-level settings for QC app"""

    analyzer_path = param.String(default="")
    recording_path = param.String(default="")


settings = Settings()
pn.state.location.sync(settings, {"analyzer_path": "analyzer_path", "recording_path": "recording_path"})

# Manually decode stream_name after syncing
settings.analyzer_path = urllib.parse.unquote(settings.analyzer_path)
settings.recording_path = urllib.parse.unquote(settings.recording_path)


ephys_gui = EphysGuiView(analyzer_path=settings.analyzer_path, recording_path=settings.recording_path)
ephys_gui_panel = ephys_gui.panel()

ephys_gui_panel.servable(title="AIND Ephys GUI")
