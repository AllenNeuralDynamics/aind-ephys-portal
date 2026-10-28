FROM python:3.13-slim

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
RUN pip install wavpack-numcodecs==0.3.0

RUN pip install spikeinterface==0.105.4

RUN pip install --force-reinstall --no-deps git+https://github.com/alejoe91/spikeinterface-gui.git@fcff799c3d32873b9b2819f9288893f3d0a02b73

# Pin scikit-learn AFTER spikeinterface installs so we override whatever the
# transitive resolver picked. Match the version that analyzers in our pipeline
# are saved with — version mismatches trigger sklearn's InconsistentVersionWarning,
# which is then constructed with a positional arg by buggy upstream code and
# crashes session init (TypeError: __init__() takes 1 positional argument but 2).
RUN pip install scikit-learn==1.8.0

# panel 1.10 / bokeh 3.10 break rendering (DeserializationError: reference isn't known)
RUN pip install panel==1.9.4 bokeh==3.9.2

ENV PYTHONUNBUFFERED=1
# Limit glibc malloc arenas to reduce per-thread heap fragmentation.
# Default is 8 * NCPU; with numpy/zarr large alloc + free patterns this
# leaves freed pages stranded across many arenas, inflating RSS.
ENV MALLOC_ARENA_MAX=2
ENV NUMCODECS_ALLOW_UNSAFE_PICKLE_DECODE=1


EXPOSE 8000
ENTRYPOINT ["python", "entrypoint.py", "--address", "0.0.0.0", "--port", "8000"]
