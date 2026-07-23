import ctypes
import json
import os
import psutil
import param
import time
import gc
import warnings
from pathlib import Path
from copy import deepcopy

import panel as pn

pn.extension("tabulator", "gridstack")

# Silence sklearn's InconsistentVersionWarning during analyzer load. The
# warning itself is informational, but some upstream code in the
# spikeinterface / spikeinterface-gui stack constructs the warning class
# with a positional arg, which crashes because its __init__ is kwarg-only
# (`__init__() takes 1 positional argument but 2 were given`). Suppressing
# the warning prevents any reactive code path that re-emits it from firing.
# Belt-and-braces with the scikit-learn==1.8.0 pin in the Dockerfile, which
# avoids the version mismatch in the common case but doesn't help when
# loading older analyzers saved with sklearn < 1.8.0.
try:
    from sklearn.exceptions import InconsistentVersionWarning
    warnings.filterwarnings("ignore", category=InconsistentVersionWarning)
except ImportError:
    pass


from spikeinterface_gui import run_mainwindow

import spikeinterface as si
from spikeinterface.core.core_tools import extractor_dict_iterator, set_value_in_extractor_dict
from spikeinterface.core.zarrextractors import super_zarr_open
from spikeinterface.curation import validate_curation_dict

from aind_ephys_portal.session_logging import (
    setup_logging,
    local_log_context,
    can_admit_new_session,
    estimate_session_ram_bytes,
    get_hard_cap_sessions,
    get_per_session_estimate_pct,
    get_safe_max_ram_pct,
    list_gui_sessions,
    get_ecs_task_id,
    get_container_total_memory,
    get_container_used_memory,
    record_session_rejection,
    record_pending_load,
    clear_pending_load,
    record_admission,
    admission_cooldown_remaining,
    remove_session,
)
from aind_ephys_portal.panel.utils import PostMessageListener, FullscreenResizeHandler

# Admission is now decided dynamically by can_admit_new_session() in logging.py,
# which predicts post-admit RAM and rejects above SAFE_MAX_RAM_PCT or beyond
# HARD_CAP_SESSIONS. The old fixed MAX_RAM_PERCENT_FOR_NEW_SESSION constant has
# been removed — it is subsumed by SAFE_MAX_RAM_PCT - PER_SESSION_ESTIMATE_PCT.

