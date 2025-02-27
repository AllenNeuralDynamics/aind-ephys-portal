"""Search functionality for the AIND SIGUI Portal."""

import param
import panel as pn
import pandas as pd

from aind_ephys_portal.docdb.database import get_all_ecephys_derived

import boto3

s3_client = boto3.client("s3")

class SearchOptions(param.Parameterized):
    """Search options for the SIGUI Portal."""
    
    def __init__(self):
        """Initialize a search options object."""
        super().__init__()
        
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
                    "subject_id": record.get("subject", {}).get("subject_id", ""),
                    "date": record.get("created", ""),
                    "id": record.get("_id", ""),
                    "location": record.get("location", ""),
                }
                data.append(r)
        except Exception as e:
            print(f"Error loading initial data: {e}")
        
        # Create DataFrame
        self.df_full = pd.DataFrame(
            data,
            columns=[
                "name",
                "subject_id",
                "date",
                "id"
            ]
        )
        self.df = self.df_full.copy()
        
        # Sort by date if available
        if not self.df.empty and "date" in self.df.columns:
            self.df = self.df.sort_values(by="date", ascending=False)
        
        # Initialize filters
        self.text_filter = ""

    def get_postprocessed_streams(self, location):
        """Get the postprocessed folders for a given location."""
        # Get the bucket name and prefix
        bucket_name = location.split("/")[2]
        prefix = "/".join(location.split("/")[3:])

        paginator = s3_client.get_paginator('list_objects_v2')
        pages = paginator.paginate(Prefix=prefix, Bucket=bucket_name)
        posptrocessed_streams = []
        print(f"Looking for postprocessed streams in {bucket_name}/{prefix}")
        for page in pages:
            for item in page.get('Contents', []):
                key = item['Key']
                if "postprocessed" in key and "postprocessed-sorting" not in key:
                    stream_name = key[key.find("postprocessed"):].split("/")[1]
                    if stream_name not in posptrocessed_streams:
                        posptrocessed_streams.append(stream_name)
        return posptrocessed_streams

    def df_filtered(self):
        """Filter the options dataframe."""
        print(f"Filtering records for: {self.text_filter}")
        if self.text_filter == "":
            return self.df
        
        # Search for records matching the text filter
        try:
            print(f"Searching records for: {self.text_filter}")
            # Make sure we're returning a DataFrame, not a Series
            mask = self.df_full['name'].str.contains(self.text_filter, case=False)
            df_filtered = self.df_full[mask]
            return df_filtered
        except Exception as e:
            print(f"Error searching records: {e}")
            # Return a sample search result to show the interface works
            return pd.DataFrame(columns=self.df.columns)
    
    def df_textinput(self, value):
        """Filter the dataframe based on the text input."""
        self.text_filter = value

class SearchView(param.Parameterized):
    """Filtered view based on the search options."""
    
    text_filter = param.String(default="")
    
    def __init__(self, **params):
        """Initialize the search view."""
        super().__init__(**params)
    
    def df_filtered(self):
        """Filter the options dataframe."""
        if self.text_filter == "":
            return options.df
        
        df_filtered = options.df_filtered()
        return df_filtered
    
    def df_textinput(self, value):
        """Filter the dataframe based on the text input."""
        self.text_filter = value
        options.df_textinput(value)

# Initialize options
options = SearchOptions()

# Initialize search view
searchview = SearchView()

# Create the search input widget
text_input = pn.widgets.TextInput(
    name="Search",
    placeholder="Enter search terms...",
    sizing_mode="stretch_width",
)

# Connect the search input to the search view
def handle_text_input(event):
    searchview.df_textinput(event.new)

text_input.param.watch(handle_text_input, "value")

def get_search_results():
    """Get the current search results as a DataFrame."""
    return searchview.df_filtered()

def get_search_input():
    """Get the search input widget."""
    return text_input
