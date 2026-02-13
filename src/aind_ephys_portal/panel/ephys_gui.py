import psutil
import param
import time
import gc
import ctypes

import panel as pn

pn.extension("tabulator", "gridstack")


from spikeinterface_gui import run_mainwindow
from spikeinterface_gui.launcher import instantiate_analyzer_and_recording

import spikeinterface as si
from spikeinterface.core.core_tools import extractor_dict_iterator, set_value_in_extractor_dict
from spikeinterface.curation import validate_curation_dict
from spikeinterface_gui.curation_tools import empty_curation_data, default_label_definitions

from aind_ephys_portal.panel.logging import setup_logging, local_log_context
from aind_ephys_portal.panel.utils import Tee


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
Sorting Analyzer not loaded. Embed the `analyzer_path` parameter in the URL 
(and optionally the `recording_path` parameter) to launch the GUI. For example:
ephys.allenneuraldymamics.org/ephys_gui_app?analyzer_path="/path/to/analyzer.zarr"&recording_path="/path/to/recording.zarr"
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

        setup_logging()

        self.analyzer_path = analyzer_path
        self.recording_path = recording_path
        self.analyzer = None
        self._cleanup_registered = False

        self.spinner = pn.indicators.LoadingSpinner(value=True, sizing_mode="stretch_width")
        self.log_output = pn.widgets.TextAreaInput(value="", sizing_mode="stretch_both")
        self.loading_banner = pn.Row(self.spinner, self.log_output, sizing_mode="stretch_both")

        self.win = None
        if self.analyzer_path != "":
            self.layout = pn.Column(
                self._create_main_window(),
                sizing_mode="stretch_both",
            )
            def delayed_init():
                self._initialize()
                return False
            self._init_cb = pn.state.add_periodic_callback(delayed_init, period=1500, count=1)
        else:
            self.layout = pn.Column(
                pn.pane.Markdown(help_txt, sizing_mode="stretch_both"),
                sizing_mode="stretch_both",
            )

    def _register_cleanup(self):
        """Register cleanup on the current document. Must be called from within the session."""
        if self._cleanup_registered:
            return
        doc = pn.state.curdoc
        if doc is not None and hasattr(doc, "on_session_destroyed"):
            def _on_destroy(session_context, view=self):
                view.cleanup()
            doc.on_session_destroyed(_on_destroy)
            self._cleanup_registered = True
            print(f"[GUI] Cleanup registered on doc {id(doc)}")

    def _initialize(self):
        # Register cleanup HERE — the document is now bound to this GUI session
        self._register_cleanup()

        self.layout[0] = self.loading_banner
        self.log_output.value = ""
        with local_log_context(self.log_output):
            error = None
            if self.analyzer_path != "":
                try:
                    t_start = time.perf_counter()
                    initial_mem = psutil.virtual_memory()
                    total_ram = initial_mem.total / (1024 ** 3)
                    current_ram_usage = initial_mem.used / (1024 ** 3)
                    print(f"Initializing Ephys GUI")
                    print(f"\nRAM Usage before initialization: {current_ram_usage:.2f} / {total_ram:.2f} GB\n")

                    print(f"\nLoading with the following paths:")
                    print(f"Analyzer path:\n{self.analyzer_path}\nRecording path:\n{self.recording_path}")
                    self._initialize_analyzer()
                    if self.recording_path != "":
                        self._set_processed_recording()
                    win = self._create_main_window()
                    self.layout[0] = win
                    print("\nEphys GUI initialized successfully!")
                    t_stop = time.perf_counter()
                    print(f"Initialization time: {t_stop - t_start:.2f} seconds")

                    final_mem = psutil.virtual_memory()
                    final_ram_usage = final_mem.used / (1024 ** 3)
                    print(f"\nRAM Usage after initialization: {final_ram_usage:.2f} / {total_ram:.2f} GB\n")
                except Exception as e:
                    error = e
            else:
                print("Analyzer path is empty. Please provide a valid path.")

            if error is not None:
                print(f"Error during initialization: {error}")
                self.layout[0] = pn.pane.Markdown(f"⚠️ Error during initialization: {error}", sizing_mode="stretch_both")

    def _initialize_analyzer(self):
        if not self.analyzer_path.endswith((".zarr", ".zarr/")):
            raise ValueError("Only Zarr files are supported for now.")
        print(f"Loading analyzer...")
        self.analyzer = si.load(self.analyzer_path, load_extensions=False)
        print(f"Analyzer loaded: {self.analyzer}")

    def _set_processed_recording(self):
        print(f"Loading processed recording...")
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
                # for testing
                skip_extensions=["waveforms", "principal_components"],
                panel_window_servable=False,
                verbose=True,
                layout=aind_layout
            )
            self.win = win
            return win.main_layout
        else:
            return pn.pane.Markdown(help_txt, sizing_mode="stretch_both")

    def cleanup(self):
        """Release resources when the session is closed."""
        print("Cleaning up Ephys GUI resources...")
        initial_mem = psutil.virtual_memory()
        total_ram = initial_mem.total / (1024 ** 3)
        current_ram_usage = initial_mem.used / (1024 ** 3)
        print(f"\nRAM Usage before cleanup: {current_ram_usage:.2f} / {total_ram:.2f} GB\n")

        # 1) Release GUI controller references
        if self.win is not None:
            del self.win

        # 2) Close zarr store explicitly
        if self.analyzer is not None:
            # Try to close the underlying zarr store
            zarr_root = getattr(self.analyzer, "sorting_analyzer", None) or self.analyzer
            store = getattr(zarr_root, "_root", None)
            if store is not None:
                inner_store = getattr(store, "store", None)
                if inner_store is not None and hasattr(inner_store, "close"):
                    inner_store.close()
                    print("Zarr store closed.")
            self.analyzer = None
            print("Analyzer resources released.")

        # 3) Clear layout references
        if self._init_cb is not None:
            self._init_cb.stop()
            self._init_cb = None
        self.layout = None
        self.log_output = None
        self.spinner = None
        self.loading_banner = None

        # 4) Force garbage collection (two passes for ref cycles)
        gc.collect()
        gc.collect()

        # 5) Force glibc to return freed memory to OS
        # try:
        #     ctypes.CDLL("libc.so.6").malloc_trim(0)
        #     print("malloc_trim: freed memory returned to OS.")
        # except Exception as e:
        #     print(f"malloc_trim failed: {e}")

        final_mem = psutil.virtual_memory()
        current_ram_usage = final_mem.used / (1024 ** 3)
        print(f"\nRAM Usage after cleanup: {current_ram_usage:.2f} / {total_ram:.2f} GB\n")


        # Debug: compare RSS vs OS-reported used
        import os
        process = psutil.Process(os.getpid())
        rss = process.memory_info().rss / 1024**2
        print(f"\nProcess RSS: {rss:.1f} MB")
        print(f"OS used (includes page cache): {psutil.virtual_memory().used / 1024**2:.1f} MB")
        print(f"OS available: {psutil.virtual_memory().available / 1024**2:.1f} MB")

    def panel(self):
        """Return the panel layout"""
        return self.layout
