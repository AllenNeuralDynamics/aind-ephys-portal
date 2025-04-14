"""Main Panel application for the AIND SIGUI Portal."""

import param
import threading
import panel as pn
import pandas as pd
import boto3

from aind_ephys_portal.docdb.database import get_raw_asset_by_name, get_all_ecephys_derived
from aind_ephys_portal.panel.utils import format_link, OUTER_STYLE, EPHYSGUI_LINK_PREFIX

s3_client = boto3.client("s3")


class EphysPortal:
    """
    Ephys Portal Panel application.

    This class provides a search interface for ecephys processed assets and their postprocessed streams.
    It allows users to search for assets, view their details, and access the postprocessed streams, and
    renders a link to the Ephys GUI for each stream.

    The search options auto-updates every 30 minutes to sync with new data in the database.
    """

    def __init__(self):
        """Initialize the SIGUI Portal application."""
        self.search_options = SearchOptions()
        # Get the search input widget
        self.search_bar = pn.widgets.TextInput(
            name="Search",
            placeholder="Enter search terms...",
            sizing_mode="stretch_width",
        )

        stylesheet = """
        .tabulator-cell {
            font-size: 10px;
        }
        """
        self.results_panel = pn.widgets.Tabulator(
            pd.DataFrame(columns=["name", "subject_id", "date", "id"]),  # Empty DataFrame initially
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
            formatters={"Ephys GUI View": {"type": "html"}},  # Tell Tabulator to render this column as HTML
            widths={"Stream name": "50%", "Ephys GUI View": "50%"},  # Changed from column_width to widths
            stylesheets=[stylesheet],
            styles={"background-color": "#f5f5f5", "padding": "20px", "border-radius": "5px"},
        )

        # Update the results panel when the search input changes
        self.search_bar.param.watch(self.update_results, "value")

        # Update the streams panel when a row is selected
        self.results_panel.on_click(self.update_streams)

        # Start the auto-update process
        # TODO: debug
        # self.auto_update_datasets()

        # Initialize with current results
        self.update_results(None)

    def update_results(self, event):
        """Update the results panel with the current search results."""
        print("Updating search results...")
        if event is None:
            df = self.search_options.df
        else:
            # Filter the DataFrame based on the search input
            df = self.search_options.df_filtered(event.new)
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
        for record in self.search_options.all_records:
            if record.get("name") == selected_name:
                asset_name = record.get("name", "")
                location = record.get("location", "")

                loading_text = f"Loading postprocessed streams..."
                streams_df = pd.DataFrame({"Stream name": [loading_text], "Ephys GUI View": [""]})
                self.streams_panel.value = streams_df

                # Get the postprocessed streams for this location
                stream_names = self.search_options.get_postprocessed_streams(location)
                print(f"Found {len(stream_names)} postprocessed streams from {location}")
                analyzer_base_location = record["location"]
                raw_asset = get_raw_asset_by_name(asset_name)[0]
                links_url = []
                for stream_name in stream_names:
                    raw_stream_name = stream_name[: stream_name.find("_recording")]
                    raw_asset_prefix = self.get_raw_asset_location(raw_asset["location"])
                    print(f"Raw asset prefix: {raw_asset_prefix}")
                    recording_path = f"{raw_asset_prefix}/{raw_stream_name}.zarr"
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

    # def auto_update_datasets(self):
    #     # Update the search options
    #     print(f"Updating datasets. Current number of ecephys processed assets: {len(self.search_options.df)}")
    #     self.search_options.update_options()
    #     print(f"Updated datasets. New number of ecephys processed assets: {len(self.search_options.df)}")

    #     # Schedule next run in 1 hour (3600 seconds)
    #     threading.Timer(3600, self.auto_update_datasets).start()

    def get_raw_asset_location(self, asset_location):
        asset_without_s3 = asset_location[asset_location.find("s3://") + 5:]
        asset_split = asset_without_s3.split("/")
        bucket_name = asset_split[0]
        session_name = "/".join(asset_split[1:])
        possible_locations = ["ecephys/ecephys_compressed", "ecephys_compressed"]
        raw_asset_location = None
        for location in possible_locations:
            prefix = f"{session_name}/{location}/"
            response = s3_client.list_objects_v2(Bucket=bucket_name, Prefix=prefix, MaxKeys=1)
            if "Contents" in response:
                raw_asset_location = f"s3://{bucket_name}/{prefix}"
                break
        if raw_asset_location is not None and raw_asset_location.endswith("/"):
            raw_asset_location = raw_asset_location[:-1]
        return raw_asset_location

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
            align="center",
        )
        display = pn.Row(pn.HSpacer(), col, pn.HSpacer())

        return display


class SearchOptions(param.Parameterized):
    """Search options for the Ephys Portal."""

    def __init__(self):
        """Initialize a search options object."""
        super().__init__()

        self.update_options()

        # Sort by date if available
        if not self.df.empty and "date" in self.df.columns:
            self.df = self.df.sort_values(by="date", ascending=False)

    def update_options(self):
        # Get initial data
        data = []
        try:
            # Get initial data from database
            self.all_records = get_all_ecephys_derived()
            print(f"Loaded {len(self.all_records)} records.")
            # Process records into a list of dictionaries
            for record in self.all_records:
                r = {
                    "name": record.get("name", ""),
                    "date": record.get("created", ""),
                    "id": record.get("_id", ""),
                    "location": record.get("location", ""),
                }
                subject = record.get("subject", {})
                if subject:
                    r["subject_id"] = subject.get("subject_id", "")
                else:
                    r["subject_id"] = record.get("subject_id", "")
                data.append(r)
        except Exception as e:
            print(f"Error loading initial data: {e}.")

        # Create DataFrame
        self.df = pd.DataFrame(data, columns=["name", "subject_id", "date", "id"])

    def get_postprocessed_streams(self, location):
        """Get the postprocessed folders for a given location."""
        # Get the bucket name and prefix
        bucket_name = location.split("/")[2]
        prefix = "/".join(location.split("/")[3:])

        paginator = s3_client.get_paginator("list_objects_v2")
        pages = paginator.paginate(Prefix=prefix, Bucket=bucket_name)
        posptrocessed_streams = []
        print(f"Looking for postprocessed streams in {bucket_name}/{prefix}")
        for page in pages:
            for item in page.get("Contents", []):
                key = item["Key"]
                if "postprocessed" in key and "postprocessed-sorting" not in key:
                    stream_name = key[key.find("postprocessed") :].split("/")[1]
                    if stream_name not in posptrocessed_streams:
                        posptrocessed_streams.append(stream_name)
        return posptrocessed_streams

    def df_filtered(self, text_filter=None):
        """Filter the options dataframe."""
        if text_filter is None or text_filter == "":
            return self.df
        print(f"Filtering records for: {text_filter}")

        # Search for records matching the text filter
        try:
            # Make sure we're returning a DataFrame, not a Series
            mask = self.df["name"].str.contains(text_filter, case=False)
            df_filtered = self.df[mask]
            return df_filtered
        except Exception as e:
            print(f"Error searching records: {e}")
            # Return a sample search result to show the interface works
            return pd.DataFrame(columns=self.df.columns)
