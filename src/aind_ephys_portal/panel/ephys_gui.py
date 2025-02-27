import sys
import io
import param
import boto3


from aind_ephys_portal.docdb.database import get_name_from_id, get_asset_by_name, get_raw_asset_by_name

from spikeinterface_gui.backends.panel import PanelBackend
import spikeinterface as si
from spikeinterface.core.core_tools import extractor_dict_iterator, set_value_in_extractor_dict
import panel as pn


class EphysGuiView(param.Parameterized):

    def __init__(self, analyzer_path, recording_path, **params):
        """Construct the QCPanel object"""
        super().__init__(**params)

        # Setup minimal record information from DocDB
        self.analyzer_path = analyzer_path
        self.recording_path = recording_path
        self.analyzer = None

        self.backend = PanelBackend()
        self.pn = self.backend.create_app()

        # Create initial layout
        self.layout = self.pn.Column(
            self.pn.Row(
                self.pn.widgets.TextInput(name='Analyzer path', value=self.analyzer_path, height=50),
                self.pn.widgets.TextInput(name='Recording path (optional)', value=self.recording_path, height=50),
                self.pn.widgets.Button(name='Launch!', button_type='primary', height=50)
            ),
            self._create_main_window()
        )

        # Store widget references
        self.analyzer_input = self.layout[0][0]
        self.recording_input = self.layout[0][1]
        self.launch_button = self.layout[0][2]
        
        # Setup event handlers
        self.analyzer_input.param.watch(self.update_values, 'value')
        self.recording_input.param.watch(self.update_values, 'value')
        self.launch_button.on_click(self.on_click)

    def _initialize(self):
        if self.analyzer_input.value != "":
            spinner = pn.indicators.LoadingSpinner(value=True, sizing_mode="stretch_width")
            # Create a TextArea widget to display logs
            log_output = pn.widgets.TextAreaInput(value='', sizing_mode="stretch_both")

            class StdoutRedirector(io.StringIO):
                def write(self, message):
                    log_output.value += message  # Append new log messages

            sys.stdout = StdoutRedirector()  # Redirect stdout
            class StderrRedirector(io.StringIO):
                def write(self, message):
                    log_output.value += f"<span style='color:red;'>{message}</span>"  # Append new log messages in red

            sys.stderr = StderrRedirector()  # Redirect stderr
            self.layout[1] = pn.Row(spinner, log_output)

            print(f"Initializing Ephys GUI for:\nAnalyzer path: {self.analyzer_path}\nRecording path: {self.recording_path}")

            self._initialize_analyzer()
            if self.recording_path != "":
                self._set_processed_recording()
            self.win = self._create_main_window()
            self.layout[1] = self.win
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
            s3 = boto3.client('s3')
            response = s3.list_objects_v2(Bucket=bucket_name, Prefix=prefix, MaxKeys=1)
            return 'Contents' in response
        except Exception as e:
            return False

    def _create_main_window(self):
        if self.analyzer is not None:
            win = self.backend.create_main_window(
                analyzer=self.analyzer,
                verbose=True,
                curation=True
            )
            return win.show()
        else:
            return pn.pane.Markdown("Analyzer not initialized")

    def update_values(self, event):
        self.analyzer_path = self.analyzer_input.value
        self.recording_path = self.recording_input.value
        self._initialize()

    def on_click(self, event):
        print("Launching!!!!!!!!!!!!!")
        self._initialize()

    def panel(self):
        """Return the panel layout"""
        return self.layout
