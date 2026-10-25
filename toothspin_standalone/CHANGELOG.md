# Changelog

## 0.5.1 (2026-10-25)

### Fixes

- **server:** No skips when Bluetooth audio comes in bursts

### Documentation

- Diagram for both variants
- New screenshots with covers and taps
- Shorter comparison
- Rickrolling
- Site and README intro for both variants
- Covers, speaker groups and Standalone throughout
- Which Bluetooth adapters work

## 0.5.0 (2026-10-25)

### Features

- Ask for an update when Music Assistant speaks another Sendspin version
- **server:** Speaker groups that play as one speaker
- Covers from the phones

### Fixes

- **source:** Log the codec actually streamed
- **server:** Recognise older speakers again with aiosendspin 10
- **server:** Start again until mDNS works
- **server:** Play again on speakers that come back
- Connect phones' audio again after a restart
- **covers:** Start obexd so it keeps running
- **selinux:** Drop the rule for covers again

### Image and dependencies

- **deps-dev:** Bump ruff from 0.16.10 to 0.17.1
- Aiosendspin 10.2.0, as Music Assistant 2.10.7 ships
- Aiosendspin 10.2.1, as Music Assistant 2.10.8 ships

### Documentation

- Music Assistant 2.10.7 or newer
- Runs in a couple of homes by now
- List the hardware ToothSpin runs on
- ToothSpin or ToothSpin Standalone, side by side

## 0.4.0 (2026-10-20)

### Features

- **web:** Suggest putting ToothSpin on the home screen once a phone is paired
- **web:** Link help and issue reports at the bottom

### Fixes

- **server:** Play on the chosen speakers again after a long pause
- **server:** No silence for ToothSpin's own server

### Documentation

- **faq:** List all questions on top; home screen and long pause for standalone

## 0.3.0 (2026-10-18)

### Features

- Standalone mode with ToothSpin's own Sendspin server
- **app:** ToothSpin Standalone, a Home Assistant App for standalone mode
- **web:** Say which ToothSpin it is in the title
- **server:** Optional speaker buffer for standalone mode
- **server:** Show what the phone plays on speakers with a display
- Sum up dropouts per speaker and per phone after each session

### Fixes

- **setup:** Standalone mode's setup hints are about its own server
- **server:** Keep starting the Sendspin server until the network is up
- **server:** Say why standalone mode can't start next to Music Assistant
- **server:** One log line per older speaker instead of several warnings
- **web:** Log successful requests only at log level debug

### Image and dependencies

- A server image flavour for standalone mode
- Publish standalone mode as its own image, toothspin-standalone

### Documentation

- Drop the "Demo data" notes under the screenshots
- An "Install on Home Assistant" button at the top of the website
- **install:** Links to each way to install at the top
- Describe standalone mode
- **pages:** Standalone mode in the installation guide and FAQ
- Standalone mode as a small alternative to Music Assistant

## 0.2.1 (2026-10-17)

### Fixes

- **app:** Let Home Assistant's init stop ToothSpin cleanly

### Documentation

- **app:** A changelog for Home Assistant's update dialog

## 0.2.0 (2026-10-17)

### Features

- **capture:** Log when a phone's audio comes late
- **bluez:** Option to refuse pairing on the host's other adapters
- Run as an unprivileged user, not root
- **app:** Read the App's options from the Supervisor's API
- Run with Docker's --user, without any capabilities

### Fixes

- **web:** Shorter setup texts and confirmations
- **web:** Don't reconnect on a second tap of a slow Disconnect
- **web:** Refuse POSTs other websites can send
- **bluez:** Only let paired phones connect by themselves
- **web:** Check every request field strictly
- **app:** Let AppArmor allow only BlueZ on the host's D-Bus
- Say how to hand over /data when it belongs to another user
- Refuse a runtime folder that isn't ToothSpin's own

### Documentation

- **app:** Call the start volume option "Maximum start volume", explain it better
- **app:** Shorter, clearer option descriptions, store page and docs
- Shorter FAQ, install guide and README usage
- **faq:** Why only AAC and SBC, no aptX or LDAC

## 0.1.5 (2026-10-15)

### Features

- **app:** Run under its own AppArmor profile
- **app:** Run without the host network
- **web:** Show the running version and commit at the bottom, with a link

### Fixes

- **bluez:** Connect a freshly paired phone if its own connection broke down
- **bluez:** Refuse headset and hands-free connections from phones
- **source:** Keep the speakers through a pause on the phone
- **capture:** Keep the signal through a pause, so Music Assistant doesn't stop
- Reconnect the phones a restart dropped
- **source:** Back off and warn when the server keeps dropping the connection
- **speakers:** Let a speaker finish leaving a group before starting it again
- **speakers:** Report it when Music Assistant doesn't group a speaker

### Documentation

- **faq:** How to put ToothSpin on a phone's home screen
- **faq:** Speakers after a long pause, a known limitation
- The App without host network, the web UI port in Network
- **faq:** Speakers that won't group, usually a stale device in Music Assistant

## 0.1.4 (2026-10-15)

### Features

- **web:** Show "Disconnecting…" until a phone is disconnected
- **ma:** Check Music Assistant's version and ask for an update if too old
- **app:** Take Bluetooth audio from Home Assistant's audio service, with consent

### Fixes

- **web:** Skip speaker clicks a newer one replaced, explain timeouts
- **web:** Clicks no longer get lost on re-render; the setup box opens on click
- **ma:** Answer Music Assistant 2.11's new steps when pairing
- **bluetooth:** Offer phones only AAC and SBC

