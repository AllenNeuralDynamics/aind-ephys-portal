FROM python:3.11-slim

WORKDIR /app

ADD src ./src
ADD pyproject.toml .
ADD setup.py .
ADD entrypoint.py .


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
RUN pip install spikeinterface==0.104.1

# Install spikeinterface-gui from source
RUN pip install spikeinterface-gui==0.13.1

# Pin scikit-learn AFTER spikeinterface installs so we override whatever the
# transitive resolver picked. Match the version that analyzers in our pipeline
# are saved with — version mismatches trigger sklearn's InconsistentVersionWarning,
# which is then constructed with a positional arg by buggy upstream code and
# crashes session init (TypeError: __init__() takes 1 positional argument but 2).
RUN pip install scikit-learn==1.8.0

ENV PYTHONUNBUFFERED=1
# Limit glibc malloc arenas to reduce per-thread heap fragmentation.
# Default is 8 * NCPU; with numpy/zarr large alloc + free patterns this
# leaves freed pages stranded across many arenas, inflating RSS.
ENV MALLOC_ARENA_MAX=2

EXPOSE 8000
ENTRYPOINT ["python", "entrypoint.py", "--address", "0.0.0.0", "--port", "8000"]