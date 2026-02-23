import panel as pn

from panel.param import param
from panel.custom import ReactComponent


EPHYSGUI_LINK_PREFIX = "/ephys_gui_app?analyzer_path={}&recording_path={}&preload_curation=true"


AIND_COLORS = colors = {
    "dark_blue": "#003057",
    "light_blue": "#2A7DE1",
    "green": "#1D8649",
    "yellow": "#FFB71B",
    "grey": "#7C7C7F",
    "red": "#FF5733",
}

OUTER_STYLE = {
    "background": "#ffffff",
    "border-radius": "5px",
    "border": "2px solid black",
    "padding": "10px",
    "box-shadow": "5px 5px 5px #bcbcbc",
    "margin": "5px",
}


def format_link(link: str, text: str = "link"):
    """Format link as an HTML anchor tag

    Parameters
    ----------
    link : str
    text : str, optional
        by default "link"
    """
    return f'<a href="{link}" target="_blank">{text}</a>'


def format_css_background():
    """Add the custom CSS for the background to the panel configuration"""
    # Add the custom CSS
    background_color = AIND_COLORS[
        (
            pn.state.location.query_params["background"]
            if "background" in pn.state.location.query_params
            else "dark_blue"
        )
    ]
    BACKGROUND_CSS = f"""
    body {{
        background-color: {background_color} !important;
        background-image: url('/images/aind-pattern.svg') !important;
        background-size: 1200px;
    }}
    """
    pn.config.raw_css.append(BACKGROUND_CSS)  # type: ignore



class PostMessageListener(ReactComponent):
    """
    Listen to window.postMessage events and forward them to Python via on_msg().
    This avoids ReactiveHTML/Bokeh 'source' linkage issues.
    """
    _model_name = "PostMessageListener"
    _model_module = "post_message_listener"
    _model_module_version = "0.0.1"

    # If set, only forward messages whose event.data.type matches this value.
    accept_type = param.String(default="curation-data")

    _esm = """
    export function render({ model }) {
      const [accept_type] = model.useState("accept_type");

      function onMessage(event) {
        const data = event.data;

        // Ignore messages from browser extensions
        if (data && data.source === "react-devtools-content-script") return;

        if (accept_type && data && data.type !== accept_type) return;

        // Always include a timestamp so repeated sends still look "new"
        model.send_msg({ payload: data, _ts: Date.now() });
      }

      React.useEffect(() => {
        window.addEventListener("message", onMessage);
        return () => window.removeEventListener("message", onMessage);
      }, [accept_type]);

      return <></>;
    }
    """