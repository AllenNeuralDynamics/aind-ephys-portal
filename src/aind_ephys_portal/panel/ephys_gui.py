import sys
import param
import boto3
import time
from copy import deepcopy

import panel as pn

pn.extension("tabulator", "gridstack")

from aind_ephys_portal.docdb.database import get_name_from_id, get_asset_by_name, get_raw_asset_by_name

from spikeinterface_gui import run_mainwindow
import spikeinterface as si
from spikeinterface.core.core_tools import extractor_dict_iterator, set_value_in_extractor_dict

from .utils import Tee


displayed_unit_properties = ["decoder_label", "default_qc", "firing_rate", "y", "snr", "amplitude_median", "isi_violation_ratio"]
default_curation_dict = {
    "label_definitions": {
        "quality":{
            "label_options": ["good", "MUA", "noise"],
            "exclusive": True,
        }, 
    },
    "manual_labels": [],
    "merge_unit_groups": [],
    "removed_units": [],
}

from spikeinterface_gui.layout_presets import _presets

aind_layout = dict(
    zone1=['unitlist', 'curation', 'mergelist', 'spikelist'],
    zone2=[],
    zone3=['spikeamplitude', 'spikedepth', 'trace', 'tracemap'],
    zone4=[],
    zone5=['probe'],
    zone6=['ndscatter', 'similarity'],
    zone7=['waveform'],
    zone8=['correlogram'],
)
_presets['aind'] = aind_layout


class EphysGuiView(param.Parameterized):

    def __init__(self, analyzer_path, recording_path, **params):
        """Construct the QCPanel object"""
        super().__init__(**params)

        # Setup minimal record information from DocDB
        self.analyzer_path = analyzer_path
        self.recording_path = recording_path
        self.analyzer = None

        # Create initial layout
        self.layout = pn.Column(
            pn.Row(
                pn.widgets.TextInput(
                    name="Analyzer path", value=self.analyzer_path, height=50, sizing_mode="stretch_width"
                ),
                pn.widgets.TextInput(
                    name="Recording path (optional)", value=self.recording_path, height=50, sizing_mode="stretch_width"
                ),
                pn.widgets.Button(name="Launch!", button_type="primary", height=50, sizing_mode="stretch_width"),
                sizing_mode="stretch_width",
            ),
            self._create_main_window(),
        )

        # Store widget references
        self.analyzer_input = self.layout[0][0]
        self.recording_input = self.layout[0][1]
        self.launch_button = self.layout[0][2]

        # Setup event handlers
        self.analyzer_input.param.watch(self.update_values, "value")
        self.recording_input.param.watch(self.update_values, "value")
        self.launch_button.on_click(self.on_click)

    def _initialize(self):
        if self.analyzer_input.value != "":
            t_start = time.perf_counter()
            spinner = pn.indicators.LoadingSpinner(value=True, sizing_mode="stretch_width")
            # Create a TextArea widget to display logs
            log_output = pn.widgets.TextAreaInput(value="", sizing_mode="stretch_both")

            original_stdout = sys.stdout
            sys.stdout = Tee(original_stdout, log_output)  # Redirect stdout

            original_stderr = sys.stderr
            sys.stderr = Tee(original_stderr, log_output)  # Redirect stderr

            self.layout[1] = pn.Row(spinner, log_output)

            print(
                f"Initializing Ephys GUI for:\nAnalyzer path: {self.analyzer_path}\nRecording path: {self.recording_path}"
            )

            self._initialize_analyzer()
            if self.recording_path != "":
                self._set_processed_recording()
            self.win = self._create_main_window()
            self.layout[1] = self.win
            print("Ephys GUI initialized successfully!")
            t_stop = time.perf_counter()
            print(f"Initialization time: {t_stop - t_start:.2f} seconds")
            sys.stdout = sys.__stdout__  # Reset stdout
            sys.stderr = sys.__stderr__  # Reset stderr

    def _initialize_analyzer(self):
        if not self.analyzer_path.endswith((".zarr", ".zarr/")):
            raise ValueError("Only Zarr files are supported for now.")
        print(f"Loading analyzer from {self.analyzer_path}...")
        self.analyzer = si.load(self.analyzer_path, load_extensions=False)
        print(f"Analyzer loaded: {self.analyzer}")

    def _set_processed_recording(self):
        print(f"Loading processed recording from {self.recording_path}")
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
        set_value_in_extractor_dict(recording_dict, access_path, self.recording_path)
        recording_processed = si.load(recording_dict)
        print(f"Processed recording loaded: {recording_processed}")
        self.analyzer.set_temporary_recording(recording_processed)

    def _check_if_s3_folder_exists(self, location):
        bucket_name = location.split("/")[2]
        prefix = "/".join(location.split("/")[3:])
        try:
            s3 = boto3.client("s3")
            response = s3.list_objects_v2(Bucket=bucket_name, Prefix=prefix, MaxKeys=1)
            return "Contents" in response
        except Exception as e:
            return False

    def _create_main_window(self):
        if self.analyzer is not None:
            # prepare the curation data using decoder labels
            curation_dict = deepcopy(default_curation_dict)
            curation_dict["unit_ids"] = self.analyzer.unit_ids
            if "decoder_label" in self.analyzer.sorting.get_property_keys():
                decoder_labels = self.analyzer.get_sorting_property("decoder_label")
                noise_units = self.analyzer.unit_ids[decoder_labels == "noise"]
                curation_dict["removed_units"] = list(noise_units)
                for unit_id in noise_units:
                    curation_dict["manual_labels"].append({"unit_id": unit_id, "quality": ["noise"]})

            win = run_mainwindow(
                analyzer=self.analyzer,
                curation=True,
                skip_extensions=["waveforms"],
                displayed_unit_properties=displayed_unit_properties,
                curation_dict=curation_dict,
                mode="web",
                start_app=False,
                make_servable=False,
                verbose=True,
                layout_preset="aind"
            )
            return win.main_layout
        else:
            return pn.pane.Markdown("Analyzer not initialized")

    def update_values(self, event):
        self.analyzer_path = self.analyzer_input.value
        self.recording_path = self.recording_input.value
        self._initialize()

    def on_click(self, event):
        print("Launching SpikeInterface GUI!")
        self._initialize()

    def panel(self):
        """Return the panel layout"""
        return self.layout
