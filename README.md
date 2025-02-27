# AIND SIGUI Portal

A Panel application for SIGUI data visualization.

## Description

The AIND SIGUI Portal is a web-based application built with [Panel](https://panel.holoviz.org/) that provides a user interface for searching and visualizing SIGUI data.

## Features

- Search bar for querying SIGUI data
- Placeholder panel for future implementation

## Installation

```bash
# Clone the repository
git clone https://github.com/AllenNeuralDynamics/aind-sigui-portal.git
cd aind-sigui-portal

# Install the package
pip install -e .
```

## Usage

To run the SIGUI Portal:

```bash
# Run using Panel CLI (recommended for server deployment)
panel serve src/aind_sigui_portal/app.py

# Or run as a module
python -m aind_sigui_portal

# Or use the command-line entry point
aind-sigui-portal
```

The Panel CLI method is recommended for server deployment and provides additional options:

```bash
# Run with auto-reload for development
panel serve src/aind_sigui_portal/app.py --autoreload

# Specify a port
panel serve src/aind_sigui_portal/app.py --port=8000

# Run in the background
panel serve src/aind_sigui_portal/app.py --port=8000 --allow-websocket-origin=* --address=0.0.0.0
```

This will start a Panel server and make the application available in your web browser.

## Development

To install development dependencies:

```bash
pip install -e ".[dev]"
```

## License

This project is licensed under the terms of the LICENSE file included in the repository.
