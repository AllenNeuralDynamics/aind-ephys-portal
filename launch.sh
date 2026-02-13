#!/bin/sh
panel serve \
    src/aind_ephys_portal/ephys_gui_app.py \
    src/aind_ephys_portal/ephys_portal_app.py \
    src/aind_ephys_portal/ephys_launcher_app.py \
    src/aind_ephys_portal/ephys_monitor_app.py \
    --setup src/aind_ephys_portal/setup.py \
    --static-dirs images=src/aind_ephys_portal/images \
    --check-unused-sessions 2000 \
    --unused-session-lifetime 5000 \
    --num-procs 4