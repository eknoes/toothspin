# Self-contained image: the service plus its own PipeWire/WirePlumber. Needs
# only the host's bluetoothd (over the system D-Bus socket). Alpine: small,
# and its PipeWire ships the AAC codec iPhones stream. The release is written
# out in both FROM lines so Dependabot can propose new ones.

FROM docker.io/library/alpine:3.24 AS build
# "server" builds toothspin-standalone (ToothSpin's own Sendspin server),
# which needs PyAV, numpy and Pillow: about 200 MB more.
ARG EXTRAS=""
# All dependencies ship musl wheels for amd64 and arm64, so no compilers.
RUN apk add --no-cache python3
COPY pyproject.toml /src/
COPY src /src/src
RUN python3 -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir "/src${EXTRAS:+[$EXTRAS]}" \
    && /opt/venv/bin/pip uninstall -y pip \
    && find /opt/venv -name __pycache__ -prune -exec rm -rf {} +

FROM docker.io/library/alpine:3.24
# The mode the image starts in: toothspin-standalone is built with
# MODE=standalone, so it needs no configuration for it.
ARG MODE=music-assistant
# PipeWire's camera plugin needs libcamera, which drags in Mesa and LLVM
# (~250 MB). Camera support is disabled (deploy/pipewire), so a stub package
# stands in for libcamera; the check fails the build should a new libcamera
# soname bring the real one back. Upgrade first: the base image lags behind
# Alpine's security fixes.
RUN apk mkpkg --output /tmp/no-camera.apk \
        --info name:toothspin-no-camera --info version:1-r0 --info arch:noarch \
        --info "description:Stands in for libcamera, PipeWire camera support is disabled" \
        --info license:GPL-3.0-or-later \
        --info "provides:so:libcamera.so.0.7=0 so:libcamera-base.so.0.7=0" \
    && apk add --no-cache --allow-untrusted /tmp/no-camera.apk \
    && rm /tmp/no-camera.apk \
    && apk upgrade --no-cache \
    && apk add --no-cache python3 pipewire wireplumber pipewire-spa-bluez pipewire-tools \
        pulseaudio-utils bluez-obexd dbus \
    && ! apk info -e libcamera mesa
# ToothSpin runs as this user. Started as root (Home Assistant), it hands its
# files to it and switches (src/toothspin/privileges.py). /data belongs to it,
# so a new Docker volume does too and `--user 1000:1000` needs no root.
RUN adduser -D -s /sbin/nologin -u 1000 toothspin \
    && install -d -o toothspin -g toothspin /data
COPY --from=build /opt/venv /opt/venv
COPY deploy/pipewire/*.conf /etc/wireplumber/wireplumber.conf.d/
COPY deploy/pipewire/pipewire.conf.d/*.conf /etc/pipewire/pipewire.conf.d/

# The commit the image is built from, shown in the web UI. Last, so a new
# commit only rebuilds this layer.
ARG GIT_COMMIT=""
ENV PATH=/opt/venv/bin:$PATH \
    TOOTHSPIN_COMMIT=${GIT_COMMIT} \
    DATA_DIR=/data \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    BUNDLED_PIPEWIRE=1 \
    MODE=${MODE} \
    XDG_RUNTIME_DIR=/tmp/runtime \
    XDG_STATE_HOME=/tmp/runtime/state
LABEL org.opencontainers.image.licenses="GPL-3.0-or-later" \
      org.opencontainers.image.source="https://github.com/eknoes/toothspin" \
      org.opencontainers.image.url="https://github.com/eknoes/toothspin"
VOLUME /data
CMD ["toothspin"]
