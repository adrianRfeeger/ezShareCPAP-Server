# Deploy ezShareCPAP on Proxmox

This version has a password-protected web interface for status, manual downloads, daily scheduling, and the last 20 run results. Samba provides a separate read-only share for OSCAR imports.

## Software and host setup

Use a dedicated Debian LXC with a LAN interface on `vmbr0` and the unused Wi-Fi card assigned to it. The LXC needs Docker Engine, the Docker Compose plugin, and a Wi-Fi manager such as NetworkManager with wpa_supplicant. Install Docker using the [official Debian instructions](https://docs.docker.com/engine/install/debian/). Docker supplies the Python and Samba environments from this repository. Docker Desktop on the Mac is unnecessary.

Docker inside an unprivileged LXC needs the relevant nesting/keyctl features. Confirm the actual wireless-interface or PHY assignment method for this hardware; adding a generic device entry does not establish Wi-Fi control. Keep the host Ethernet connection and management route unchanged. A dedicated VM remains the fallback if the LXC cannot run this configuration with the intended isolation.

Install `iw` on the Proxmox host before starting an LXC with a physical wireless interface assigned; LXC uses it to move the wireless device. Keep the host kernel driver loaded. The tested RTL8822CE card uses `rtw88_8822ce`.

Configure only the assigned wireless interface to join the ez Share access point. Keep the LAN as the default route and DNS source. With an unmanaged LAN interface, prevent NetworkManager from overwriting resolv.conf with an empty file. The tested configuration in `/etc/NetworkManager/conf.d/10-ezshare-lan.conf` is:

```ini
[main]
dns=none
[keyfile]
unmanaged-devices=interface-name:eth0
```

Set the LXC DNS server through Proxmox and verify `/etc/resolv.conf` contains it. Reload NetworkManager after changing its configuration. Configure the card connection with `ipv4.never-default=yes`, `ipv4.ignore-auto-dns=yes`, and IPv6 disabled if the card does not use it.

Keep the LAN as the default route and DNS source. The wireless interface should route the card subnet only. Confirm the LXC can reach `http://192.168.4.1/dir?dir=A:` and still reach the LAN. Verify recovery after the card loses power and the LXC restarts.

The web interface does not configure Wi-Fi. This remains an LXC administration task.

## Prepare the checkout

Copy this branch's repository contents to a directory in the LXC, for example `/opt/ezsharecpap`. In that directory:

```sh
mkdir -p config secrets data/state data/work data/published
cp server.example.json config/server.json
cp .env.example .env
```

Reserve the LXC address in your router's DHCP configuration, or use a verified static address, before relying on unattended service startup. Compose binds ports to this address.

Edit `.env` to set `LAN_IP` to the dedicated LXC's LAN address, not the Proxmox host address. Use the downloader account's numeric UID/GID for `PUID` and `PGID`; the defaults are 1000/1000. Ensure that account can write `config` and `data`. For those defaults:

```sh
chown -R 1000:1000 config data
chmod 750 config data
```

Create `secrets/web_password` and `secrets/smb_password`, each containing a different password on one line. The web password must be at least 16 characters. Store both in your password manager. Restrict the files:

```sh
chmod 700 secrets
chown 1000:1000 secrets/web_password
chmod 400 secrets/web_password
chmod 600 secrets/smb_password
```

Use the chosen PUID/PGID instead of 1000:1000 above if you changed them. Compose file-backed secrets retain source ownership, so the downloader account must be able to read its web password. Samba runs as root at startup and can read its separate root-owned secret. Compose mounts these secret files read-only. The web password is read at startup, so restart the downloader after changing it. The Samba account is recreated from its secret at startup.

Edit `config/server.json` before first launch. The default schedule is 10:00 in Australia/Melbourne, with a run on startup. Set `run_on_startup` to false if you want to verify connectivity before downloading. `timeout` bounds the download, retry and snapshot-building window in seconds. Copies check the deadline between chunks; a blocked filesystem call may still need container termination. Snapshot copying also requires sufficient disk space. `attempts` and `retry_delay` control bounded retries within it.

## Use published images

Use [the public-image installation guide](container-images.md) to install without a source build. In an existing checkout, `docker compose -f compose.release.yaml pull` and `docker compose -f compose.release.yaml up -d` use the same configuration, data and secret mounts.

## Build and start

```sh
docker compose config --quiet
docker compose build
docker compose up -d
docker compose ps
docker compose logs --tail=100 downloader samba
```

Open `http://<LXC-LAN-IP>:8080` and sign in as `admin` with the web password. The browser uses HTTP Basic authentication. Put HTTPS in front of this service before using it over an untrusted network; existing Tailscale HTTPS or a reverse proxy can provide that. Do not expose its port directly to the internet. Samba listens on TCP 445 at the specified LAN address. Check guest and Proxmox firewall rules for both ports.

The GUI displays the last successful publication separately from the last attempt. It does not report Wi-Fi signal strength or configure the card. The status area updates every two seconds without overwriting schedule edits. It shows directory discovery during scanning, file counts and percentage during downloading, and current actions during verification and snapshot publication. The download ETA appears after at least 30 seconds and five observed file completions. It uses up to five minutes of recent file progress, includes pauses in that observed rate, and resets when the run or phase changes. It is approximate because files vary in size. It estimates downloading only; verification and snapshot preparation follow. Scanning and verification do not show a time estimate. Reloading the page starts a new observation window. Schedule edits are persisted and picked up within 15 seconds when the scheduler is idle; an active run finishes with its existing settings.

For a manual download from the terminal:

```sh
docker compose exec downloader python server.py --config /config/server.json sync
docker compose exec downloader python server.py --config /config/server.json status
```

These commands share the same filesystem lock as the web button and scheduler. Exit 75 means another run holds the lock. Exit 1 means a download/publication failed; exit 2 means a configuration or filesystem error.

## Import on your computer

Mount `smb://<LXC-LAN-IP>/CPAP` using username `cpap` and the SMB password. Choose a dated completed snapshot folder in OSCAR's CPAP card import flow. Keep the local OSCAR profile and database on your computer.

The `current` link is a convenience for browsing. A dated folder keeps an import fixed while new data arrives. The share is read-only at both the Samba setting and mount layers. Snapshot files are copies rather than hard links. Failed downloads do not replace `current`.

Automatic retention is disabled by default. Preview cleanup in the dashboard before enabling it, then choose how many completed snapshots to retain (default two). Cleanup never deletes `current` or the working archive. Dated snapshots outside the retained set expire; avoid importing them during cleanup. When retention is disabled, snapshots remain until an explicit cleanup. Monitor storage use. This release does not automatically delete archive files when the card deletes them. Use a separate data directory when changing cards or machines.

If OSCAR cannot select or read the network directory correctly, copy a completed dated snapshot to your computer and import from there. Validate one real session before relying on unattended downloads.

## Scheduling and status

A run after startup is configurable. After the daily time, the scheduler performs one due run for the current local date and does not replay all missed dates. The attempted scheduled date is persisted before downloading, so a failed attempt is retried only within its configured window; manual sync remains available afterward. A crash during that window does not cause an unbounded replay on restart. An enabled startup run may still run again after a restart.

For a time skipped by daylight saving, the run occurs at the first valid local time after it. A repeated local time gets one scheduled attempt. Changing the schedule after that day's attempt takes effect on the next local date.

Container health measures scheduler liveness, not whether the card is reachable or data is fresh. Check the GUI's last success and any failure message. Run results are capped at 20; container logs rotate separately. Logs may contain card filenames and network addresses. The application does not send notifications.

The downloader compares card listings before and after a run, including any size text the card supplies. It rejects malformed listings, cycles, unsafe names, and observed changes. Listings with no anchors are rejected conservatively until a real empty-card format is validated. The card does not provide transactional snapshots: changes that leave identical listing metadata cannot be detected reliably. Schedule after therapy finishes.

## Backups, upgrades and recovery

Back up `config`, `data`, and the secret files using an access-controlled backup. Verify the actual Proxmox backup job includes their storage. Host bind mounts are not automatically included merely because the LXC itself is backed up. Hardware assignment also needs to be documented separately.

Before upgrading, record the repository revision and take a recoverable backup. Rebuild the images and recreate the services. Mounts preserve settings, archive files and published snapshots. To roll back, restore the previous code/images and, if necessary, the associated configuration backup. Test restores in a separate directory or guest.

After a power loss, the last fully published dated folder remains the import source. The next download cleans identified partial temporary files before running. Investigate a stale running status after a crash; the next run updates it. Never use the private `data/work` directory as an OSCAR import source.

## Validation status

Local Python tests and a simulated HTTP card exercise download, subprocess execution, persistence and publication. The GUI has been checked in a browser, including schedule saving. Docker image builds, nested Docker, Wi-Fi assignment, SMB access, host reboot recovery and real OSCAR imports still require testing on the target server and client. These are deployment acceptance checks, not claims established by the Python suite.

## Importing and downloading SD files

The web page's Local files section accepts a ZIP of the complete SD folder, up to 4 GB (8 GB expanded). Include Identification.tgt at the root, or inside one enclosing folder. Import is available while sync is idle. The importer checks ZIP paths, file integrity and device identification before adding missing files to the working archive. Existing server files are kept. Run Sync now afterward to fetch missing or changed card files and publish a verified snapshot.

Download latest completed SD folder creates a ZIP from the published snapshot. Extract it locally and select that folder in OSCAR. The button becomes available after the first successful sync. Upload and archive preparation are serialized, temporary files are cleaned after interruption, and normal web authentication applies to both actions. ZIP uploads use their stored wall-clock timestamps so the server can compare them with card timestamps.

On a Mac, the Import into OSCAR section also provides a connection-script ZIP. Extract it and open Connect-CPAP.command to open the CPAP share in Finder. The script uses the dashboard's hostname without its web port and signs in as cpap; macOS prompts for the SMB password. It contains no credentials beyond the username. Select the current folder or a dated snapshot in OSCAR.


## Storage, stopping and recovery

The dashboard reports free space, working archive size and completed snapshot size. Category totals refresh in the background once per minute. File transfers, import extraction, snapshot publication and exports reserve disk space before writing; the default reserve is 1 GiB. Upload admission budgets the incoming request, multipart spool and saved ZIP before the body is buffered. An archive below the 4 GB upload limit can still be rejected if the disk cannot accommodate these temporary copies and its expanded contents.

To enable retention, choose a count, select Preview cleanup, review the snapshot names, then enable deletion and save settings. A changed snapshot set requires a new preview. Manual cleanup also requires a preview matching the saved count. A failed download preserves the previous completed snapshot. Space checks do not delete old snapshots to force a new copy to fit.

Stop after current file preserves completed files and pauses scheduled runs. Resume starts a fresh card scan and reuses complete cached files. A partial file starts again from the beginning. The server enforces a five-minute absolute file deadline from the supervising process, including a card response that trickles data too slowly for ordinary socket timeouts to help.

An interrupted run resumes once when the app restarts, even when Also download when the service starts is off. An intentional user pause survives restart. A first sync with no published snapshot uses the initial-sync timeout, while later runs retain the normal timeout. A manual run or resume consumes an already-due daily slot so the scheduler does not immediately repeat it.

Additional server.json settings (existing files receive these defaults):

```json
{
  "retention_enabled": false,
  "retention_keep": 2,
  "storage_reserve_bytes": 1073741824,
  "resume_interrupted": true,
  "initial_sync_timeout": 86400,
  "smb_host": ""
}
```

The next run, recent history and last success use the configured timezone. The page warns after two consecutive failed scheduled runs or when a completed snapshot is more than 36 hours old. These are dashboard warnings; no messages are sent to external services.

Set SMB server hostname or IP when the browser address differs from the address used for file sharing, such as behind a web proxy. Enter the hostname or IP only, without a port or URL scheme. Both Open in Finder and the connection-script ZIP use that setting. A previously downloaded script keeps its original address; download a fresh copy after changing it.

## Optional Wi-Fi diagnostics

The app can show guest Wi-Fi link information without controlling the interface or receiving extra Docker permissions. The collector is optional; card downloads work without it. The connection check button performs a bounded card request only while sync/import are idle, with a 30-second interval between checks.

For the supplied Proxmox guest layout, install scripts/collect_wifi_status.py under /opt/ezsharecpap/scripts, create /opt/ezsharecpap/diagnostics and copy the service/timer from docker/systemd into /etc/systemd/system inside the guest. Check the interface name in the service (wlp1s0 in this setup), then enable the timer:

```sh
systemctl daemon-reload
systemctl enable --now ezshare-wifi-status.timer
```

Use the read-only diagnostics mount when starting Compose:

```sh
docker compose -f compose.yaml -f compose.diagnostics.yaml up -d
```

The collector runs fixed read-only iw commands and writes a small JSON file every 15 seconds. It does not record SSIDs, passwords or therapy files. Samples older than 60 seconds are marked stale. Missing tools or permissions show Wi-Fi details unavailable and do not stop sync. Wireless link rates and actual SD-card throughput are labelled separately.

## Upgrade and rollback

Back up configuration and state, retain the previous Docker image, and deploy while the service is idle or stopped at a safe boundary. Preserve the existing data mounts and secrets. The new configuration fields are optional, and state additions remain readable by the earlier version. To roll back, restore the previous image and configuration. Snapshot deletion cannot be undone by an image rollback; enable retention only after reviewing its preview.
