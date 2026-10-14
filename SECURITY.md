# Security policy

## Reporting a vulnerability

Please report security vulnerabilities privately through GitHub: on the
repository's **Security** tab, choose **Report a vulnerability**
([direct link](https://github.com/eknoes/toothspin/security/advisories/new)).

Don't open a public issue, pull request or discussion for a vulnerability.
Include what is affected (version or image tag, Home Assistant App or plain
container), how to reproduce it and its impact as you understand it.

## Supported versions

Only the latest release receives security fixes.

## Scope

ToothSpin's web interface has no login of its own: as a Home Assistant App
it is protected by Home Assistant's ingress, otherwise (and on the App's
optional LAN port) it relies on the home network. Exposing it beyond a
trusted network is outside the supported setup.

Known vulnerabilities in the container image's packages are listed in the
vulnerability report of each CI run; the SBOMs are attached to every
release.
