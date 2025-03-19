FROM python:3.11-slim

WORKDIR /app

ADD src ./src
ADD pyproject.toml .
ADD setup.py .


RUN apt-get update
RUN apt install -y git
RUN pip install --upgrade pip
RUN pip install . --no-cache-dir

# Install spikeinterface-gui from source
RUN git clone https://github.com/alejoe91/spikeinterface-gui.git && \
    cd spikeinterface-gui && \
    git checkout 77d7f5df66049d194553782702aaaae4352a332e && \
    pip install . --no-cache-dir && cd ..

# Install PyQt5
RUN pip install PyQt5

EXPOSE 8000
ENTRYPOINT ["sh", "-c", "panel serve src/aind_ephys_portal/ephys_portal_app.py src/aind_ephys_portal/ephys_gui_app.py --static-dirs images=src/aind_ephys_portal/images --address 0.0.0.0 --port 8000 --allow-websocket-origin ${ALLOW_WEBSOCKET_ORIGIN} --keep-alive 10000 --index ephys_portal_app.py"]