# Proxmox deployment record

16 October 2026. Node `pve`; all changes limited to the dedicated guest and required host `iw` package. No existing guest was repurposed.

## Provisioned configuration

- CT 114, `ezsharecpap`: Debian 13, unprivileged, 1 CPU, 1024 MiB RAM, 16 GiB root disk on `local-zfs`, on boot enabled.
- Nesting/keyctl enabled for Docker with explicit user approval.
- LAN `eth0` on `vmbr0`, DHCP address `192.168.8.104`, gateway and DNS `192.168.8.1`.
- Physical `wlp1s0` assigned using `lxc.net.1.type: phys`, `lxc.net.1.link: wlp1s0`, and `lxc.net.1.name: wlp1s0`.
- Realtek RTL8822CE Wi-Fi, host driver `rtw88_8822ce`. Host `iw` installed because LXC requires it to move wireless hardware.
- NetworkManager manages the wireless connection, `ezshare-card`. Ethernet is unmanaged by NetworkManager; `dns=none` preserves Proxmox-managed LAN DNS. The card network has no default route and supplies no DNS.
- Source revision `a4e0484` installed in `/opt/ezsharecpap`; Docker images built locally. No GitHub publication was required.
- Guest setup/build logs are in `/root/ezshare-setup.log` and `/root/ezshare-build.log`. Initial download is supervised by `ezshare-initial-sync.service` and Docker container `ezshare-initial-sync`.
- Startup sync is initially disabled. The daily schedule remains 10:00 Australia/Melbourne, configurable in the GUI after startup.

## Verified on target

- LAN route, DNS restoration, and card directory reachability.
- Physical Wi-Fi assignment and automatic association survive a full guest shutdown/start.
- Both downloader and Samba images built successfully.
- Downloader image executes inside Docker in the unprivileged LXC.

## Pending

- Complete and inspect the first real download result.
- Owner completed web/SMB password setup and started Compose. Passwords are not stored in Git. Both services are running; the downloader reports healthy.
- Web login and scheduler health are verified. Authenticated read-only SMB and a local OSCAR import still need acceptance testing.
- Reserve the DHCP address, confirm Proxmox backup coverage, and test a future host reboot during an agreed maintenance window. No host reboot was performed.


## Live progress update

Revision `a68cb4d` is deployed. The authenticated dashboard polls live status every two seconds and shows the current phase, directory discovery counts, file download counts/percentage, per-file bytes when available, and elapsed/update times. Scanning, planning and verification have indeterminate progress. Telemetry writes are nonfatal and interrupted unlocked runs are recoverable. Local suite: 64 passing tests; independent review found no remaining important issue after fixes. Live HTTP validation confirmed scanning counters advance on the target. Rendered QA for this update was blocked by the unresponsive browser-control connection.

The first run found 9,473 candidate files. Its old process was stopped gracefully and replaced with the instrumented version while retaining the working archive. It now uses `/config/initial-sync.json` with a separate 86,400-second limit under `ezshare-bootstrap-progress.service`; regular `/config/server.json` keeps the 1,800-second daily limit. First-run publication is still pending. Both Compose services are running; the downloader is healthy. Reboot recovery of this transient initial-sync job is not claimed.


## Page artwork and download ETA

Web image revision `cb39f7b` adds a transparent illustration derived from the app icon, without its rounded-square tile, and a client-side download ETA. The initial-sync container remains on its existing instrumented image and was not restarted. The ETA uses existing live counters, waits for 30 seconds and five completed files, and resets when the run, phase or total changes. Network errors replace the estimate with a waiting message. It excludes subsequent verification and publication.

Validation: 65 Python tests and 5 Node ETA tests pass. Authenticated HTTP checks verify the module MIME type and exact deployed PNG. The browser-control connection remains unavailable, so a rendered-page check is not claimed for this update. No credentials or server network permissions changed.

## ETA diagnostic check

The first download was completing roughly one file every three seconds with about 9,000 files remaining. Three small root-file requests showed multi-second delays while local fsync tests took approximately 2 to 9 milliseconds. A short Wi-Fi power-save-off comparison showed no clear immediate improvement, and power saving was restored to its prior on setting. These small concurrent samples do not establish a complete throughput benchmark.

