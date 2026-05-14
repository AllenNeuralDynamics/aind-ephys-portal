"""Main Panel application for the AIND SIGUI Portal."""

import os
import threading
import param
import panel as pn
import pandas as pd
import boto3


from aind_ephys_portal.docdb.database import get_raw_asset_by_name, get_all_ecephys_derived
from aind_ephys_portal.panel.utils import format_link, OUTER_STYLE, EPHYSGUI_LINK_PREFIX
from aind_ephys_portal.session_logging import setup_logging, get_container_total_memory, get_container_used_memory

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
        setup_logging()  # Ensure logging is set up for this panel
        # for test deployment, use v1 by default
        default_db_version = "v2" if os.environ.get("TEST_ENV", "0") == "0" else "v1"
        # Initialize search options without blocking on database load
        self.search_options = SearchOptions(database_version=default_db_version, defer_load=True)
        self._db_loading = False
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
            min_height=400,
            selectable=True,
            disabled=True,
            show_index=False,
            stylesheets=[stylesheet],
            styles={"background-color": "#f5f5f5", "padding": "20px", "border-radius": "5px"},
        )
        self._results_loading_pane = pn.pane.Markdown(
            "*Loading Database...*",
            styles={"background-color": "#f5f5f5", "padding": "20px", "border-radius": "5px", "min-height": "200px"},
        )
        self.results_container = pn.Column(self._results_loading_pane)

        # Create a streams panel to display postprocessed streams for the selected entry
        self.streams_panel = pn.widgets.Tabulator(
            pd.DataFrame(columns=["Stream name", "Ephys GUI View"]),  # Empty DataFrame initially
            min_height=200,
            sizing_mode="stretch_width",
            show_index=False,
            disabled=True,
            formatters={"Ephys GUI View": {"type": "html"}},  # Tell Tabulator to render this column as HTML
            widths={"Stream name": "50%", "Ephys GUI View": "50%"},  # Changed from column_width to widths
            stylesheets=[stylesheet],
            styles={"background-color": "#f5f5f5", "padding": "20px", "border-radius": "5px"},
        )
        self._streams_loading_pane = pn.pane.Markdown(
            "*Loading postprocessed streams...*",
            styles={"background-color": "#f5f5f5", "padding": "20px", "border-radius": "5px", "min-height": "100px"},
        )
        self.streams_container = pn.Column(self.streams_panel)

        # Update the results panel when the search input changes
        self.search_bar.param.watch(self.update_results, "value")

        # Update the streams panel when a row is selected
        self.results_panel.on_click(self.update_streams)

        self.database_version_dropdown = pn.widgets.Select(
            name="Database Version", options=["v1", "v2"], value=default_db_version, width=150
        )
        self.database_version_dropdown.param.watch(self.update_db_version, "value")
        self.refresh_button = pn.widgets.Button(name="Refresh Datasets", button_type="primary", height=30, width=150)
        self.refresh_button.on_click(self.update_results)
        # Load database in a background thread so the UI renders immediately
        self._load_database()

    def _run_in_background(self, target, on_complete):
        """Run *target()* in a daemon thread; schedule *on_complete(result)* on the UI thread."""
        def _worker():
            result = target()
            pn.state.execute(lambda: on_complete(result))

        t = threading.Thread(target=_worker, daemon=True)
        t.start()

    def _set_db_loading(self, loading):
        """Toggle the loading state and enable/disable controls accordingly."""
        self._db_loading = loading
        self.refresh_button.disabled = loading
        self.database_version_dropdown.disabled = loading

    def _load_database(self):
        """Kick off a background thread to load/reload the database."""
        self._set_db_loading(True)
        self.results_container[:] = [self._results_loading_pane]
        self.streams_container[:] = [self.streams_panel]
        self.streams_panel.value = pd.DataFrame(columns=["Stream name", "Ephys GUI View"])

        def _do_load():
            used = get_container_used_memory()
            total = get_container_total_memory()
            print(f"[Portal] RAM before DB load: {used / (1024**3):.2f} GB / {total / (1024**3):.2f} GB ({used / total * 100:.1f}%)")
            self.search_options.update_options()
            used = get_container_used_memory()
            print(f"[Portal] RAM after DB load:  {used / (1024**3):.2f} GB / {total / (1024**3):.2f} GB ({used / total * 100:.1f}%)")
            return self.search_options.df

        def _on_loaded(df):
            self._set_db_loading(False)
            self.results_panel.value = df
            self.results_container[:] = [self.results_panel]
            print("Database loaded.")

        self._run_in_background(_do_load, _on_loaded)

    def update_db_version(self, event):
        """Update the database version used for searching."""
        if event.new != event.old:
            new_version = event.new
            print(f"Switching to database version: {new_version}")
            self.search_options.database_version = new_version
            self._load_database()

    def update_db_version(self, event):
        """Update the database version used for searching."""
        if event.new != event.old:
            new_version = event.new
            print(f"Switching to database version: {new_version}")
            self.search_options.database_version = new_version
            self.search_options.update_options()
            self.update_results(None)

    def update_results(self, event):
        """Update the results panel with the current search results."""
        print("Updating search results...")
        if event is None:
            df = self.search_options.df
        elif event.name == "clicks":
            # Refresh button: reload from database in a background thread
            self._load_database()
            return
        else:
            # Filter the DataFrame based on the search input
            if self._db_loading:
                # Database is still loading; nothing to filter yet
                return
            df = self.search_options.df_filtered(event.new)
        self.results_panel.value = df
        self.results_container[:] = [self.results_panel]
        # Clear the streams panel when results are updated
        self.streams_panel.value = pd.DataFrame(columns=["Stream name", "Ephys GUI View"])
        self.streams_container[:] = [self.streams_panel]

    def update_streams(self, event):
        """Update the streams panel with the postprocessed streams for the selected entry."""
        if event.row is None:
            return

        # Get the selected row data
        selected_row = self.results_panel.value.iloc[event.row]
        selected_name = selected_row["name"]
        db_version = self.search_options.database_version

        # Find the corresponding record in the original data
        for record in self.search_options.all_records:
            if record.get("name") == selected_name:
                asset_name = record.get("name", "")
                location = record.get("location", "")

                # Show loading pane while fetching streams in background
                self.streams_container[:] = [self._streams_loading_pane]

                # Fetch streams data in a background thread to avoid blocking the UI
                def _on_streams_loaded(result_df):
                    self.streams_panel.value = result_df
                    self.streams_container[:] = [self.streams_panel]

                self._run_in_background(
                    lambda: self._fetch_streams_data(record, asset_name, location, db_version),
                    _on_streams_loaded,
                )
                return

        # If no matching record is found, show message
        self.streams_container[:] = [pn.pane.Markdown(
            "*No postprocessed streams...*",
            styles={"background-color": "#f5f5f5", "padding": "20px", "border-radius": "5px"},
        )]

    def _fetch_streams_data(self, record, asset_name, location, db_version):
        """Blocking helper that fetches postprocessed stream data (runs in a background thread)."""
        stream_names = self.search_options.get_postprocessed_streams(location)
        print(f"Found {len(stream_names)} postprocessed streams from {location}")
        analyzer_base_location = record["location"]
        raw_asset = get_raw_asset_by_name(asset_name, version=db_version)[0]
        links_url = []
        for stream_name in stream_names:
            raw_stream_name = stream_name[: stream_name.find("_recording")]
            raw_asset_prefix = self.get_raw_asset_location(raw_asset["location"])
            print(f"Raw asset prefix: {raw_asset_prefix}")
            if raw_asset_prefix is None:
                recording_path = ""
            else:
                recording_path = f"{raw_asset_prefix}/{raw_stream_name}.zarr"
            analyzer_path = f"{analyzer_base_location}/postprocessed/{stream_name}"
            if not analyzer_path.endswith(".zarr"):
                link_url = "Only Zarr files are supported."
            else:
                link_url = EPHYSGUI_LINK_PREFIX.format(analyzer_path, recording_path, asset_name).replace(
                    "#", "%23"
                )
            links_url.append(link_url)
        links = []
        for link in links_url:
            if "ephys_gui_app" in link:
                links.append(format_link(link, text="SpikeInterface-GUI"))
            else:
                links.append(link)

        return pd.DataFrame({"Stream name": stream_names, "Ephys GUI View": links})

    def get_raw_asset_location(self, asset_location):
        asset_without_s3 = asset_location[asset_location.find("s3://") + 5 :]
        asset_split = asset_without_s3.split("/")
        bucket_name = asset_split[0]
        session_name = "/".join(asset_split[1:])
        possible_locations = ["ecephys/ecephys_compressed", "ecephys_compressed"]
        raw_asset_location = None
        for location in possible_locations:
            prefix = f"{session_name}/{location}/"
            try:
                response = s3_client.list_objects_v2(Bucket=bucket_name, Prefix=prefix, MaxKeys=1)
            except Exception as e:
                print(f"Error listing objects with unsigned client from {bucket_name}/{prefix}: {e}")
                continue
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
            pn.Row(self.search_bar, self.database_version_dropdown, align="center"),
            self.refresh_button,
            pn.layout.Divider(),
            pn.pane.Markdown("## Search Results", styles={"text-align": "left"}),
            self.results_container,
            pn.layout.Divider(),
            pn.pane.Markdown("## Postprocessed Streams", styles={"text-align": "left"}),
            self.streams_container,
            min_width=1500,
            styles=OUTER_STYLE,
            align="center",
        )
        display = pn.Row(pn.HSpacer(), col, pn.HSpacer(), sizing_mode="stretch_width")

        return display


