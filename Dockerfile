FROM python:3.11-slim

WORKDIR /app

ADD src ./src
ADD pyproject.toml .
ADD setup.py .


RUN apt-get update
RUN apt install -y git build-essential nodejs npm
RUN pip install --upgrade pip
RUN pip install . --no-cache-dir

# Install wavpack
ENV WAVPACK_VERSION=5.7.0
RUN apt install -y wget
RUN wget "https://www.wavpack.com/wavpack-${WAVPACK_VERSION}.tar.bz2" && \
    tar -xf wavpack-$WAVPACK_VERSION.tar.bz2 && cd wavpack-$WAVPACK_VERSION && \
    ./configure && make install && cd ..

# Install
RUN pip install wavpack-numcodecs

# Install spikeinterface-gui from source
RUN git clone https://github.com/alejoe91/spikeinterface-gui.git && \
    cd spikeinterface-gui && \
    git checkout f8198db0ac04232f594dcb1bef80c446e41cd775 && \
    pip install . --no-cache-dir && cd ..


EXPOSE 8000
ENTRYPOINT ["sh", "-c", "panel serve src/aind_ephys_portal/ephys_portal_app.py src/aind_ephys_portal/ephys_gui_app.py --static-dirs images=src/aind_ephys_portal/images --address 0.0.0.0 --port 8000 --allow-websocket-origin ${ALLOW_WEBSOCKET_ORIGIN} --keep-alive 10000 --index ephys_portal_app.py --warm"]