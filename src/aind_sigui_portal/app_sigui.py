"""SIGUI View main entrypoint"""

import panel as pn
import param

from aind_sigui_portal.panel.sigui_view import SIGuiView

pn.extension()


# State sync
class Settings(param.Parameterized):
    """Top-level settings for QC app"""

    id = param.String(default="b99f821e-c81e-4465-b783-22adf33be74a")
    stream_name = param.String(default="experiment1_Record Node 104#Neuropix-PXI-100.ProbeA-AP_recording1.zarr")


settings = Settings()
pn.state.location.sync(settings, {"id": "id", "stream_name": "stream_name"})

sigui_panel = SIGuiView(id=settings.id, stream_name=settings.stream_name)

sigui_panel.panel().servable(title="AIND SIGUI - View")
