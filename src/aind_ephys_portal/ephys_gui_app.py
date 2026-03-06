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
    preload_curation = param.Boolean(
        default=False,
        doc="Whether to preload existing curation from disk (if available)"
    )


settings = Settings()
pn.state.location.sync(settings, {"analyzer_path": "analyzer_path", "recording_path": "recording_path", "identifier": "identifier", "fast_mode": "fast_mode", "preload_curation": "preload_curation"})



analyzer_path = urllib.parse.unquote(_get_arg("analyzer_path"))
recording_path = urllib.parse.unquote(_get_arg("recording_path"))
identifier = urllib.parse.unquote(_get_arg("identifier"))
fast_mode = _get_arg("fast_mode", "false").lower() in ("true", "1", "yes")
preload_curation = _get_arg("preload_curation", "false").lower() in ("true", "1", "yes")

print(f"Parsed arguments:")
print(f"\tanalyzer_path={analyzer_path}\n\trecording_path={recording_path}\n\tidentifier={identifier}\n\tfast_mode={fast_mode}\n\tpreload_curation={preload_curation}")

ephys_gui = EphysGuiView(analyzer_path=analyzer_path, recording_path=recording_path, identifier=identifier, fast_mode=fast_mode, preload_curation=preload_curation)

ephys_gui.panel().servable(title="AIND Ephys GUI")

# Register session cleanup on the document. The document is definitively bound
# to this session at module-execution time, so curdoc is correct here.
# Factory function creates a proper closure (cell variable) for view_ref,
# which is immune to Panel's exec() scoping (exec uses separate globals/locals
# dicts, so plain module-level names are inaccessible inside callbacks).
def _make_cleanup_callback(view):
    view_ref = [view]
    def _on_session_destroyed(session_context):
        v = view_ref[0]
        view_ref[0] = None  # always break the reference, even if cleanup raises
        if v is not None:
            v.cleanup()
    return _on_session_destroyed

pn.state.curdoc.on_session_destroyed(_make_cleanup_callback(ephys_gui))
print(f"[GUI] Cleanup registered on doc {id(pn.state.curdoc)}")

# Don't keep a module-level reference to the heavy GUI object.
# The servable layout is now owned by Panel/Bokeh's document.
del ephys_gui