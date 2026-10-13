# Licensing

ToothSpin is free software, licensed under the
[GNU General Public License v3.0 or later](LICENSE) (`GPL-3.0-or-later`).

The container image also bundles third-party software under its own
licenses. None of it is modified. This file lists it and where to get its
source.

## Container image

The image is built from unmodified **Alpine Linux 3.22** packages
([Containerfile](Containerfile)). For any package:

- package page (version, license, upstream URL):
  `https://pkgs.alpinelinux.org/packages?branch=v3.22&name=<package>`
- build recipe and patches:
  [aports, branch `3.22-stable`](https://gitlab.alpinelinux.org/alpine/aports/-/tree/3.22-stable),
  directory `<repository>/<origin>`
- original source tarballs:
  [distfiles.alpinelinux.org/distfiles/v3.22](https://distfiles.alpinelinux.org/distfiles/v3.22/)

### GPL, LGPL and MPL components

Grouped by Alpine source package (origin). Licenses as declared by Alpine.

| Origin | Installed packages | License |
|---|---|---|
| [alpine-baselayout](https://pkgs.alpinelinux.org/packages?branch=v3.22&name=alpine-baselayout) | alpine-baselayout, alpine-baselayout-data | GPL-2.0-only |
| [alsa-lib](https://pkgs.alpinelinux.org/packages?branch=v3.22&name=alsa-lib) | alsa-lib | LGPL-2.1-or-later |
| [apk-tools](https://pkgs.alpinelinux.org/packages?branch=v3.22&name=apk-tools) | apk-tools, libapk2 | GPL-2.0-only |
| [avahi](https://pkgs.alpinelinux.org/packages?branch=v3.22&name=avahi-libs) | avahi-libs | LGPL-2.1-or-later |
| [bluez](https://pkgs.alpinelinux.org/packages?branch=v3.22&name=bluez-libs) | bluez-libs | GPL-2.0-or-later AND BSD-2-Clause AND MIT |
| [busybox](https://pkgs.alpinelinux.org/packages?branch=v3.22&name=busybox) | busybox, busybox-binsh, ssl_client | GPL-2.0-only |
| [ca-certificates](https://pkgs.alpinelinux.org/packages?branch=v3.22&name=ca-certificates-bundle) | ca-certificates-bundle | MPL-2.0 AND MIT |
| [dbus](https://pkgs.alpinelinux.org/packages?branch=v3.22&name=dbus-libs) | dbus-libs | AFL-2.1 OR GPL-2.0-or-later |
| [eudev](https://pkgs.alpinelinux.org/packages?branch=v3.22&name=eudev-libs) | eudev-libs | GPL-2.0-or-later |
| [flac](https://pkgs.alpinelinux.org/packages?branch=v3.22&name=libflac) | libflac | BSD-3-Clause AND GPL-2.0-or-later |
| [gcc](https://pkgs.alpinelinux.org/packages?branch=v3.22&name=libgcc) | libgcc, libstdc++ | GPL-2.0-or-later AND LGPL-2.1-or-later |
| [gdbm](https://pkgs.alpinelinux.org/packages?branch=v3.22&name=gdbm) | gdbm | GPL-3.0-or-later |
| [gettext](https://pkgs.alpinelinux.org/packages?branch=v3.22&name=libintl) | libintl | LGPL-2.1-or-later |
| [glib](https://pkgs.alpinelinux.org/packages?branch=v3.22&name=glib) | glib | LGPL-2.1-or-later |
| [gmp](https://pkgs.alpinelinux.org/packages?branch=v3.22&name=gmp) | gmp | LGPL-3.0-or-later OR GPL-2.0-or-later |
| [gnutls](https://pkgs.alpinelinux.org/packages?branch=v3.22&name=gnutls) | gnutls | LGPL-2.1-or-later |
| [lame](https://pkgs.alpinelinux.org/packages?branch=v3.22&name=lame-libs) | lame-libs | LGPL-2.0-or-later |
| [libcamera](https://pkgs.alpinelinux.org/packages?branch=v3.22&name=libcamera) | libcamera, libcamera-ipa | LGPL-2.1-or-later AND GPL-2.0-or-later |
| [libfreeaptx](https://pkgs.alpinelinux.org/packages?branch=v3.22&name=libfreeaptx) | libfreeaptx | LGPL-2.1-or-later |
| [libidn2](https://pkgs.alpinelinux.org/packages?branch=v3.22&name=libidn2) | libidn2 | GPL-2.0-or-later OR LGPL-3.0-or-later |
| [libsndfile](https://pkgs.alpinelinux.org/packages?branch=v3.22&name=libsndfile) | libsndfile | LGPL-2.1-or-later |
| [libtasn1](https://pkgs.alpinelinux.org/packages?branch=v3.22&name=libtasn1) | libtasn1 | LGPL-2.1-or-later |
| [libunistring](https://pkgs.alpinelinux.org/packages?branch=v3.22&name=libunistring) | libunistring | GPL-2.0-or-later OR LGPL-3.0-or-later |
| [libusb](https://pkgs.alpinelinux.org/packages?branch=v3.22&name=libusb) | libusb | LGPL-2.1-or-later |
| [mpg123](https://pkgs.alpinelinux.org/packages?branch=v3.22&name=mpg123-libs) | mpg123-libs | LGPL-2.1-only |
| [musl](https://pkgs.alpinelinux.org/packages?branch=v3.22&name=musl-utils) | musl-utils | MIT AND BSD-2-Clause AND GPL-2.0-or-later |
| [nettle](https://pkgs.alpinelinux.org/packages?branch=v3.22&name=nettle) | nettle | GPL-2.0-or-later OR LGPL-3.0-or-later |
| [pax-utils](https://pkgs.alpinelinux.org/packages?branch=v3.22&name=scanelf) | scanelf | GPL-2.0-only |
| [pipewire](https://pkgs.alpinelinux.org/packages?branch=v3.22&name=pipewire) | pipewire, pipewire-libs, pipewire-spa-bluez, pipewire-tools | LGPL-2.1-or-later |
| [readline](https://pkgs.alpinelinux.org/packages?branch=v3.22&name=readline) | readline | GPL-3.0-or-later |
| [roc-toolkit](https://pkgs.alpinelinux.org/packages?branch=v3.22&name=roc-toolkit-libs) | roc-toolkit-libs | MPL-2.0 |
| [sbc](https://pkgs.alpinelinux.org/packages?branch=v3.22&name=sbc) | sbc | GPL-2.0-or-later AND LGPL-2.1-or-later |
| [util-linux](https://pkgs.alpinelinux.org/packages?branch=v3.22&name=libblkid) | libblkid, libmount | LGPL-2.1-or-later |
| [wireplumber](https://pkgs.alpinelinux.org/packages?branch=v3.22&name=wireplumber) | wireplumber, wireplumber-libs | LGPL-2.1-or-later |
| [xz](https://pkgs.alpinelinux.org/packages?branch=v3.22&name=xz-libs) | xz-libs | GPL-2.0-or-later AND 0BSD AND Public-Domain AND LGPL-2.1-or-later |

### Other Alpine packages

| License | Packages |
|---|---|
| Apache-2.0 | abseil-cpp, liblc3, libldac, openssl (libcrypto3, libssl3) |
| BSD-2-Clause | mpdecimal |
| BSD-3-Clause | libogg, libvorbis, opus, p11-kit, pcre2, speexdsp |
| ISC | lilv, serd, sord, sratom, zix |
| MIT | alpine-keys, alpine-base, expat, libeconf, libffi, libunwind, libuv, lua5.4, musl, yaml |
| PSF-2.0 | python3 |
| X11 | ncurses |
| Zlib | zlib |
| bzip2-1.0.6 | bzip2 |
| blessing (public domain) | sqlite |
| custom (BSD-style, see package) | webrtc-audio-processing-2 |
| FDK-AAC | fdk-aac, see below |

### fdk-aac

PipeWire's Bluetooth plugin (`pipewire-spa-bluez`) links
[fdk-aac](https://pkgs.alpinelinux.org/packages?branch=v3.22&name=fdk-aac)
for AAC. Its license (FDK-AAC) is free, but the FSF considers it
GPL-incompatible. ToothSpin doesn't link it: PipeWire runs as its own
process and ToothSpin only reads audio from it through `pw-record`. The
image bundles the two as separate programs. fdk-aac's license text is the
`NOTICE` file in its source; among other things, it forbids charging
copyright license fees for fdk-aac.

## Python packages

Installed from PyPI into `/opt/venv` in the image. None of them is
modified; sources are on [PyPI](https://pypi.org) and the linked
repositories.

| Package | License |
|---|---|
| [zeroconf](https://github.com/python-zeroconf/python-zeroconf) | LGPL-2.1-or-later |
| [orjson](https://github.com/ijl/orjson) | MPL-2.0 AND (Apache-2.0 OR MIT) |
| [aiosendspin](https://github.com/Sendspin/aiosendspin) | Apache-2.0 |
| aiohttp | Apache-2.0 AND MIT |
| aiosignal, cpace, frozenlist, mashumaro, multidict, propcache, yarl | Apache-2.0 |
| cryptography | Apache-2.0 OR BSD-3-Clause |
| idna, pycparser | BSD-3-Clause |
| attrs, dbus-fast, ifaddr, noiseprotocol | MIT |
| cffi | MIT-0 |
| aiohappyeyeballs, typing_extensions | PSF-2.0 |

The optional `codecs` extra (FLAC/Opus, not in the image) adds
[PyAV](https://github.com/PyAV-Org/PyAV) (BSD-3-Clause), whose wheels bundle
an FFmpeg build that includes GPL libraries (x264, x265), and numpy
(BSD-3-Clause and others).

## Not distributed

BlueZ's `bluetoothd` runs on the host (GPL-2.0-or-later). ToothSpin talks to
it over D-Bus and doesn't ship it.
