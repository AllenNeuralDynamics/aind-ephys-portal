import panel as pn
import param
import boto3

from aind_sigui_portal.docdb.database import get_name_from_id, get_asset_by_name, get_raw_asset_by_name

from spikeinterface_gui.backends.panel import PanelMainWindow
import spikeinterface as si
from spikeinterface.core.core_tools import extractor_dict_iterator, set_value_in_extractor_dict, _get_paths_list

pn.extension("bokeh")

class SIGuiView(param.Parameterized):

    def __init__(self, id, stream_name, load_recording=True, **params):
        """Construct the QCPanel object"""
        super().__init__(**params)

        # Setup minimal record information from DocDB
        self.id = id
        self.stream_name = stream_name

        asset_name = get_name_from_id(self.id)
        self.derived_asset = get_asset_by_name(asset_name)[0]
        print("Derived location:", self.derived_asset["location"])
        self.raw_asset = get_raw_asset_by_name(asset_name)[0]
        print("Raw location:", self.raw_asset["location"])

        # Initialize analyzer
        self._initialize_analyzer()
        if load_recording:
            self._set_processed_recording()

    def _initialize_analyzer(self):
        if not self.stream_name.endswith(".zarr"):
            raise ValueError("Only Zarr files are supported for now.")
        self.path = f"{self.derived_asset['location']}/postprocessed/{self.stream_name}"
        print(f"Loading analyzer from {self.path}")
        self.analyzer = si.load(self.path, load_extensions=False)
        print(self.analyzer)

    def _set_processed_recording(self):
        raw_stream_name = self.stream_name[:self.stream_name.find("_recording")]
        self.raw_path = f"{self.raw_asset['location']}/ecephys/ecephys_compressed/{raw_stream_name}.zarr"
        
        # TODO: handle this later
        # if not self._check_if_s3_folder_exists(self.raw_path):
        #     self.raw_path = f"{self.raw_asset['location']}/ecephys_compressed/{raw_stream_name}.zarr"
        print(f"Loading processed recording from {self.raw_path}")
        analyzer_root = self.analyzer._get_zarr_root(mode="r")
        recording_root = analyzer_root["recording"]
        recording_dict = recording_root[0]
        # Remap path and set relative to to false
        recording_dict["relative_paths"] = False
        # update_key(recording_dict, "relative_paths", False)
        path_list_iter = extractor_dict_iterator(recording_dict)
        for path_iter in path_list_iter:
            if "folder_path" in path_iter.name:
                access_path = path_iter.access_path
                break
        set_value_in_extractor_dict(recording_dict, access_path, self.raw_path)
        path_list = _get_paths_list(recording_dict)
        recording_processed = si.load(recording_dict)
        print(recording_processed)
        self.analyzer.set_temporary_recording(recording_processed)

    def _check_if_s3_folder_exists(self, location):
        bucket_name = location.split("/")[2]
        prefix = "/".join(location.split("/")[3:])
        try:
            s3 = boto3.client('s3')
            response = s3.list_objects_v2(Bucket=bucket_name, Prefix=prefix, MaxKeys=1)
            return 'Contents' in response
        except Exception as e:
            return False

    def panel(self):
        return PanelMainWindow(
            analyzer=self.analyzer,
            verbose=True,
            curation=True
        ).show()


def update_key(d, target_key, new_value):
    """Recursively update all occurrences of target_key in a nested dictionary"""
    if isinstance(d, dict):
        for key in d:
            if key == target_key:
                d[key] = new_value
            else:
                update_key(d[key], target_key, new_value)  # Recursive call
    elif isinstance(d, list):
        for item in d:
            update_key(item, target_key, new_value)