# Self-contained image: the service plus its own PipeWire/WirePlumber. Needs
# only the host's bluetoothd (system D-Bus socket) and host networking.
# Alpine: smallest base whose PipeWire ships the AAC codec iPhones stream
# (Debian's lacks it, fdk-aac being non-free there).
ARG ALPINE_RELEASE=3.22

FROM docker.io/library/alpine:${ALPINE_RELEASE} AS build
RUN apk add --no-cache python3
COPY pyproject.toml /src/
COPY src /src/src
RUN python3 -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir /src \
    && /opt/venv/bin/pip uninstall -y pip \
    && find /opt/venv -name __pycache__ -prune -exec rm -rf {} +

FROM docker.io/library/alpine:${ALPINE_RELEASE}
RUN apk add --no-cache python3 pipewire wireplumber pipewire-spa-bluez pipewire-tools
COPY --from=build /opt/venv /opt/venv
COPY deploy/pipewire/*.conf /etc/wireplumber/wireplumber.conf.d/
COPY deploy/pipewire/pipewire.conf.d/*.conf /etc/pipewire/pipewire.conf.d/

ENV PATH=/opt/venv/bin:$PATH \
    DATA_DIR=/data \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    BUNDLED_PIPEWIRE=1 \
    XDG_RUNTIME_DIR=/tmp/runtime \
    XDG_STATE_HOME=/tmp/runtime/state
LABEL org.opencontainers.image.licenses="GPL-3.0-or-later"
VOLUME /data
CMD ["toothspin"]