class SearchOptions(param.Parameterized):
    """Search options for the Ephys Portal."""

    def __init__(self, database_version="v2", defer_load=False):
        """Initialize a search options object."""
        super().__init__()
        self.database_version = database_version
        self.all_records = []
        self.df = pd.DataFrame(columns=["name", "subject_id", "date", "id"])

        if not defer_load:
            self.update_options()

    def update_options(self):
        # Get initial data
        data = []
        try:
            # Get initial data from database
            version = self.database_version
            self.all_records = get_all_ecephys_derived(additional_includes_in_name="sorted", version=version)
            print(f"Loaded {len(self.all_records)} 'sorted' records.")
            # Process records into a list of dictionaries
            for record in self.all_records:
                created_str = "_created" if version == "v2" else "created"
                r = {
                    "name": record.get("name", ""),
                    "date": record.get(created_str, ""),
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

        # Create DataFrame and sort by date if available
        self.df = pd.DataFrame(data, columns=["name", "subject_id", "date", "id"])
        if not self.df.empty and "date" in self.df.columns:
            self.df = self.df.sort_values(by="date", ascending=False)

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
            # Search first in the 'name' column. If no matches, we check for the dataset ID
            mask = self.df["name"].str.contains(text_filter, case=False)
            if not mask.any():
                mask = self.df["id"].str.contains(text_filter, case=False)
            df_filtered = self.df[mask]
            return df_filtered
        except Exception as e:
            print(f"Error searching records: {e}")
            # Return a sample search result to show the interface works
            return pd.DataFrame(columns=self.df.columns)
