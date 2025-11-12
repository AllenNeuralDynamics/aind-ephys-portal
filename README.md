# AIND Ephys Portal

A Panel application for Ephys data visualization.

## Description

The AIND Ephys Portal is a web-based application built with [Panel](https://panel.holoviz.org/) that provides a user interface for searching and visualizing Ephys data.

## Features

- Search bar for querying Ephys data
- SpikeInterface GUI to view and curate ephys data

## Installation

```bash
# Clone the repository
git clone https://github.com/AllenNeuralDynamics/aind-ephys-portal.git
cd aind-ephys-portal

# Install the package
pip install -e .
```

## Usage

To run the Ephys Portal:

```bash
# Run using Panel CLI (recommended for server deployment)
panel serve src/aind_ephys_portal/ephys_portal_app.py src/aind_ephys_portal/ephys_gui_app.py  --setup src/aind_ephys_portal/setup.py --static-dirs images=src/aind_ephys_portal/images --num-procs 8
```

This will start a Panel server and make the application available in your web browser.

## Development

To install development dependencies:

```bash
pip install -e ".[dev]"
```

### Local dev
1. Build the Docker image locally and run a Docker container:
```sh
docker build -t aind-ephys-portal .
docker run -e ALLOW_WEBSOCKET_ORIGIN=0.0.0.0:8000 -p 8000:8000 aind-ephys-portal
```
2. Navigate to '0.0.0.0:8000` to view the app.

## License

This project is licensed under the terms of the LICENSE file included in the repository.
