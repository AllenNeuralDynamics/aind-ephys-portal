"""Main Panel application for the AIND SIGUI Portal."""

import panel as pn
import pandas as pd

from aind_ephys_portal.docdb.database import get_name_from_id, get_asset_by_name, get_raw_asset_by_name
from aind_ephys_portal.panel.utils import format_link, OUTER_STYLE, EPHYSGUI_LINK_PREFIX
from aind_ephys_portal.panel.search import get_search_input, get_search_results, options


class EphysPortal:
    """Ephys Portal Panel application."""

    def __init__(self):
        """Initialize the SIGUI Portal application."""
        # Get the search input widget
        self.search_bar = get_search_input()
        
        # Create a selection widget to track the selected row
        self.selected_index = pn.widgets.IntInput(name="Selected Index", value=0, visible=False)
        
        # Create a results panel that will display search results with selection
        stylesheet = """
        .tabulator-cell {
            font-size: 10px;
        }
        """
        self.results_panel = pn.widgets.Tabulator(
            pd.DataFrame(
                columns=[
                    "name",
                    "subject_id",
                    "date",
                    "id"
                ]
            ),  # Empty DataFrame initially
            height=400,
            selectable=True,
            disabled=True,
            show_index=False,
            stylesheets=[stylesheet],
            styles={"background-color": "#f5f5f5", "padding": "20px", "border-radius": "5px"},
        )
        
        # Create a streams panel to display postprocessed streams for the selected entry
        self.streams_panel = pn.widgets.Tabulator(
            pd.DataFrame(columns=["Stream name", "Ephys GUI View"]),  # Empty DataFrame initially
            height=200,
            sizing_mode="stretch_width",
            show_index=False,
            disabled=True,
            formatters={
                'Ephys GUI View': {'type': 'html'}  # Tell Tabulator to render this column as HTML
            },
            widths={  # Changed from column_width to widths
                'Stream name': '50%',
                'Ephys GUI View': '50%'
            },
            stylesheets=[stylesheet],
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
        self.streams_panel.value = pd.DataFrame(columns=["Stream name", "Ephys GUI View"])
    
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
                asset_name = record.get("name", "")
                location = record.get("location", "")

                loading_text = f"Loading postprocessed streams..."
                streams_df = pd.DataFrame({"Stream name": [loading_text], "Ephys GUI View": [""]})
                self.streams_panel.value = streams_df
                
                # Get the postprocessed streams for this location
                stream_names = options.get_postprocessed_streams(location)
                print(f"Found {len(stream_names)} postprocessed streams from {location}")
                analyzer_base_location = record["location"]
                raw_asset = get_raw_asset_by_name(asset_name)[0]
                links_url = []
                for stream_name in stream_names:
                    raw_stream_name = stream_name[:stream_name.find("_recording")]
                    recording_path = f"{raw_asset['location']}/ecephys/ecephys_compressed/{raw_stream_name}.zarr"
                    analyzer_path = f"{analyzer_base_location}/postprocessed/{stream_name}"
                    print("Raw path:", recording_path)
                    print("Analyzer path:", analyzer_path)
                    link_url = EPHYSGUI_LINK_PREFIX.format(analyzer_path, recording_path).replace("#", "%23")
                    links_url.append(link_url)
                links = [format_link(link) for link in links_url]
                
                # Update the streams panel
                streams_df = pd.DataFrame({"Stream name": stream_names, "Ephys GUI View": links})
                self.streams_panel.value = streams_df
                return
        
        # If no matching record is found, clear the streams panel
        no_streams_text = f"No postprocessed streams..."
        streams_df = pd.DataFrame({"Stream name": [no_streams_text], "Ephys GUI View": [""]})
        self.streams_panel.value = streams_df
        
    def panel(self):
        """Build a Panel object representing the Ephys Portal."""
        # Create a layout with the search bar at the top, results panel in the middle,
        # and streams panel at the bottom
        col = pn.Column(
            pn.pane.Markdown("# AIND Ephys Portal", styles={"text-align": "center"}),
            pn.Row(self.search_bar, align="center"),
            pn.layout.Divider(),
            pn.pane.Markdown("## Search Results", styles={"text-align": "left"}),
            self.results_panel,
            pn.layout.Divider(),
            pn.pane.Markdown("## Postprocessed Streams", styles={"text-align": "left"}),
            self.streams_panel,
            min_width=900,
            styles=OUTER_STYLE,
            align="center"
        )
        display = pn.Row(pn.HSpacer(), col, pn.HSpacer())
        
        return display
