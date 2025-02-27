"""Main application file for the AIND SIGUI Portal.

This file can be directly served using the Panel CLI:
    panel serve app.py
"""

from aind_ephys_portal.panel.utils import format_css_background
from aind_ephys_portal.panel.ephys_portal import EphysPortal


format_css_background()

# Create the application
app = EphysPortal().panel()

# Make the app servable
app.servable(title="AIND Ephys Portal")
