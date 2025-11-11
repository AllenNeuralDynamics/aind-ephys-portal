import sys
import param
import boto3
import time

import panel as pn

pn.extension("tabulator", "gridstack")

import spikeinterface as si
from spikeinterface.curation import validate_curation_dict
from spikeinterface.core.core_tools import extractor_dict_iterator, set_value_in_extractor_dict
from spikeinterface_gui.curation_tools import empty_curation_data, default_label_definitions

from .utils import Tee


displayed_unit_properties = [
    "decoder_label",
    "default_qc",
    "firing_rate",
    "y",
    "snr",
    "amplitude_median",
    "isi_violation_ratio",
]
default_curation_dict = empty_curation_data.copy()
default_curation_dict["label_definitions"] = default_label_definitions


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

help_txt = """
## Usage

Sorting Analyzer not loaded. Follow the steps below to launch the SpikeInterface GUI:

1. Enter the path to the SpikeInterface analyzer Zarr file.
2. (Optional) Enter the path to the processed recording folder.
3. Click "Launch!" to start the SpikeInterface GUI.
"""


class EphysGuiView(param.Parameterized):

    refresh = param.Event()

    def __init__(self, analyzer_path, recording_path, launch=True, **params):
        """Construct the QCPanel object"""
        super().__init__(**params)

        # Setup minimal record information from DocDB
        self.analyzer_path = analyzer_path
        self.recording_path = recording_path
        self.analyzer = None
        self.launch = launch

        self.analyzer_input = pn.widgets.TextInput(
            name="Analyzer path", value=self.analyzer_path, height=50, sizing_mode="stretch_width"
        )
        self.recording_input = pn.widgets.TextInput(
            name="Recording path (optional)", value=self.recording_path, height=50, sizing_mode="stretch_width"
        )
        self.launch_button = pn.widgets.Button(
            name="Launch!", button_type="primary", height=50, sizing_mode="stretch_width"
        )

        # Create initial layout
        self.top_panel = pn.Row(
            self.analyzer_input,
            self.recording_input,
            self.launch_button,
            sizing_mode="stretch_width",
        )
        help_pane = pn.pane.Markdown(
            help_txt,
            sizing_mode="stretch_both",
        )
        # initialize with gridstack with same layout as GUI!
        self.gui_tab = pn.Column(sizing_mode="stretch_both")

        log_output = pn.widgets.TextAreaInput(value="", sizing_mode="stretch_both")
        original_stdout = sys.stdout
        original_stderr = sys.stderr
        sys.stdout = Tee(original_stdout, log_output)
        sys.stderr = Tee(original_stderr, log_output)

        self.log_tab = pn.Row(help_pane, log_output)

        self.tabs = pn.Tabs(
            ("GUI", self.gui_tab),
            ("Log", self.log_tab),
            tabs_location="below",
            sizing_mode="stretch_both",
        )

        self.tabs.active = 1  # Set default tab to Log

        self.layout = pn.Column(
            self.top_panel,
            self.tabs,
        )

        # Setup event handlers
        self.analyzer_input.param.watch(self.update_values, "value")
        self.recording_input.param.watch(self.update_values, "value")
        self.launch_button.on_click(self.on_click)
        if self.launch and self.analyzer_path != "":
            # # # Schedule initialization to run after UI is rendered
            def delayed_init():
                self._initialize()
                return False  # Don't repeat the callback

            # # Add a short delay to let the UI render
            # pn.state.add_periodic_callback(delayed_init, period=500, count=1)
            self._initialize()
            # pn.state.execute(self._initialize_async)
            # self._initialize()

    def _initialize(self):
        # Show loading UI
        self.tabs.active = 1  # Switch to log tab
        # spinner = pn.indicators.LoadingSpinner(value=True, sizing_mode="stretch_width")
        # log_output = pn.widgets.TextAreaInput(value="", sizing_mode="stretch_both")
        # self.layout[1] = pn.Row(spinner, log_output)

        # # Redirect stdout/stderr
        # original_stdout = sys.stdout
        # original_stderr = sys.stderr
        # sys.stdout = Tee(original_stdout, log_output)
        # sys.stderr = Tee(original_stderr, log_output)
        t_start = time.perf_counter()
        print(
            f"Initializing Ephys GUI for:\nAnalyzer path: {self.analyzer_path}\nRecording path: {self.recording_path}"
        )
        self._initialize_analyzer()
        if self.recording_path != "":
            self._set_processed_recording()
        self.sigui = self._create_main_window()

        # # # Restore stdout/stderr
        # sys.stdout = original_stdout
        # sys.stderr = original_stderr

        # if self.win is not None:
        t_stop = time.perf_counter()
        print(f"Ephys GUI initialized in time: {t_stop - t_start:.2f} seconds")
        # self.tabs.objects = [
        #     self.sigui.main_layout,
        #     self.log_tab
        # ]
        self.tabs[0].clear()
        self.tabs[0].append(self.sigui.main_layout)
        # self.gui_tab.clear()
        # self.gui_tab.append(self.sigui.main_layout)
        # time.sleep(1)  # Give time for the tab to update
        self.tabs.active = 0  # Switch back to GUI tab
        # trigger a refresh
        # self.sigui.refresh_all_views()

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
            from spikeinterface_gui import run_mainwindow

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
                verbose=True,
                layout=aind_layout,
                disable_save_settings_button=True,
                start_app=False,
                panel_window_servable=False,
            )

            # Ensure the layout is not marked as servable
            return win
        else:
            return None

    def update_values(self, event):
        self.analyzer_path = self.analyzer_input.value
        self.recording_path = self.recording_input.value
        # self._initialize()

    def on_click(self, event):
        # with self.loading_context():
        print("Launching SpikeInterface GUI!")
        self._initialize()
        # pn.state.execute(self._initialize)
        self.param.trigger("refresh")
        self.sigui.refresh_all_views()

    def panel(self):
        """Return the panel layout"""
        return self.layout
