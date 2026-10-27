import panel as pn

import spikeinterface as si
from spikeinterface_gui import run_mainwindow_comparison

from aind_ephys_portal.panel.ephys_gui import EphysGuiView, displayed_unit_properties, user_settings


comparison_help_txt = """
## Usage
Sorting Analyzers not loaded. Embed the `analyzer_path1` and `analyzer_path2` parameters in the URL
(and optionally `analyzer1_name`, `analyzer2_name` and `recording_path`) to launch the comparison GUI,
or use the comparison launcher: /ephys_comparison_launcher_app
"""


class EphysComparisonGuiView(EphysGuiView):
    """
    The spikeinterface-gui comparison of two analyzers of the same recording.

    Admission control, logging and cleanup are the ones of EphysGuiView: analyzer 1 plays
    the role of `self.analyzer`, analyzer 2 is handled on top of it. There is no curation
    in comparison mode, and the analyzers are always loaded eagerly (the comparison
    controller does not support lazy analyzers).
    """

    def __init__(
        self,
        analyzer_path1,
        analyzer_path2,
        analyzer1_name="",
        analyzer2_name="",
        recording_path="",
        fast_mode=False,
        session=None,
        **params,
    ):
        self.analyzer_path2 = analyzer_path2
        self.analyzer1_name = analyzer1_name or (self._get_analyzer_stream_name(analyzer_path1) if analyzer_path1 else "1")
        self.analyzer2_name = analyzer2_name or (self._get_analyzer_stream_name(analyzer_path2) if analyzer_path2 else "2")
        self.analyzer2 = None
        # both paths are needed: an empty analyzer_path makes the base class show the usage text
        super().__init__(
            analyzer_path=analyzer_path1 if analyzer_path2 else "",
            recording_path=recording_path,
            identifier=None,
            fast_mode=fast_mode,
            preload_curation=False,
            lazy=False,
            session=session,
            **params,
        )

    def _get_header_name(self):
        return f"{self.analyzer1_name} vs {self.analyzer2_name}"

    def _estimate_session_ram(self, total_ram_bytes):
        """The sum of the estimates of the two analyzers, both loaded eagerly"""
        analyzer_path1 = self.analyzer_path
        if not analyzer_path1:
            # nothing will be loaded (usage text), same as the base class
            return None, None
        estimates = []
        for path in (analyzer_path1, self.analyzer_path2):
            self.analyzer_path = path
            estimates.append(super()._estimate_session_ram(total_ram_bytes))
        self.analyzer_path = analyzer_path1
        # the estimate may ask for lazy loading, which the comparison cannot do
        self.lazy = False
        if any(pct is None for pct, _ in estimates):
            # the static per session fallback once: twice would exceed the safe ceiling on any
            # task, so a comparison could never be admitted when the estimate fails
            return None, None
        return sum(pct for pct, _ in estimates), sum(n for _, n in estimates)

    def _initialize_analyzer(self):
        super()._initialize_analyzer()
        if not self.analyzer_path2.endswith((".zarr", ".zarr/")):
            raise ValueError("Only Zarr files are supported for now.")
        print("Loading analyzer 2...")
        self.analyzer2 = si.load(self.analyzer_path2, lazy=False)
        print(f"Analyzer 2 loaded: {self.analyzer2}")

    def _set_processed_recording(self):
        super()._set_processed_recording()
        # the comparison only displays the traces of analyzer 1, but both need the same recording
        if self.analyzer.has_temporary_recording():
            self.analyzer2.set_temporary_recording(self.analyzer.recording)

    def _create_main_window(self):
        if self.analyzer is None or self.analyzer2 is None:
            return pn.pane.Markdown(comparison_help_txt, sizing_mode="stretch_both")

        skip_extensions = ["waveforms", "principal_components"] if self.fast_mode else None
        win = run_mainwindow_comparison(
            self.analyzer,
            self.analyzer2,
            analyzer1_name=self.analyzer1_name,
            analyzer2_name=self.analyzer2_name,
            displayed_unit_properties=list(displayed_unit_properties),
            mode="web",
            start_app=False,
            panel_window_servable=False,
            verbose=True,
            skip_extensions=skip_extensions,
            user_settings=user_settings,
        )
        self.sigui_win = win
        return win.main_layout

    def cleanup(self):
        # the comparison controller holds a few more references than the single analyzer one
        controller = getattr(getattr(self, "sigui_win", None), "controller", None)
        if controller is not None:
            for attr in (
                "analyzer1", "analyzer2", "waveforms_ext1", "waveforms_ext2", "comp",
                "external_sparsity1", "external_sparsity2", "analyzer_sparsity1", "analyzer_sparsity2",
                "_matching_cache", "_ordered_agreement_scores", "_main_channels",
            ):
                try:
                    setattr(controller, attr, None)
                except Exception:
                    pass

        # close the zarr store of analyzer 2, the base class closes the one of analyzer 1
        if getattr(self, "analyzer2", None) is not None:
            try:
                store = getattr(self.analyzer2._get_zarr_root(mode="r"), "store", None)
                if store is not None:
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
                print(f"Warning: could not close zarr store of analyzer 2: {e}")
            self.analyzer2 = None

        super().cleanup()
