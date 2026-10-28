"""SIGUI comparison View main entrypoint"""

import urllib
import param

import panel as pn

pn.extension("tabulator", "gridstack")

# Import for side effects: registers SpikeInterface GUI custom Panel/Bokeh models/resources
import spikeinterface_gui.utils_panel  # noqa: F401

from aind_ephys_portal.panel.ephys_comparison_gui import EphysComparisonGuiView


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
    """Top-level settings for the comparison app"""

    analyzer_path1 = param.String(default="")
    analyzer_path2 = param.String(default="")
    analyzer1_name = param.String(default="")
    analyzer2_name = param.String(default="")
    recording_path = param.String(default="")
    fast_mode = param.Boolean(
        default=False, doc="Whether to enable fast mode (skips waveforms and principal components)"
    )
    session = param.String(default=None, doc="Session name to display in header (optional)")


settings = Settings()
pn.state.location.sync(
    settings,
    {
        "analyzer_path1": "analyzer_path1",
        "analyzer_path2": "analyzer_path2",
        "analyzer1_name": "analyzer1_name",
        "analyzer2_name": "analyzer2_name",
        "recording_path": "recording_path",
        "fast_mode": "fast_mode",
        "session": "session",
    },
)


analyzer_path1 = urllib.parse.unquote(_get_arg("analyzer_path1"))
analyzer_path2 = urllib.parse.unquote(_get_arg("analyzer_path2"))
analyzer1_name = urllib.parse.unquote(_get_arg("analyzer1_name"))
analyzer2_name = urllib.parse.unquote(_get_arg("analyzer2_name"))
recording_path = urllib.parse.unquote(_get_arg("recording_path"))
fast_mode = _get_arg("fast_mode", "false").lower() in ("true", "1", "yes")
session = urllib.parse.unquote(_get_arg("session"))

print(f"Parsed arguments:")
print(
    f"\tanalyzer_path1={analyzer_path1}\n\tanalyzer_path2={analyzer_path2}"
    f"\n\tanalyzer1_name={analyzer1_name}\n\tanalyzer2_name={analyzer2_name}"
    f"\n\trecording_path={recording_path}\n\tfast_mode={fast_mode}\n\tsession={session}"
)

ephys_gui = EphysComparisonGuiView(
    analyzer_path1=analyzer_path1,
    analyzer_path2=analyzer_path2,
    analyzer1_name=analyzer1_name,
    analyzer2_name=analyzer2_name,
    recording_path=recording_path,
    fast_mode=fast_mode,
    session=session,
)

ephys_gui.panel().servable(title="AIND Ephys Comparison GUI")


# Same cleanup registration as ephys_gui_app: a factory so that the closure survives
# Panel's exec() scoping, and no module-level reference to the heavy GUI object.
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

del ephys_gui