displayed_unit_properties = [
    "unitrefine_label",
    "bombcell_label",
    "default_qc",
    "firing_rate",
    "y",
    "snr",
    "amplitude_median",
    "isi_violation_ratio",
    "decoder_label"
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


# Default OFF until we verify the refcount guard doesn't race with concurrent
# sessions that may grab a cached fsspec FS microseconds after we check. Flip
# via FSSPEC_DROP_INSTANCE_CACHE=1 once we have confidence.
_FSSPEC_DROP_INSTANCE_CACHE = os.environ.get("FSSPEC_DROP_INSTANCE_CACHE", "0").lower() in ("1", "true", "yes")


def _malloc_trim():
    """Force glibc to return freed memory to the OS (Linux only)."""
    try:
        ctypes.CDLL("libc.so.6").malloc_trim(0)
    except Exception:
        pass


def _clear_fsspec_instance_caches():
    """Drop cached fsspec filesystem instances and their internal block buffers.

    fsspec keeps every filesystem ever constructed in AbstractFileSystem._cache,
    so per-instance invalidate_cache() (dir listings) doesn't release the FS
    itself or its dircache/block buffers. We only drop instances with no other
    referrers to avoid stealing FS objects from concurrent sessions.
    """
    try:
        import sys
        from fsspec import AbstractFileSystem
    except Exception:
        return

    cache = getattr(AbstractFileSystem, "_cache", None)
    if not cache:
        return

    # 2 = the local var here + sys.getrefcount's own arg ref → no external holders.
    # If anything else has a handle, leave it alone.
    removed = 0
    for key in list(cache.keys()):
        fs = cache.get(key)
        if fs is None:
            continue
        if sys.getrefcount(fs) <= 3:  # cache dict + local + getrefcount arg
            try:
                # Drop any caches the FS exposes before dropping the FS.
                for attr in ("dircache", "_intrans", "_open_files"):
                    try:
                        getattr(fs, attr, {}).clear()
                    except Exception:
                        pass
                del cache[key]
                removed += 1
            except Exception:
                pass
    if removed:
        print(f"Dropped {removed} idle fsspec filesystem instance(s) from cache.")


class EphysGuiView(param.Parameterized):

    def __init__(
        self,
        analyzer_path,
        recording_path,
        identifier=None,
        fast_mode=False,
        preload_curation=False,
        lazy=False,
        session=None,
        **params,
    ):
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
        self.lazy = lazy
        self.analyzer = None
        self._init_cb = None

        self.spinner = pn.indicators.LoadingSpinner(value=True, sizing_mode="stretch_width")
        self.log_output = pn.widgets.TextAreaInput(value="", sizing_mode="stretch_both")
        self.loading_banner = pn.Row(self.spinner, self.log_output, sizing_mode="stretch_both")

        self.win = None

        task_id = get_ecs_task_id()
        header_str = ""
        if session is not None:
            session_name = session
            header_str += f"**{session_name}** / "
        stream_name = self._get_analyzer_stream_name(self.analyzer_path)
        header_str += f"**{stream_name}**"
        header_str += f" / `{task_id}`"
        header = pn.pane.Markdown(
            header_str,
            sizing_mode="stretch_width",
        )

        # `on_session_created` in setup.py runs *before* this constructor and has
        # already added this session's log file to the count. So `list_gui_sessions()`
        # returns ALL sessions including the one being admitted right now. Subtract 1
        # to get the count of OTHER (already-active) sessions, which is what
        # `can_admit_new_session()` expects ("how many sessions are already
        # consuming a slot — can we fit one more on top of them?").
        all_gui_sessions = len(list_gui_sessions())
        existing_gui_sessions = max(0, all_gui_sessions - 1)
        ram_percent = get_container_used_memory() / get_container_total_memory() * 100
        total_ram_bytes = get_container_total_memory()

        # Admission cooldown: if another session was admitted within the
        # last few seconds, soft-reject this one. The previous admission's
        # pending-load entry needs a moment to register so concurrent
        # admissions don't all read the same stale `used + pending` sum.
        # NB: this is sequencing, not real capacity pressure — we do NOT
        # call record_session_rejection() so /health doesn't inflate.
        cooldown_remaining = admission_cooldown_remaining()
        if cooldown_remaining > 0:
            print(
                f"Soft-rejecting (admission cooldown): {cooldown_remaining:.1f}s remaining. "
                f"Task ID: {task_id}"
            )
            doc = pn.state.curdoc
            route = getattr(doc, "_log_route", None)
            session_id = getattr(doc, "_log_session_id", None)
            if route and session_id:
                remove_session(route, session_id)
            self.layout = pn.Column(
                header,
                pn.pane.Markdown(
                    f"⏱️ Another session is being admitted — please retry in "
                    f"a few seconds. (Task: `{task_id}`)",
                    sizing_mode="stretch_both",
                ),
                sizing_mode="stretch_both",
            )
            return

        # Try to derive a *dataset-specific* RAM estimate by reading the unit counts
        # unit count. This costs one S3 round-trip (~1-3s) but lets us accurately predict heavy
        # sessions instead of relying on a fixed percent.
        estimate_pct = None
        num_units = None
        if self.analyzer_path and self.analyzer_path.endswith((".zarr", ".zarr/")):
            try:
                root = super_zarr_open(self.analyzer_path)
                num_units = len(root["sorting/unit_ids"])
                est_bytes = estimate_session_ram_bytes(num_units, fast_mode=self.fast_mode)
                estimate_pct = est_bytes / total_ram_bytes * 100
                print(
                    f"Dynamic per-session RAM estimate: "
                    f"{est_bytes / (1024**3):.2f} GB ({estimate_pct:.1f}%) "
                    f"for {num_units} units, fast_mode={self.fast_mode}"
                )
            except Exception as e:
                # Pre-load failed (S3 transient, bad path, etc.) — fall back
                # to the static estimate. Better to occasionally reject a
                # session we could have admitted than to OOM.
                print(f"Could not pre-load # units for size estimate: {e}. Using static fallback.")

        # Pass the count of OTHER existing sessions (not this one) so
        # can_admit_new_session can answer "is there room for one more?".
        if not can_admit_new_session(
            current_count=existing_gui_sessions,
            used_pct=ram_percent,
            estimate_pct=estimate_pct,
        ):
            # Tell /health a rejection just happened so it can fire the
            # inflate / scale-up signal on its next tick. Without this,
            # /health would see the task's current RAM and think there's
            # still room — even though admission just turned a session away.
            record_session_rejection()
            # Remove this session from the count — it is being rejected
            doc = pn.state.curdoc
            route = getattr(doc, "_log_route", None)
            session_id = getattr(doc, "_log_session_id", None)
            if route and session_id:
                remove_session(route, session_id)
            hard_cap = get_hard_cap_sessions()
            safe_max = get_safe_max_ram_pct()
            effective_estimate = estimate_pct if estimate_pct is not None else get_per_session_estimate_pct()
            if existing_gui_sessions >= hard_cap:
                reason = f"hard session cap reached ({existing_gui_sessions}/{hard_cap})"
            else:
                source = f"{num_units} units" if num_units is not None else "static fallback"
                reason = (
                    f"insufficient RAM headroom: current {ram_percent:.1f}% + "
                    f"~{effective_estimate:.1f}% (estimated from {source}) would "
                    f"exceed safe ceiling {safe_max:.0f}%"
                )
            print(f"Rejecting new session: {reason}. Task ID: {task_id}")
            self.layout = pn.Column(
                header,
                pn.pane.Markdown(
                    f"⚠️ Cannot start a new GUI session: {reason}. "
                    f"Please try again in a few minutes or open a new tab (Task ID: `{task_id}`).",
                    sizing_mode="stretch_both",
                ),
                sizing_mode="stretch_both",
            )
        elif self.analyzer_path != "":
            # Admission succeeded — register this session's estimated RAM so
            # later admission attempts (within the same ~10s loading window)
            # see it as "pending" instead of reading a stale-low used_pct from
            # cgroup. Falls back to the static estimate if the dynamic one
            # could not be computed. The pending entry is cleared in cleanup()
            # or expires after PENDING_LOAD_TTL (60s).
            self._pending_session_id = getattr(pn.state.curdoc, "_log_session_id", None)
            pending_pct = estimate_pct if estimate_pct is not None else get_per_session_estimate_pct()
            record_pending_load(self._pending_session_id, pending_pct)
            # Start the admission-cooldown clock so the next arrival waits
            # for THIS pending-load entry to be visible.
            record_admission()

            self.layout = pn.Column(
                header,
                self._create_main_window(),
                sizing_mode="stretch_both",
            )

            def delayed_init():
                self._initialize()
                return False

            self._init_cb = pn.state.add_periodic_callback(delayed_init, period=1500, count=1)
        else:
            self.layout = pn.Column(
                header,
                pn.pane.Markdown(help_txt, sizing_mode="stretch_both"),
                sizing_mode="stretch_both",
            )

    def create_fullscreen_resize_listener(self):
        return FullscreenResizeHandler()

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
        submit_trigger.jscallback(value="""
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
            """.format(identifier=self.identifier))
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
            print(
                f"Received message for identifier {identifier}, but current identifier is {self.identifier}. Ignoring."
            )
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

    @staticmethod
    def _get_analyzer_stream_name(analyzer_path):
        from pathlib import PurePosixPath

        if not analyzer_path:
            return "unknown", "unknown"
        path = PurePosixPath(analyzer_path.rstrip("/"))
        stream_name = path.name.replace(".zarr", "") or "unknown"
        return stream_name

    def _initialize(self):
        self.layout[1] = self.loading_banner
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
                        self.curation_listener = self.create_post_message_listener()
                        self.fullscreen_listener = self.create_fullscreen_resize_listener()

                    self.win_layout = self._create_main_window()
                    self.layout[1] = self.win_layout
                    if self.identifier is not None:
                        self.layout.append(self.submit_trigger)
                        self.layout.append(self.curation_listener)
                        self.layout.append(self.fullscreen_listener)

                    print("\nEphys GUI initialized successfully!")
                    t_stop = time.perf_counter()
                    print(f"Initialization time: {t_stop - t_start:.2f} seconds")

                except Exception as e:
                    error = e
            else:
                print("Analyzer path is empty. Please provide a valid path.")

            if error is not None:
                print(f"Error during initialization: {error}")
                if len(self.layout) > 1:
                    self.layout[1] = pn.pane.Markdown(
                        f"⚠️ Error during initialization: {error}", sizing_mode="stretch_both"
                    )
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
        self.analyzer = si.load(self.analyzer_path, lazy=self.lazy)
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
        try:
            recording_processed = si.load(recording_dict)
            print(f"Processed recording loaded: {recording_processed}")
            self.analyzer.set_temporary_recording(recording_processed)
        except Exception as e:
            print(f"Error loading processed recording: {e}")

    def _create_main_window(self):
        if self.analyzer is not None:
            # prepare the curation data using decoder labels
            curation_dict = None
            if self.preload_curation:
                curation_dict = deepcopy(default_curation_dict)
                curation_dict["unit_ids"] = self.analyzer.unit_ids

                # Check the "curated" remote path for a curation dictionary and load it if available
                curated_path = str(self.analyzer_path).replace(".zarr", "").replace("postprocessed", "curated")
                curated_path = curated_path + "/curation.json"
                print(f"Curated path: {curated_path}")
                # Check if it exists on s3 and load it if available, otherwise check local path
                if curated_path.startswith("s3://"):
                    import boto3
                    from botocore.exceptions import ClientError

                    s3 = boto3.client("s3")
                    bucket_name, key = curated_path[5:].split("/", 1)
                    try:
                        s3.head_object(Bucket=bucket_name, Key=key)
                        obj = s3.get_object(Bucket=bucket_name, Key=key)
                        curation_dict = json.loads(obj["Body"].read().decode("utf-8"))
                        print(f"Loaded curation dictionary from S3: {curated_path}")
                    except ClientError as e:
                        print(f"Failed to load curation dictionary from S3: {curated_path}: {e}")

                # Look for decoder_label
                if curation_dict is None:
                    if "decoder_label" in self.analyzer.sorting.get_property_keys():
                        decoder_labels = self.analyzer.get_sorting_property("decoder_label")
                        noise_units = self.analyzer.unit_ids[decoder_labels == "noise"]
                        curation_dict["removed"] = list(noise_units)
                        for unit_id in noise_units:
                            curation_dict["manual_labels"].append({"unit_id": unit_id, "quality": ["noise"]})

                if curation_dict is not None:
                    try:
                        validate_curation_dict(curation_dict)
                    except ValueError as e:
                        print(f"Curated dictionary is invalid: {e}")
                        curation_dict = None
                else:
                    print("No curated dictionary found. Cannot preload curation.")

            if self.fast_mode:
                skip_extensions = ["waveforms", "principal_components"]
            else:
                skip_extensions = None

            curation_callback = self._curation_callback if self.identifier is not None else None

            # remove duplicated "unitrefine_label" entries if present
            sorting_property_keys = self.analyzer.sorting.get_property_keys()
            local_displayed_unit_properties = list(displayed_unit_properties)
            if "unitrefine_label" in sorting_property_keys and "decoder_label" in sorting_property_keys:
                local_displayed_unit_properties.remove("decoder_label")

            win = run_mainwindow(
                analyzer=self.analyzer,
                curation=True,
                displayed_unit_properties=local_displayed_unit_properties,
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

        # 0) Release this session's pending-load reservation so the next
        # admission attempt sees accurate RAM headroom. (The actual cgroup
        # `memory.current` won't drop until the deferred GC further down
        # runs malloc_trim — but the pending entry was overestimating, so
        # dropping it now lets other admissions proceed sooner.)
        clear_pending_load(getattr(self, "_pending_session_id", None))

        # 1) Clear postMessage listeners and submit trigger (they hold bound-method back-refs to self)
        self.curation_listener = None
        self.fullscreen_listener = None
        self.submit_trigger = None

        # 2) Release GUI controller and all its data
        sigui_win = getattr(self, "sigui_win", None)
        if sigui_win is not None:
            controller = getattr(sigui_win, "controller", None)
            if controller is not None:
                # Break the SignalHandler ↔ Controller back-edge BEFORE we
                # touch the views, so even partial failures still detach the
                # graph from the controller.
                signal_handler = getattr(controller, "signal_handler", None)
                if signal_handler is not None:
                    try:
                        signal_handler.controller = None
                    except Exception:
                        pass

                # Each view has TWO sets of param watchers, plus three back-refs
                # to the controller graph that the gc cycle collector can't break
                # because SignalHandler.controller is a strong external ref into
                # the cycle. Break them all here:
                #   - view.settings._parameterized watchers   (settings change → refresh)
                #   - view.notifier watchers                  (signal handler → 8 bound methods)
                #   - view.notifier.view = view               (direct cycle)
                #   - view.controller = controller            (back-ref)
                #   - view.tour_timer (ndscatterview only)    (pn.state.add_periodic_callback)
                for view in list(getattr(controller, "views", [])):
                    try:
                        view.settings._parameterized.param.unwatch_all()
                    except Exception:
                        pass
                    try:
                        view.notifier.param.unwatch_all()
                    except Exception:
                        pass
                    notifier = getattr(view, "notifier", None)
                    if notifier is not None:
                        try:
                            notifier.view = None
                        except Exception:
                            pass
                    try:
                        view.notifier = None
                    except Exception:
                        pass
                    try:
                        view.controller = None
                    except Exception:
                        pass
                    # Stop per-view periodic callbacks. Only ndscatterview's
                    # "Random tour" registers one today, but list-driven so
                    # adding new ones upstream doesn't silently leak.
                    for cb_attr in ("tour_timer",):
                        cb = getattr(view, cb_attr, None)
                        if cb is not None:
                            try:
                                cb.stop()
                            except Exception:
                                pass
                            try:
                                setattr(view, cb_attr, None)
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
                    "templates_average",
                    "templates_std",
                    # positions / geometry
                    "unit_positions",
                    "visible_channel_inds",
                    # quality / metrics
                    "noise_levels",
                    "metrics",
                    # spike-level arrays
                    "spike_amplitudes",
                    "amplitude_scalings",
                    "spike_depths",
                    "spikes",
                    "random_spikes_indices",
                    "segment_slices",
                    "final_spike_samples",
                    "_spike_index_by_units",
                    "_spike_index_by_segment_and_units",
                    "_spike_visible_indices",
                    "_spike_selected_indices",
                    # correlograms / ISI
                    "correlograms",
                    "correlograms_bins",
                    "isi_histograms",
                    "isi_bins",
                    # similarity
                    "_similarity_by_method",
                    # extension objects (hold zarr array refs — must clear before analyzer)
                    "waveforms_ext",
                    "pc_ext",
                    "_pc_projections",
                    # misc
                    "_extremum_channel",
                    "_traces_cached",
                    "units_table",
                    "_potential_merges",
                    # sparsity / signal handler
                    "external_sparsity",
                    "analyzer_sparsity",
                    "signal_handler",
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
                if _FSSPEC_DROP_INSTANCE_CACHE:
                    _clear_fsspec_instance_caches()
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
            if _FSSPEC_DROP_INSTANCE_CACHE:
                _clear_fsspec_instance_caches()
                gc.collect()
            _malloc_trim()
            final_mem = psutil.virtual_memory()
            used = final_mem.used / (1024**3)
            print(f"\nRAM Usage after cleanup: {used:.2f} / {total_ram:.2f} GB\n")

    def panel(self):
        """Return the panel layout"""
        return self.layout
