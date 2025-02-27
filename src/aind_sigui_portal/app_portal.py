"""Main application file for the AIND SIGUI Portal.

This file can be directly served using the Panel CLI:
    panel serve app.py
"""

import panel as pn
from aind_sigui_portal.panel.sigui_portal import create_app

# Create the application
app = create_app()

# Make the app servable
app.servable(title="AIND SIGUI Portal")
