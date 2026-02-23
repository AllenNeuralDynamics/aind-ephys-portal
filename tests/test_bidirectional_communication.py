"""
Test Panel app for bidirectional postMessage communication with ephys_gui_app.

Start the ephys_gui_app server on port 6000, then serve this file:

    panel serve tests/test_bidirectional_communication.py --port 5007 --allow-websocket-origin="*"

Each iframe loads the GUI with a different identifier (0000 / 0001).
The parent app can receive curation data from either iframe and send
curation data back to a chosen iframe.
"""

import json
import datetime

import urllib.parse

import panel as pn
from panel.custom import ReactComponent
from panel.param import param

pn.extension()

EPHYS_GUI_PORT = 5006
ANALYZER_PATH="s3://codeocean-s3datasetsbucket-1u41qdg42ur9/543979ee-17bd-41af-a504-e94a1de2ac40/postprocessed/experiment1_Record Node 104#Neuropix-PXI-100.ProbeA_recording1_group0.zarr"
IDENTIFIERS = ["0000", "0001"]


# ── Receive: listen for "panel-data" messages coming from the iframes ────────

class ParentPostMessageListener(ReactComponent):
    """
    Listens on the *parent* window for postMessage events of type ``panel-data``
    sent by the embedded ephys_gui_app iframes and forwards them to Python.
    """

    accept_type = param.String(default="panel-data")

    _esm = """
    export function render({ model }) {
      const [acceptType] = model.useState("accept_type");

      function onMessage(event) {
        const data = event.data;
        if (!data || data.source === "react-devtools-content-script") return;
        if (acceptType && data.type !== acceptType) return;
        model.send_msg({ payload: data, _ts: Date.now() });
      }

      React.useEffect(() => {
        window.addEventListener("message", onMessage);
        return () => window.removeEventListener("message", onMessage);
      }, [acceptType]);

      return <></>;
    }
    """


# ── Send: postMessage into a specific iframe ─────────────────────────────────

class IFramePostMessageSender(ReactComponent):
    """
    Invisible component that, whenever *message_json* changes, posts a
    ``curation-data`` message into the iframe whose id matches *target_iframe_id*.
    """

    message_json = param.String(default="")
    target_iframe_id = param.String(default="")

    _esm = """
    export function render({ model }) {
      const [messageJson] = model.useState("message_json");
      const [targetId]    = model.useState("target_iframe_id");

      React.useEffect(() => {
        if (!messageJson) return;

        // Strip the timestamp suffix we append to force change detection
        const lastUnderscore = messageJson.lastIndexOf("_");
        const raw = lastUnderscore > 0 ? messageJson.substring(0, lastUnderscore) : messageJson;
        if (!raw) return;

        try {
          const parsed = JSON.parse(raw);
          const iframe = document.getElementById(targetId);
          if (iframe && iframe.contentWindow) {
            iframe.contentWindow.postMessage(parsed, "*");
            console.log(`[parent] Sent to iframe#${targetId}:`, parsed);
          } else {
            console.warn(`[parent] iframe#${targetId} not found`);
          }
        } catch (err) {
          console.error("[parent] JSON parse error:", err);
        }
      }, [messageJson]);

      return <></>;
    }
    """


# ── Build IFrame URLs ────────────────────────────────────────────────────────

def iframe_url(identifier: str) -> str:
    return (
        f"http://localhost:{EPHYS_GUI_PORT}/ephys_gui_app"
        f"?analyzer_path={urllib.parse.quote(ANALYZER_PATH)}&"
        f"recording_path=&identifier={identifier}&fast_mode=true"
    )


# ── Layout ────────────────────────────────────────────────────────────────────

