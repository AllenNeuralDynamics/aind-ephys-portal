"""SIGUI View main entrypoint"""

import urllib
import param

import panel as pn

pn.extension("tabulator", "gridstack")

# Import for side effects: registers SpikeInterface GUI custom Panel/Bokeh models/resources
import spikeinterface_gui.utils_panel  # noqa: F401

from aind_ephys_portal.panel.ephys_gui import EphysGuiView

    

# State sync
class Settings(param.Parameterized):
    """Top-level settings for QC app"""

    analyzer_path = param.String(default="")
    recording_path = param.String(default="")
    identifier = param.String(default="")
    fast_mode = param.Boolean(
        default=False,
        doc="Whether to enable fast mode (skips waveforms and principal components)"
    )


settings = Settings()
pn.state.location.sync(settings, {"analyzer_path": "analyzer_path", "recording_path": "recording_path", "identifier": "identifier", "fast_mode": "fast_mode"})

# Manually decode stream_name after syncing
settings.analyzer_path = urllib.parse.unquote(settings.analyzer_path)
settings.recording_path = urllib.parse.unquote(settings.recording_path)

print(settings)

ephys_gui = EphysGuiView(analyzer_path=settings.analyzer_path, recording_path=settings.recording_path, identifier=settings.identifier, fast_mode=settings.fast_mode)

ephys_gui.panel().servable(title="AIND Ephys GUI")

# Don't keep a module-level reference to the heavy GUI object.
# The servable layout is now owned by Panel/Bokeh's document.
del ephys_gui