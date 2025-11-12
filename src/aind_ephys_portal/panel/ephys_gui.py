import sys
import param
import boto3
import time

import panel as pn

pn.extension("tabulator", "gridstack")

from aind_ephys_portal.docdb.database import get_name_from_id, get_asset_by_name, get_raw_asset_by_name

from spikeinterface_gui import run_mainwindow
from spikeinterface_gui.launcher import instantiate_analyzer_and_recording

import spikeinterface as si
from spikeinterface.core.core_tools import extractor_dict_iterator, set_value_in_extractor_dict
from spikeinterface.curation import validate_curation_dict
from spikeinterface_gui.curation_tools import empty_curation_data, default_label_definitions

from .utils import Tee


displayed_unit_properties = ["decoder_label", "default_qc", "firing_rate", "y", "snr", "amplitude_median", "isi_violation_ratio"]
default_curation_dict = {
    "format_version": "2",
    "label_definitions": {
        "quality":{
            "label_options": ["good", "MUA", "noise"],
            "exclusive": True,
        }, 
    },
    "manual_labels": [],
    "removed": [],
    "merges": [],
    "splits": [],
}

help_txt = """
## Usage
Sorting Analyzer not loaded. Follow the steps below to launch the SpikeInterface GUI:
1. Enter the path to the SpikeInterface analyzer Zarr file.
2. (Optional) Enter the path to the processed recording folder.
3. Click "Launch!" to start the SpikeInterface GUI.
"""

# Define the layout for the AIND Ephys GUI
aind_layout = dict(
    zone1=["unitlist", "curation", "merge", "spikelist"],
    zone2=[],
    zone3=["spikeamplitude", "spikedepth", "spikerate", "trace", "tracemap"],
    zone4=[],
    zone5=["probe"],
    zone6=["ndscatter", "similarity"],
    zone7=["waveform", "waveformheatmap"],
    zone8=["correlogram", "metrics", "mainsettings"],
)


class EphysGuiView(param.Parameterized):

    def __init__(self, analyzer_path, recording_path, **params):
        """Construct the QCPanel object"""
        super().__init__(**params)

        # Setup minimal record information from DocDB
        self.analyzer_path = analyzer_path
        self.recording_path = recording_path
        self.analyzer = None

        self.analyzer_input = pn.widgets.TextInput(
            name="Analyzer path", value=self.analyzer_path, height=50, sizing_mode="stretch_width"
        )
        self.recording_input = pn.widgets.TextInput(
            name="Recording path (optional)", value=self.recording_path, height=50, sizing_mode="stretch_width"
        )
        self.launch_button = pn.widgets.Button(
            name="Launch!", button_type="primary", height=50, sizing_mode="stretch_width"
        )

        self.spinner = pn.indicators.LoadingSpinner(value=True, sizing_mode="stretch_width")
        self.log_output_text = pn.widgets.TextAreaInput(value="", sizing_mode="stretch_both")
        clear_log_button = pn.widgets.Button(name="Clear Log", button_type="warning", sizing_mode="stretch_width")
        clear_log_button.on_click(self._clear_log)
        self.log_output = pn.Column(self.log_output_text, clear_log_button, sizing_mode="stretch_both")

        original_stdout = sys.stdout
        sys.stdout = Tee(original_stdout, self.log_output_text)
        original_stderr = sys.stderr
        sys.stderr = Tee(original_stderr, self.log_output_text)

        self.loading_banner = pn.Row(self.spinner, self.log_output, sizing_mode="stretch_both")

        self.top_panel = pn.Row(
            self.analyzer_input,
            self.recording_input,
            self.launch_button,
            sizing_mode="stretch_width",
        )

        # Create initial layout
        self.layout = pn.Column(
            self.top_panel,
            self._create_main_window(),
            sizing_mode="stretch_both",
        )

        # Setup event handlers
        self.analyzer_input.param.watch(self.update_values, "value")
        self.recording_input.param.watch(self.update_values, "value")
        self.launch_button.on_click(self.on_click)

        if self.analyzer_path != "":
            # # # Schedule initialization to run after UI is rendered
            def delayed_init():
                self._initialize()
                return False  # Don't repeat the callback
            pn.state.add_periodic_callback(delayed_init, period=1500, count=1)

    def _initialize(self):
        self.layout[1] = self.loading_banner
        self.log_output_text.value = ""
        if self.analyzer_input.value != "":
            t_start = time.perf_counter()
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
        else:
            print("Analyzer path is empty. Please provide a valid path.")

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

    def _create_main_window(self):
        if self.analyzer is not None:
            # prepare the curation data using decoder labels
            curation_dict = default_curation_dict
            curation_dict["unit_ids"] = self.analyzer.unit_ids
            if "decoder_label" in self.analyzer.sorting.get_property_keys():
                decoder_labels = self.analyzer.get_sorting_property("decoder_label")
                noise_units = self.analyzer.unit_ids[decoder_labels == "noise"]
                curation_dict["removed"] = list(noise_units)
                for unit_id in noise_units:
                    curation_dict["manual_labels"].append({"unit_id": unit_id, "quality": ["noise"]})

            try:
                validate_curation_dict(curation_dict)
            except ValueError as e:
                print(f"Curated dictionary is invalid: {e}")
                curation_dict = None

            win = run_mainwindow(
                analyzer=self.analyzer,
                curation=True,
                displayed_unit_properties=displayed_unit_properties,
                curation_dict=curation_dict,
                mode="web",
                start_app=False,
                panel_window_servable=False,
                verbose=True,
                layout=aind_layout
            )
            self.log_output.value = ""
            tabs = pn.Tabs(
                ("GUI", win.main_layout),
                ("Log", self.log_output),
                tabs_location="below",
                sizing_mode="stretch_both",
            )
            return tabs
        else:
            return pn.pane.Markdown(help_txt, sizing_mode="stretch_both")

    def update_values(self, event):
        self.analyzer_path = self.analyzer_input.value
        self.recording_path = self.recording_input.value
        self._initialize()

    def _clear_log(self, event):
        self.log_output_text.value = ""

    def on_click(self, event):
        print("Launching SpikeInterface GUI!")
        self._initialize()

    def panel(self):
        """Return the panel layout"""
        return self.layout
