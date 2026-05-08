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

# Force scikit-learn to 1.6.1 to avoid issues with newer versions
RUN pip install scikit-learn==1.6.1

# Install spikeinterface-gui from source
RUN pip install spikeinterface-gui==0.13.1

ENV PYTHONUNBUFFERED=1

EXPOSE 8000
ENTRYPOINT ["python", "entrypoint.py", "--address", "0.0.0.0", "--port", "8000", "--test"]