Web revision `a91d4b2` labels estimates from fewer than three minutes or 30 observed completed files as early and displays measured files per minute. It does not lower the numerical ETA without evidence. All 65 Python and 6 Node tests pass. The bootstrap container was not restarted, and authenticated HTTP checks confirm the deployed assets.

## Local archive import and snapshot download

The dashboard now accepts complete SD-folder ZIP uploads and downloads the latest completed snapshot as a ZIP. Imports validate the full ZIP and matching device identification, preserve existing files, and share the sync lock. Archive preparation is serialized and interrupted temporary files are recovered. Case-insensitive filename matching lets existing Mac downloads be reused on Linux. ZIP wall-clock timestamps are normalized to the server's card parser.

Wi-Fi power saving is now disabled persistently for ezshare-card at the owner's request. A short comparison did not establish a meaningful speed improvement.

One-off seed transfer completed over SSH. The source ZIP contained 8,443 eligible files and matched the server's device identification. Import added 7,605 files and retained 838 existing files. The initial sync resumed under ezshare-bootstrap-seeded.service with the new image and existing 86,400-second initial-run limit. Authenticated HTTP checks confirmed the upload/download controls, import result and advancing directory scan. Download correctly returns 404 while no completed snapshot exists. Rendered browser testing remains unavailable because the browser-control connection is unresponsive.

Validation: 85 Python tests and 6 Node ETA tests passed, including ZIP corruption/path checks, cancellation, transfer serialization, cleanup and upload-body limits. Independent code review found no remaining important issue in the changes.


## Reliability and usability implementation, 17 October 2026

Implemented in the isolated codex/server-reliability branch: storage reservations and previewed retention, seeded/publication status, file-boundary stop and persistent pause, restart recovery, shared timezone scheduling, explicit SMB host/Finder access and optional guest Wi-Fi telemetry. Automatic retention remains disabled by default.

Independent review identified cancelled-upload lease cleanup, stale recovery admission, an absolute file deadline and IPv6 zone validation issues. Each was reproduced and corrected with regression coverage. Additional checks cover duplicate Resume admission, consumption of an already-due schedule slot and mandatory retention preview. A real Waitress multipart upload validates the ingress reservation lifecycle. A real service process test verifies recovery, seeded-file reuse, publication and no duplicate run after the next restart.

Rendered local browser checks passed at desktop and 390-pixel width with no JavaScript exceptions or horizontal overflow. Schedule preview works and polling preserves unsaved time edits. Browser plugin was unavailable; checks used the installed Playwright runtime. Finder protocol handoff and OSCAR import remain owner acceptance checks.

After the owner renewed Tailscale authentication, the update was built and deployed in CT 114. Source revision ef630b5 produced image sha256:a72deb287ade3b4e42a814645da4fdf601a585ab797e1c17a90e2deda616d111. The previous image is retained as ezsharecpap-downloader:before-reliability, and configuration/state backups are under /root/ezshare-reliability-backup in the guest.

A restricted-container smoke test with separate synthetic data passed publication, ZIP export, authentication and old-configuration loading. The production downloader is healthy. The existing startup-sync setting was true, so service startup initiated a sync; the previous 9,473-file completed snapshot stayed available throughout. Automatic retention remains disabled, with all existing snapshots preserved.

The optional Wi-Fi collector timer is active inside CT 114, and its JSON directory is mounted read-only into the downloader. The live dashboard reports connected Wi-Fi, fresh signal/link-rate samples and unchanged power saving off. No network privileges or Wi-Fi settings were changed.

Authenticated live HTTP and Playwright checks verified controls, connection-script address, schedule preview, retention preview, saved-draft preservation, desktop rendering and 390-pixel layout without page errors or horizontal overflow. The mounted /Volumes/CPAP share independently shows current and dated snapshots, including current/Identification.tgt. The preview lists two older snapshots for a keep count of two; no cleanup was executed. The next scheduled run is 18 October 2026 at 10:00 Australia/Melbourne.

Validation totals: 125 Python tests and 9 Node tests passed. Native Finder protocol confirmation and an actual OSCAR import remain owner acceptance checks. Changes are available in draft PR 1 of the standalone server repository.
