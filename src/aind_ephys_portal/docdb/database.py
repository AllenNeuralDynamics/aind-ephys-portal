"""Database access functions for the AIND SIGUI Portal."""

import os
from typing import List, Dict, Any

import panel as pn
from aind_data_access_api.document_db import MetadataDbClient


TEST_ENV = os.environ.get("TEST_ENV", "0") == "1"

# Constants for database connection
default_api_gateway_host = "api.allenneuraldynamics-test.org" if TEST_ENV else "api.allenneuraldynamics.org"
API_GATEWAY_HOST = os.environ.get("API_GATEWAY_HOST", default_api_gateway_host)
DATABASE = os.environ.get("DATABASE", "metadata_index")
COLLECTION = os.environ.get("COLLECTION", "data_assets")

# Timeouts
TIMEOUT_1H = 60 * 60

# Initialize the client
client_v1 = MetadataDbClient(
    host=API_GATEWAY_HOST,
    database=DATABASE,
    collection=COLLECTION,
    version="v1",
)

client_v2 = MetadataDbClient(
    host=API_GATEWAY_HOST,
    database=DATABASE,
    collection=COLLECTION,
    version="v2",
)


@pn.cache()
def get_name_from_id(id: str, version: str = "v2") -> str:
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
    client = client_v1 if version == "v1" else client_v2
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
def get_raw_asset_by_name(asset_name: str, version: str = "v2"):
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
    client = client_v1 if version == "v1" else client_v2
    response = client.retrieve_docdb_records(
        filter_query={"name": {"$regex": raw_name, "$options": "i"}, "data_description.data_level": "raw"}, limit=0
    )
    return response


@pn.cache(ttl=TIMEOUT_1H)
def get_all_ecephys_derived(additional_includes_in_name: str | None = None, version: str = "v2") -> List[Dict[str, Any]]:
    """Get a limited set of all records from the database.

    Returns
    -------
    list[dict]
        List of records, limited to 50 entries.
    additional_includes_in_name : str, optional
        Comma-separated list of additional fields to include in the results, by default None
    """
    filter_query = {"data_description.modality.abbreviation": "ecephys", "data_description.data_level": "derived"}
    client = client_v1 if version == "v1" else client_v2
    responses = client.retrieve_docdb_records(
        filter_query=filter_query,
    )
    responses_filt = []
    if additional_includes_in_name:
        additional_fields = [field.strip() for field in additional_includes_in_name.split(",")]
        for record in responses:
            for field in additional_fields:
                if field in record["name"]:
                    responses_filt.append(record)
    else:
        responses_filt = responses
    return responses_filt
