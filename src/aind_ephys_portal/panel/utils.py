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



class FullscreenResizeHandler(ReactComponent):
    """
    Pure-JS component that listens for 'fullscreen-resize' postMessages and
    forces Bokeh to re-measure canvas sizes without any Python layout rebuild.

    Bokeh 3.x uses ResizeObserver (not window.resize events) to detect size
    changes. We trigger it by briefly collapsing the Bokeh root element to 1px
    then removing the override — ResizeObserver fires on the size delta, Bokeh
    re-renders at the new (fullscreen) container dimensions.

    This avoids the destructive Python layout swap (remove + re-add) which
    loses Bokeh event handler routing (e.g. selectiongeometry) and resets
    toolbar.active_drag, breaking the lasso selection tool.
    """

    _esm = """
    export function render({ model }) {
      React.useEffect(() => {
        function triggerResize() {
          // 1) BokehJS API — invalidate layout on all registered views.
          //    Bokeh.index is a plain object in Bokeh 3.x ({id: view, ...}).
          try {
            if (window.Bokeh && window.Bokeh.index) {
              Object.values(window.Bokeh.index).forEach(view => {
                if (view) {
                  view.invalidate_layout?.();
                  view.invalidate_render?.();
                }
              });
            }
          } catch(e) {
            console.warn("[FullscreenResizeHandler] BokehJS API error:", e);
          }

          // 2) Force ResizeObserver to fire by briefly collapsing the Bokeh
          //    root element then removing the override (one animation frame)
          const roots = document.querySelectorAll("[data-root-id]");
          roots.forEach(el => {
            el.style.setProperty("width",  "1px", "important");
            el.style.setProperty("height", "1px", "important");
          });
          requestAnimationFrame(() => {
            roots.forEach(el => {
              el.style.removeProperty("width");
              el.style.removeProperty("height");
            });
            // 3) window.resize fallback for older Bokeh / Panel versions
            window.dispatchEvent(new Event("resize"));
          });
        }

        function onMessage(event) {
          const data = event.data;
          if (!data || data.type !== "fullscreen-resize") return;
          triggerResize();
          setTimeout(triggerResize, 300);
        }

        window.addEventListener("message", onMessage);
        return () => window.removeEventListener("message", onMessage);
      }, []);
      return <></>;
    }
    """


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