### Documentation

- Which Music Assistant versions work, and why
- Home Assistant's audio service and the codecs offered

## 0.1.3 (2026-10-14)

### Features

- **setup:** A light Finish setup card with links into Home Assistant
- **app:** A sidebar icon closer to the logo (mdi:home-sound-in)

### Image and dependencies

- **deps:** Bump dbus-fast to 5.2.0
- **coreos:** Use Butane spec 1.7.0

### Documentation

- Screenshots of the setup card and a demo GIF

## 0.1.2 (2026-10-14)

### Fixes

- **web:** Italics and plain lists in setup instructions

### Documentation

- **pages:** Installation guide and FAQ
- Link the installation guide and FAQ from the App and notifications
- **faq:** Why Music Assistant shows no track metadata

## 0.1.1 (2026-10-14)

### Features

- **setup:** Check adapter and Music Assistant setup, show what to do
- **app:** Show ToothSpin in Home Assistant's sidebar on first start
- **web:** Show speaker changes at once, without waiting for a refresh

### Fixes

- **web:** Queue speaker changes so quick clicks don't plan from stale groups

### Documentation

- **app:** Installation steps on the store page, setup checks

## 0.1.0 (2026-10-14)

### Features

- **web:** Show the phone's track info from AVRCP
- Give each paired phone its own Sendspin source
- Report manufacturer and version to Music Assistant
- **web:** Rename a phone's input in Music Assistant
- **web:** Toggle Music Assistant speakers per phone
- **bluez:** Only accept connections started from the receiver
- **web:** List speakers with volume and mute
- **web:** Add a Connect button for disconnected phones
- **web:** Show the input name as the card title
- **web:** Make the web UI an installable app
- **web:** Keep my phone on top
- **web:** Move 'Add phone' and the Bluetooth name to the bottom
- **container:** Bundle PipeWire in a minimal Alpine image
- **web:** Use the ToothSpin icon and color palette
- **web:** Use the Sendspin red as the accent color
- **web:** Use relative URLs so the UI works below a path prefix
- **ma:** Find Music Assistant via mDNS when no URL is given
- Run as a Home Assistant App
- Add the Home Assistant App
- **web:** Hide speakers per phone
- **bluez:** Track phone transports and set a phone's volume
- Control the speaker's volume from the phone
- **deploy:** Confine the container instead of disabling SELinux
- **deploy:** Provision the CoreOS machine completely on first boot
- **web:** Move a phone to one speaker in one go
- **bluez:** Optionally let phones connect by themselves
- Pair phones with Music Assistant automatically
- **bluez:** Pair with a fixed PIN (BT_PIN)
- **web:** Say "Fixed volume" for speakers without volume control
- **web:** Show errors as a toast, and when a phone is reconnected
- **volume:** Keep a speaker's volume by default (START_VOLUME=100)
- **bluez:** Let phones connect by themselves by default
- Name the Bluetooth adapter ToothSpin by default

### Fixes

- **capture:** Pick up the phone's PipeWire capture node
- **pipewire:** Acquire every phone stream without a consumer
- Shut down cleanly on SIGTERM
- **receivers:** Keep a phone's Sendspin identity when it vanishes from BlueZ
- **web:** Forget a phone's Sendspin identity when it's removed
- **bluez:** Disconnect phones that connect on their own
- **web:** Base the streaming label on Music Assistant's request
- **source:** Say goodbye with RESTART so Music Assistant resumes the input
- **web:** Offer PNG icons so Firefox for Android uses them
- **ha:** Log App mode after logging is set up and accept any JSON content type
- **bluez:** Only apply the agent's policy to our own adapter
- **deploy:** Let PipeWire use the phones' Bluetooth sockets
- **volume:** Never start a speaker loud when a phone starts on it
- **volume:** Turn a speaker with unknown volume down before starting
- **deploy:** Switch Secure Simple Pairing back on without --pin
- **source:** Keep a speaker chosen before the phone plays
- **bluez:** Reconnect a phone that keeps playing on its own speaker
- **volume:** Leave speakers without volume control alone
- **bluez:** Give a stuck phone time before reconnecting it
- **bluez:** Let Connect win over an automatic reconnect

### Image and dependencies

- **bluetooth:** Add an installer for the BlueZ config
- Drop numpy and av from the runtime dependencies
- Base the image on Alpine 3.23 and upgrade its packages
- Add the repository URL to the package and image metadata
- Move the image to Alpine 3.24

### Documentation

- Describe the PipeWire-based setup
- Document per-phone sources and pairing
- Document SENDSPIN_MANUFACTURER and renaming
- Document speaker control and MA_URL/MA_TOKEN
- Document that connections start from the receiver
- Document the self-contained image and plain Docker setup
- **coreos:** Drop PipeWire from the host packages
- List third-party licenses and their sources
- Add a GitHub Pages site
- Build the Pages site with Jekyll
- Describe the release process
- Show the web UI on the Pages site
- Document the Home Assistant App and update the architecture
- **app:** Note that the audio stack covers every adapter
- Add a security policy
- Describe hidden speakers, phone volume and the SBOM
- Rewrite the README intro, move the details elsewhere
- Say how ToothSpin is reviewed and tested
- Explain the design decisions and the ways to install
- Describe automatic pairing and BT_PIN

### Refactor

- Rename the project to ToothSpin


