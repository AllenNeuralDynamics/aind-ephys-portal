FROM python:3.11-slim

WORKDIR /app

ADD src ./src
ADD pyproject.toml .
ADD setup.py .


RUN apt-get update
RUN apt install -y git build-essential nodejs npm
RUN pip install --upgrade pip setuptools wheel
RUN pip install .

# Install wavpack
ENV WAVPACK_VERSION=5.7.0
RUN apt install -y wget
RUN wget "https://www.wavpack.com/wavpack-${WAVPACK_VERSION}.tar.bz2" && \
    tar -xf wavpack-$WAVPACK_VERSION.tar.bz2 && cd wavpack-$WAVPACK_VERSION && \
    ./configure && make install && cd ..

# Install
RUN pip install wavpack-numcodecs

# Install spikeinterface from source
RUN git clone https://github.com/SpikeInterface/spikeinterface.git && \
    cd spikeinterface && \
    git checkout d6f8c5af9d33aca3d9191472205b91adc3ca1faf && \
    pip install . && cd ..

# Install spikeinterface-gui from source
RUN git clone https://github.com/SpikeInterface/spikeinterface-gui.git && \
    cd spikeinterface-gui && \
    git checkout 176c1b12f731d34e320c626d7ec3b1def011c791 && \
    pip install . && cd ..


EXPOSE 8000
ENTRYPOINT ["sh", "-c", "panel serve src/aind_ephys_portal/ephys_portal_app.py src/aind_ephys_portal/ephys_gui_app.py --setup src/aind_ephys_portal/setup.py --static-dirs images=src/aind_ephys_portal/images --address 0.0.0.0 --port 8000 --allow-websocket-origin ${ALLOW_WEBSOCKET_ORIGIN} --keep-alive 10000 --index ephys_portal_app.py --num-procs 4 --warm"]