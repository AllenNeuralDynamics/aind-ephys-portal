"""Main Panel application for the AIND SIGUI Portal."""

import panel as pn
import pandas as pd

from aind_sigui_portal.panel.utils import format_link
from aind_sigui_portal.panel.search import get_search_input, get_search_results, options

class SIGUIPortal:
    """SIGUI Portal Panel application."""

    def __init__(self):
        """Initialize the SIGUI Portal application."""
        # Get the search input widget
        self.search_bar = get_search_input()
        
        # Create a selection widget to track the selected row
        self.selected_index = pn.widgets.IntInput(name="Selected Index", value=0, visible=False)
        
        # Create a results panel that will display search results with selection
        self.results_panel = pn.widgets.Tabulator(
            pd.DataFrame(),  # Empty DataFrame initially
            width=800,
            height=400,
            sizing_mode="stretch_width",
            selectable=True,
            disabled=True,
            show_index=False,
            styles={"background-color": "#f5f5f5", "padding": "20px", "border-radius": "5px"}
        )
        
        # Create a streams panel to display postprocessed streams for the selected entry
        self.streams_panel = pn.pane.DataFrame(
            pd.DataFrame(columns=["Stream", "SIGUI View"]),  # Empty DataFrame initially
            width=800,
            height=200,
            sizing_mode="stretch_width",
            index=False,
            styles={"background-color": "#f5f5f5", "padding": "20px", "border-radius": "5px"}
        )
        
        # Update the results panel when the search input changes
        self.search_bar.param.watch(self.update_results, "value")
        
        # Update the streams panel when a row is selected
        self.results_panel.on_click(self.update_streams)
        
        # Initialize with current results
        self.update_results(None)
    
    def update_results(self, event):
        """Update the results panel with the current search results."""
        print("Updating search results...")
        df = get_search_results()
        self.results_panel.value = df
        # Clear the streams panel when results are updated
        self.streams_panel.object = pd.DataFrame(columns=["Stream", "SIGUI View"])
    
    def update_streams(self, event):
        """Update the streams panel with the postprocessed streams for the selected entry."""
        if event.row is None:
            return
        
        # Get the selected row data
        selected_row = self.results_panel.value.iloc[event.row]
        selected_name = selected_row["name"]
        
        
        # Find the corresponding record in the original data
        for record in options.all_records:
            if record.get("name") == selected_name:
                location = record.get("location", "")

                loading_text = f"Loading postprocessed streams..."
                streams_df = pd.DataFrame({"Stream": [loading_text], "SIGUI View": [""]})
                self.streams_panel.object = streams_df
                
                # Get the postprocessed streams for this location
                streams = options.get_postprocessed_streams(location)
                print(f"Found {len(streams)} postprocessed streams from {location}")
                links = [format_link(stream) for stream in streams]
                
                # Update the streams panel
                streams_df = pd.DataFrame({"Stream": streams, "SIGUI View": links})
                self.streams_panel.object = streams_df
                return
        
        # If no matching record is found, clear the streams panel
        self.streams_panel.object = pd.DataFrame(columns=["Stream"])
        
    def panel(self):
        """Build a Panel object representing the SIGUI Portal."""
        # Create a layout with the search bar at the top, results panel in the middle,
        # and streams panel at the bottom
        layout = pn.Column(
            pn.pane.Markdown("# AIND SIGUI Portal", styles={"text-align": "center"}),
            pn.Row(self.search_bar, width=800, align="center"),
            pn.layout.Divider(),
            pn.pane.Markdown("## Search Results", styles={"text-align": "left"}),
            self.results_panel,
            pn.layout.Divider(),
            pn.pane.Markdown("## Postprocessed Streams", styles={"text-align": "left"}),
            self.streams_panel,
            width=900,
            align="center"
        )
        
        return layout

def create_app():
    """Create and return the SIGUI Portal Panel application."""
    portal = SIGUIPortal()
    return portal.panel()
