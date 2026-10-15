#!/bin/sh
# Try the working tree on a Home Assistant OS host without a release: build
# the image, load it there under the tag the installed App runs, restart it.
#
#   deploy/ha/dev-push.sh root@homeassistant.local [build-host]
#
# Needs SSH to the HA OS host on port 22222 (developer access, see
# https://developers.home-assistant.io/docs/operating-system/debugging).
# Builds with local podman/docker, or on [build-host] via SSH if given.
# Only the code changes: the App's config.yaml (options, permissions) still
# comes from the installed release. Undo by updating or reinstalling the App,
# or `docker pull <tag>` on the host and restarting it.
# SSH="ssh -i <key>" picks another ssh command.
set -eu

ha_host=${1:?usage: $0 root@<ha-host> [build-host]}
build_host=${2:-}
ssh=${SSH:-ssh}
ha() { $ssh -p 22222 "$ha_host" "$@"; }

slug=$(ha "docker ps --format '{{.Names}}'" | sed -n 's/^app_\(.*_toothspin\)$/\1/p' | head -1)
[ -n "$slug" ] || { echo "ToothSpin isn't running on $ha_host" >&2; exit 1; }
tag=$(ha "docker inspect app_$slug --format '{{.Config.Image}}'")
commit=$(git rev-parse --short HEAD)$(git diff --quiet HEAD -- src deploy Containerfile pyproject.toml || echo -dirty)
echo "Building $commit as $tag for $slug"

tree=$(mktemp -d)
trap 'rm -rf "$tree"' EXIT
# The working tree as it is, uncommitted changes included.
git ls-files -co --exclude-standard -z -- Containerfile pyproject.toml src deploy \
    | xargs -0 tar cf "$tree/src.tar"

if [ -n "$build_host" ]; then
    $ssh "$build_host" 'rm -rf ~/toothspin-dev && mkdir ~/toothspin-dev'
    $ssh "$build_host" "tar xf - -C ~/toothspin-dev && cd ~/toothspin-dev && podman build -q -t $tag --label dev.toothspin.commit=$commit . >/dev/null && podman save $tag" < "$tree/src.tar" \
        | ha 'docker load -q'
else
    mkdir "$tree/ctx" && tar xf "$tree/src.tar" -C "$tree/ctx"
    engine=$(command -v podman || command -v docker)
    "$engine" build -q -t "$tag" --label "dev.toothspin.commit=$commit" "$tree/ctx" >/dev/null
    "$engine" save "$tag" | ha 'docker load -q'
fi

ha "ha apps restart $slug >/dev/null 2>&1 || ha addons restart $slug >/dev/null"
# Drop earlier test builds this one replaced (the release image stays).
ha "docker image prune -f --filter label=dev.toothspin.commit >/dev/null"
echo "Restarted $slug on $(ha "docker inspect app_$slug --format '{{index .Config.Labels \"dev.toothspin.commit\"}}'")"
