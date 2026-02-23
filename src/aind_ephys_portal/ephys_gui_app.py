"""SIGUI View main entrypoint"""

import urllib
import param

import panel as pn

pn.extension("tabulator", "gridstack")

# Import for side effects: registers SpikeInterface GUI custom Panel/Bokeh models/resources
import spikeinterface_gui.utils_panel  # noqa: F401

from aind_ephys_portal.panel.ephys_gui import EphysGuiView

def _get_arg(name: str, default: str = "") -> str:
    """Read a query-parameter from the raw HTTP request."""
    val = pn.state.session_args.get(name, [default.encode()])
    if isinstance(val, list):
        val = val[0]
    if isinstance(val, bytes):
        val = val.decode()
    return val
    

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


print("session_args:", {k: v for k, v in pn.state.session_args.items()})


analyzer_path = urllib.parse.unquote(_get_arg("analyzer_path"))
recording_path = urllib.parse.unquote(_get_arg("recording_path"))
identifier = _get_arg("identifier")
fast_mode = _get_arg("fast_mode", "false").lower() in ("true", "1", "yes")

ephys_gui = EphysGuiView(analyzer_path=analyzer_path, recording_path=recording_path, identifier=identifier, fast_mode=fast_mode)

ephys_gui.panel().servable(title="AIND Ephys GUI")

# Don't keep a module-level reference to the heavy GUI object.
# The servable layout is now owned by Panel/Bokeh's document.
del ephys_gui