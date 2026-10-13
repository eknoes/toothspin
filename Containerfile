FROM docker.io/library/python:3.13-slim

# pw-dump / pw-record talk to the host's PipeWire over its socket.
RUN apt-get update \
    && apt-get install -y --no-install-recommends pipewire-bin \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir .

ENV DATA_DIR=/data PYTHONUNBUFFERED=1 PIPEWIRE_RUNTIME_DIR=/run/pipewire
VOLUME /data
CMD ["sendspin-bluetooth"]
