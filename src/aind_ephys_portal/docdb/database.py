"""Database access functions for the AIND SIGUI Portal."""

import os
from typing import List, Dict, Any

import panel as pn
from aind_data_access_api.document_db import MetadataDbClient

# Constants for database connection
API_GATEWAY_HOST = os.environ.get("API_GATEWAY_HOST", "api.allenneuraldynamics.org")
DATABASE = os.environ.get("DATABASE", "metadata_index")
COLLECTION = os.environ.get("COLLECTION", "data_assets")

# Timeouts
TIMEOUT_1M = 60
TIMEOUT_1H = 60 * 60
TIMEOUT_24H = 60 * 60 * 24

# Initialize the client
client = MetadataDbClient(
    host=API_GATEWAY_HOST,
    database=DATABASE,
    collection=COLLECTION,
)


@pn.cache()
def get_name_from_id(id: str):
    """Get the name field from a record with the given ID.

    Parameters
    ----------
    id : str
        The unique identifier of the record.

    Returns
    -------
    str
        The name field from the record.
    """
    response = client.aggregate_docdb_records(pipeline=[{"$match": {"_id": id}}, {"$project": {"name": 1, "_id": 0}}])
    return response[0]["name"]


@pn.cache()
def _raw_name_from_derived(s):
    """Returns just the raw asset name from an asset that is derived, i.e. has >= 4 underscores

    Parameters
    ----------
    s : str
        Raw or derived asset name

    Returns
    -------
    str
        Raw asset name, split off from full name
    """
    if s.count("_") >= 4:
        parts = s.split("_", 4)
        return "_".join(parts[:4])
    return s


@pn.cache(ttl=TIMEOUT_1H)
def get_asset_by_name(asset_name: str):
    """Get all assets that match a given asset name pattern.

    Parameters
    ----------
    asset_name : str
        The asset name to search for (will be converted to raw name if derived).

    Returns
    -------
    list[dict]
        List of matching asset records.
    """
    response = client.retrieve_docdb_records(filter_query={"name": {"$regex": asset_name, "$options": "i"}}, limit=0)
    return response

@pn.cache(ttl=TIMEOUT_1H)
def get_raw_asset_by_name(asset_name: str):
    """Get all assets that match a given asset name pattern.

    Parameters
    ----------
    asset_name : str
        The asset name to search for (will be converted to raw name if derived).

    Returns
    -------
    list[dict]
        List of matching asset records.
    """
    raw_name = _raw_name_from_derived(asset_name)
    response = client.retrieve_docdb_records(filter_query={"name": {"$regex": raw_name, "$options": "i"},
                                                           "data_description.data_level": "raw"}, limit=0)
    return response


@pn.cache(ttl=TIMEOUT_1H)
def get_all_ecephys_derived() -> List[Dict[str, Any]]:
    """Get a limited set of all records from the database.
    
    Returns
    -------
    list[dict]
        List of records, limited to 50 entries.
    """
    filter_query = {"data_description.modality.abbreviation": "ecephys", 
                    "data_description.data_level": "derived"}
    response = client.retrieve_docdb_records(
        filter_query=filter_query,
    )
    return response