# Iframes
print("Loading iframes with URLs:")
print(f"iframe-0000: {iframe_url('0000')}")
print(f"iframe-0001: {iframe_url('0001')}")
iframe_0000 = pn.pane.HTML(
    f'<iframe id="iframe-0000" src="{iframe_url("0000")}" '
    f'style="width:100%;height:100%;border:2px solid #2A7DE1;border-radius:6px;" '
    f'allow="cross-origin-isolated"></iframe>',
    sizing_mode="stretch_both",
    min_height=500,
)
iframe_0001 = pn.pane.HTML(
    f'<iframe id="iframe-0001" src="{iframe_url("0001")}" '
    f'style="width:100%;height:100%;border:2px solid #1D8649;border-radius:6px;" '
    f'allow="cross-origin-isolated"></iframe>',
    sizing_mode="stretch_both",
    min_height=500,
)

# Received-messages log
received_log = pn.widgets.TextAreaInput(
    name="📩  Received curation messages",
    value="",
    placeholder="Messages from iframes will appear here…",
    sizing_mode="stretch_both",
    min_height=200,
    disabled=True,
)

# PostMessage listener (parent-level)
listener = ParentPostMessageListener()


def _on_receive(msg):
    """Callback fired when a panel-data message arrives from any iframe."""
    payload = msg.get("payload", {})
    identifier = payload.get("identifier", "???")
    data = payload.get("data", "")
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    entry = f"[{ts}]  ── identifier: {identifier} ──\n{json.dumps(data, indent=2)}\n{'─' * 50}\n"
    received_log.value = entry + received_log.value


listener.on_msg(_on_receive)

# ── Send controls ────────────────────────────────────────────────────────────

target_select = pn.widgets.Select(
    name="Target identifier",
    options=IDENTIFIERS,
    value=IDENTIFIERS[0],
    width=160,
)

send_textarea = pn.widgets.TextAreaInput(
    name="✏️  Curation data to send (JSON)",
    value='{"manual_labels": [{"unit_id": 0, "quality": ["good"]}]}',
    sizing_mode="stretch_width",
    min_height=120,
)

send_button = pn.widgets.Button(name="Send ➤", button_type="primary", width=120)

sender = IFramePostMessageSender()

_send_counter = [0]


def _on_send(event):
    """Build a curation-data postMessage payload and push it into the sender."""
    identifier = target_select.value
    raw = send_textarea.value.strip()
    if not raw:
        return
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        received_log.value = f"⚠️  Invalid JSON: {exc}\n" + received_log.value
        return

    envelope = {
        "type": "curation-data",
        "identifier": identifier,
        "data": data,
    }

    sender.target_iframe_id = f"iframe-{identifier}"
    # Append a unique counter so the param change always fires
    _send_counter[0] += 1
    sender.message_json = json.dumps(envelope) + f"_{_send_counter[0]}"

    ts = datetime.datetime.now().strftime("%H:%M:%S")
    received_log.value = (
        f"[{ts}]  ▶ SENT to {identifier}\n"
        f"{json.dumps(data, indent=2)}\n{'─' * 50}\n"
        + received_log.value
    )


send_button.on_click(_on_send)

# ── Assemble ──────────────────────────────────────────────────────────────────

header = pn.pane.Markdown(
    "# 🔬 Bidirectional Communication Test\n"
    f"Iframes point to `localhost:{EPHYS_GUI_PORT}` — make sure the ephys_gui_app server is running.",
    sizing_mode="stretch_width",
)

iframes_row = pn.Row(
    pn.Column("### iframe 0000", iframe_0000, sizing_mode="stretch_both"),
    pn.Column("### iframe 0001", iframe_0001, sizing_mode="stretch_both"),
    sizing_mode="stretch_both",
    min_height=500,
)

send_panel = pn.Column(
    pn.Row(target_select, send_button, align="end"),
    send_textarea,
    sizing_mode="stretch_width",
)

comm_row = pn.Row(
    pn.Column("### Send", send_panel, sizing_mode="stretch_both"),
    pn.Column("### Receive", received_log, sizing_mode="stretch_both"),
    sizing_mode="stretch_width",
    min_height=250,
)

layout = pn.Column(
    header,
    iframes_row,
    comm_row,
    listener,   # invisible – just needs to be in the document
    sender,     # invisible – just needs to be in the document
    sizing_mode="stretch_both",
)

layout.servable(title="Bidirectional Communication Test")
