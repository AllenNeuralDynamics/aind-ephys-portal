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

To run the Ephys Portal you can either use tha `launch.sh` script:

```bash
AWS_PROFILE=your-profile

# Make sure your SSO session is active
aws sso login --profile $AWS_PROFILE

python entrypoint.py --port 8000 (default) --address 0.0.0.0 (default)
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

AWS_PROFILE=your-profile

# Make sure your SSO session is active
aws sso login --profile $AWS_PROFILE

# Export temporary credentials and run Docker
eval "$(aws configure export-credentials --profile $AWS_PROFILE --format env)"
docker run --rm -e AWS_ACCESS_KEY_ID -e AWS_SECRET_ACCESS_KEY -e AWS_SESSION_TOKEN -e ALLOW_WEBSOCKET_ORIGIN=0.0.0.0:8000 -p 8000:8000 aind-ephys-portal
```
2. Navigate to '0.0.0.0:8000` to view the app.

## License

This project is licensed under the terms of the LICENSE file included in the repository.
