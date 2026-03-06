import ctypes
import json
import psutil
import param
import time
import gc
from copy import deepcopy

import panel as pn

pn.extension("tabulator", "gridstack")


from spikeinterface_gui import run_mainwindow

import spikeinterface as si
from spikeinterface.core.core_tools import extractor_dict_iterator, set_value_in_extractor_dict
from spikeinterface.curation import validate_curation_dict

from aind_ephys_portal.panel.logging import setup_logging, local_log_context
from aind_ephys_portal.panel.utils import PostMessageListener


displayed_unit_properties = [
    "decoder_label",
    "default_qc",
    "firing_rate",
    "y",
    "snr",
    "amplitude_median",
    "isi_violation_ratio",
]
default_curation_dict = {
    "format_version": "2",
    "label_definitions": {
        "quality": {
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
    zone1=["curation", "spikelist"],
    zone2=["unitlist", "merge"],
    zone3=["spikeamplitude", "amplitudescalings", "spikedepth", "spikerate", "trace", "tracemap"],
    zone4=[],
    zone5=["probe"],
    zone6=["ndscatter", "similarity"],
    zone7=["waveform"],
    zone8=["correlogram", "metrics", "mainsettings"],
)

def _malloc_trim():
    """Force glibc to return freed memory to the OS (Linux only)."""
    try:
        ctypes.CDLL("libc.so.6").malloc_trim(0)
    except Exception:
        pass


class EphysGuiView(param.Parameterized):

    def __init__(self, analyzer_path, recording_path, identifier=None, fast_mode=False, preload_curation=False, **params):
        """Construct the QCPanel object"""
        super().__init__(**params)

        setup_logging()

        self.analyzer_path = analyzer_path
        self.recording_path = recording_path
        if identifier is not None and identifier == "":
            identifier = None
        self.identifier = identifier
        self.fast_mode = fast_mode
        self.preload_curation = preload_curation
        self.analyzer = None
        self._init_cb = None

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

    def create_post_message_listener(self):
        if self.identifier is not None:
            listener = PostMessageListener()
            listener.on_msg(self._set_curation_data_from_message)
        else:
            listener = None
        return listener

    def create_submit_trigger(self):
        submit_trigger = pn.widgets.TextInput(value="", visible=False)
        # Add JavaScript callback that triggers when the TextInput value changes
        submit_trigger.jscallback(
            value="""
            // Extract just the JSON data (remove timestamp suffix)
            const dataStr = cb_obj.value;

            if (dataStr && dataStr.length > 0) {{
                try {{
                    const data = JSON.parse(dataStr);
                    console.log('Sending data to parent:', data);
                    parent.postMessage({{
                            type: 'curation-data',
                            identifier: '{identifier}',
                            data: data
                        }},
                    '*');
                    console.log('Data sent successfully to parent window');
                }} catch (error) {{
                    console.error('Error sending data to parent:', error);
                }}
            }}
            """.format(identifier=self.identifier)
        )
        return submit_trigger


    def _curation_callback(self, curation_data):
        self.submit_trigger.value = json.dumps(curation_data)

    def _set_curation_data_from_message(self, event):
        """
        Handler for PostMessageListener.on_msg.

        event.data is whatever the JS side passed to model.send_msg(...).
        Expected shape:
        {
            "payload": {"type": "curation-data", "identifier": "<identifier>", "data": <curation_dict>},
        }
        """
        msg = event.data
        payload = (msg or {}).get("payload", {})
        identifier = payload.get("identifier", None)
        if identifier != self.identifier:
            print(f"Received message for identifier {identifier}, but current identifier is {self.identifier}. Ignoring.")
            return

        data_type = payload.get("type", None)
        if data_type != "curation-data":
            print(f"Received message with type {data_type}, but expected 'curation-data'. Ignoring.")
            return

        print(f"Received curation message!")

        curation_data = payload.get("data", None)

        # Optional: validate basic structure
        if not isinstance(curation_data, dict):
            print("Invalid curation_data type:", type(curation_data), curation_data)
            return
        self.sigui_win.set_external_curation(curation_data)

    def _initialize(self):
        self.layout[0] = self.loading_banner
        self.log_output.value = ""

        initial_mem = psutil.virtual_memory()
        total_ram = initial_mem.total / (1024**3)
        current_ram_usage = initial_mem.used / (1024**3)
        available_ram = initial_mem.available / (1024**3)
        print(f"\nRAM Usage before initialization:")
        print(
            f"\tUsed: {current_ram_usage:.2f}/{total_ram:.2f} GB\n\tAvailable: {available_ram:.2f}/{total_ram:.2f} GB\n"
        )
        with local_log_context(self.log_output):
            error = None
            if self.analyzer_path != "":
                try:
                    t_start = time.perf_counter()
                    print(f"Initializing Ephys GUI")

                    print(f"\nLoading with the following paths:")
                    print(f"Analyzer path:\n{self.analyzer_path}\nRecording path:\n{self.recording_path}")
                    self._initialize_analyzer()
                    if self.recording_path != "":
                        self._set_processed_recording()

                    if self.identifier is not None:
                        print(f"\nSetting up bi-directional communication with identifier: {self.identifier}")
                        # Add custom curation callback to send data to parent window
                        self.submit_trigger = self.create_submit_trigger()
                        # Add postMessage listener to receive data from parent window
                        self.listener = self.create_post_message_listener()

                    self.win_layout = self._create_main_window()
                    self.layout[0] = self.win_layout
                    if self.identifier is not None:
                        self.layout.append(self.submit_trigger)
                        self.layout.append(self.listener)

                    print("\nEphys GUI initialized successfully!")
                    t_stop = time.perf_counter()
                    print(f"Initialization time: {t_stop - t_start:.2f} seconds")

                except Exception as e:
                    error = e
            else:
                print("Analyzer path is empty. Please provide a valid path.")

            if error is not None:
                print(f"Error during initialization: {error}")
                self.layout[0] = pn.pane.Markdown(f"⚠️ Error during initialization: {error}", sizing_mode="stretch_both")
            else:
                final_mem = psutil.virtual_memory()
                final_ram_usage = final_mem.used / (1024**3)
                final_ram_available = final_mem.available / (1024**3)
                print(f"\nRAM Usage after initialization:")
                print(
                    f"\tUsed: {final_ram_usage:.2f}/{total_ram:.2f} GB\n\tAvailable: {final_ram_available:.2f}/{total_ram:.2f} GB\n"
                )

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
            if self.preload_curation:
                curation_dict = deepcopy(default_curation_dict)
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
            else:
                curation_dict = None

            if self.fast_mode:
                skip_extensions = ["waveforms", "principal_components"]
            else:
                skip_extensions = None

            curation_callback = self._curation_callback if self.identifier is not None else None

            win = run_mainwindow(
                analyzer=self.analyzer,
                curation=True,
                displayed_unit_properties=displayed_unit_properties,
                curation_dict=curation_dict,
                mode="web",
                start_app=False,
                panel_window_servable=False,
                verbose=True,
                layout=aind_layout,
                skip_extensions=skip_extensions,
                curation_callback=curation_callback,
            )
            self.sigui_win = win
            return win.main_layout
        else:
            return pn.pane.Markdown(help_txt, sizing_mode="stretch_both")

    def cleanup(self):
        """Release resources when the session is closed."""
        print("Cleaning up Ephys GUI resources...")
        initial_mem = psutil.virtual_memory()
        total_ram = initial_mem.total / (1024**3)
        current_ram_usage = initial_mem.used / (1024**3)
        print(f"\nRAM Usage before cleanup: {current_ram_usage:.2f} / {total_ram:.2f} GB\n")

        # 1) Clear postMessage listener and submit trigger (they hold bound-method back-refs to self)
        self.listener = None
        self.submit_trigger = None

        # 2) Release GUI controller and all its data
        sigui_win = getattr(self, "sigui_win", None)
        if sigui_win is not None:
            controller = getattr(sigui_win, "controller", None)
            if controller is not None:
                # Clear views list — each view has param watchers holding back-refs
                for view in list(getattr(controller, "views", [])):
                    try:
                        view.settings._parameterized.param.unwatch_all()
                    except Exception:
                        pass
                controller.views = []
                # Clear PanelMainWindow's view dicts too
                sigui_win.views = {}
                sigui_win.view_layouts = {}
                # Explicitly drop all data cached on the controller.
                # Includes numpy arrays, extension objects (waveforms_ext, pc_ext hold
                # zarr array references), spike indices, and the units table.
                for attr in (
                    # template data
                    "templates_average", "templates_std",
                    # positions / geometry
                    "unit_positions", "visible_channel_inds",
                    # quality / metrics
                    "noise_levels", "metrics",
                    # spike-level arrays
                    "spike_amplitudes", "amplitude_scalings", "spike_depths",
                    "spikes", "random_spikes_indices", "segment_slices",
                    "final_spike_samples",
                    "_spike_index_by_units", "_spike_index_by_segment_and_units",
                    "_spike_visible_indices", "_spike_selected_indices",
                    # correlograms / ISI
                    "correlograms", "correlograms_bins",
                    "isi_histograms", "isi_bins",
                    # similarity
                    "_similarity_by_method",
                    # extension objects (hold zarr array refs — must clear before analyzer)
                    "waveforms_ext", "pc_ext", "_pc_projections",
                    # misc
                    "_extremum_channel", "_traces_cached", "units_table",
                    "_potential_merges",
                    # sparsity / signal handler
                    "external_sparsity", "analyzer_sparsity", "signal_handler",
                ):
                    try:
                        setattr(controller, attr, None)
                    except Exception:
                        pass
                controller.analyzer = None
                sigui_win.controller = None
            self.sigui_win = None

        self.win_layout = getattr(self, "win_layout", None) and None

        # 3) Clear the Panel layout children before releasing the layout reference.
        #    This unregisters the heavy GUI models from Bokeh's Document._all_models
        #    so they can be freed once the document is torn down.
        layout = getattr(self, "layout", None)
        if layout is not None:
            try:
                layout.clear()
            except Exception:
                pass
        self.layout = None

        # 4) Close zarr store and release the analyzer.
        #    Explicitly closing the store releases fsspec file handles and
        #    their associated S3 block/chunk caches before the Python GC runs.
        if getattr(self, "analyzer", None) is not None:
            # Invalidate recording zarr store cache if a recording is attached
            try:
                recording = getattr(self.analyzer, "recording", None)
                if recording is not None:
                    rec_zarr_root = getattr(recording, "_zarr_root", None)
                    if rec_zarr_root is not None:
                        rec_store = getattr(rec_zarr_root, "store", None)
                        if rec_store is not None:
                            rec_fs = getattr(rec_store, "fs", None)
                            if rec_fs is not None:
                                try:
                                    rec_fs.invalidate_cache()
                                except Exception:
                                    pass
                            try:
                                rec_store.close()
                            except Exception:
                                pass
                        print("Recording zarr store released.")
            except Exception as e:
                print(f"Warning: could not close recording zarr store: {e}")
            try:
                zarr_root = self.analyzer._get_zarr_root(mode="r")
                store = getattr(zarr_root, "store", None)
                if store is not None:
                    # Clear fsspec filesystem cache (dir listings + open handles)
                    fs = getattr(store, "fs", None)
                    if fs is not None:
                        try:
                            fs.invalidate_cache()
                        except Exception:
                            pass
                    try:
                        store.close()
                    except Exception:
                        pass
            except Exception as e:
                print(f"Warning: could not close zarr store: {e}")
            self.analyzer = None
            print("Analyzer resources released.")

        # 5) Clear remaining widget references
        if self._init_cb is not None:
            self._init_cb.stop()
            self._init_cb = None
        self.log_output = None
        self.spinner = None
        self.loading_banner = None

        # 6) Defer gc + malloc_trim until after the Bokeh document has finished
        #    releasing its own model references (Document._all_models is cleared
        #    after on_session_destroyed callbacks return, so gc.collect() here
        #    would be premature).
        try:
            from tornado.ioloop import IOLoop

            def _deferred_gc():
                gc.collect()
                gc.collect()
                _malloc_trim()
                final_mem = psutil.virtual_memory()
                used = final_mem.used / (1024**3)
                print(f"\nRAM Usage after deferred cleanup: {used:.2f} / {total_ram:.2f} GB\n")

            IOLoop.current().call_later(2.0, _deferred_gc)
            print("Deferred GC scheduled.")
        except Exception:
            # Fallback: run immediately if IOLoop is unavailable
            gc.collect()
            gc.collect()
            _malloc_trim()
            final_mem = psutil.virtual_memory()
            used = final_mem.used / (1024**3)
            print(f"\nRAM Usage after cleanup: {used:.2f} / {total_ram:.2f} GB\n")


    def panel(self):
        """Return the panel layout"""
        return self.layout
