# Install published Docker images

The public images are hosted on GitHub Container Registry:

- `ghcr.io/adrianrfeeger/ezsharecpap-server:latest` for the web interface and downloader.
- `ghcr.io/adrianrfeeger/ezsharecpap-server-samba:latest` for the read-only CPAP network share.

Both include Linux AMD64 and ARM64 images. Docker selects the matching architecture automatically. Downloads do not require a GitHub account or registry login.

## Prepare an installation

Install Docker Engine and its Compose plugin on a Linux server. Configure the server's Wi-Fi connection to the ez Share card while keeping its LAN connection available. The images use this existing network connection; they do not configure Wi-Fi or grant Docker access to host network administration.

Create an installation folder and download the small configuration files:

```sh
mkdir ezsharecpap-server
cd ezsharecpap-server
mkdir -p config secrets data/state data/work data/published
curl -fL https://raw.githubusercontent.com/adrianRfeeger/ezShareCPAP-Server/main/compose.release.yaml -o compose.yaml
curl -fL https://raw.githubusercontent.com/adrianRfeeger/ezShareCPAP-Server/main/.env.example -o .env
curl -fL https://raw.githubusercontent.com/adrianRfeeger/ezShareCPAP-Server/main/server.example.json -o config/server.json
```

Edit `.env` to set `LAN_IP` to this server's LAN address. Leave `EZSHARE_VERSION=latest` for the current main-branch build, or choose a published `sha-XXXXXXX` tag to pin an exact application revision. Both services use the same revision tag.

Edit `config/server.json` for the card URL, daily time and timezone. The card must be reachable from this Linux server before starting a sync.

Create `secrets/web_password` and `secrets/smb_password` with different passwords, each on one line. The web password needs at least 16 characters. Store the passwords in your password manager. With the default UID/GID of 1000:

```sh
chown -R 1000:1000 config data
chmod 750 config data
chmod 700 secrets
chown 1000:1000 secrets/web_password
chmod 400 secrets/web_password
chmod 600 secrets/smb_password
```

Run these administrative commands with suitable privileges. If PUID/PGID in `.env` differ, use those numbers instead. The app account must be able to read its web secret and write configuration/data. Samba reads its own secret as root at startup. Passwords, configuration and downloaded files stay in these host folders and are not part of the images.

## Start and update

```sh
docker compose config --quiet
docker compose pull
docker compose up -d
docker compose ps
```

Open `http://SERVER-LAN-IP:8080` and sign in as `admin`. The CPAP share is available at `smb://SERVER-LAN-IP/CPAP`, using username `cpap` and the SMB password. Completed snapshots appear after a successful sync.

For an existing source checkout, use the published-image Compose file explicitly:

```sh
docker compose -f compose.release.yaml pull
docker compose -f compose.release.yaml up -d
```

The image-based and source-build Compose files use the same services, folders, ports and secrets. Back up configuration/state and finish or stop an active sync before switching. Keep the previous image/tag for rollback. Optional Wi-Fi diagnostics work by adding `-f compose.diagnostics.yaml` to the same Compose command, as described in the [deployment guide](docker-deployment.md).

## Image tags and publication

The Container images workflow tests changes, smoke-tests the packaged app, and publishes both images for AMD64 and ARM64. Main-branch builds receive `latest` and `sha-XXXXXXX` tags. A `v1.2.3` Git tag publishes `1.2.3` and the revision tag, without replacing `latest` with a potentially older tagged release. ARM64 smoke checks run through emulation; this does not claim testing on physical ARM hardware.

Keep automatic updates under your control. Pulling images does not restart running containers; `docker compose up -d` applies the selected image. Pin a revision tag or registry digest when you need a reproducible installation.


## Verified first publication

Source revision `029b884` was published on 17 October 2026. [The publishing workflow](https://github.com/adrianRfeeger/ezShareCPAP-Server/actions/runs/39000016187) passed all 125 Python tests, 9 JavaScript tests, AMD64 package smoke checks and ARM64 checks through emulation. Both image manifests were retrieved anonymously and contain Linux AMD64 and ARM64 variants.

| Image | Published manifest digest |
| --- | --- |
| `ghcr.io/adrianrfeeger/ezsharecpap-server` | `sha256:f3f7139d32a1d54baeb96eacb184e32376d54e539242a69c82b44555df733c31` |
| `ghcr.io/adrianrfeeger/ezsharecpap-server-samba` | `sha256:899e40ead4dd61768e110b13badc952b52e367c1368d783c18c18e690910d2e8` |

The app image was also pulled without registry credentials on the Proxmox guest and passed its restricted-container smoke checks with synthetic data. The existing production services were not switched to the registry images during publication.

## Password-free dashboard

To open the dashboard without signing in, set `WEB_AUTH_MODE=none` in `.env` and recreate the downloader. This gives anyone who can reach the dashboard access to CPAP downloads, uploads, sync controls and settings. Use it only on a trusted LAN.

With a source build, run:

```sh
docker compose up -d --build downloader
```

With a published image that includes this option, run:

```sh
docker compose -f compose.release.yaml pull downloader
docker compose -f compose.release.yaml up -d downloader
```

The supplied Compose files still mount `secrets/web_password`. For a new password-free installation, create an empty file there instead of choosing a web password. Keep an existing password file if you may switch back. The application does not read it in password-free mode. SMB still requires its separate password.

The server saves a random session secret in `config/.web-session-secret`, with owner-only permissions. Keep the config directory writable by the downloader account. Browser-request protections and upload storage limits remain active.

To restore login protection, set `WEB_AUTH_MODE=password`, ensure `secrets/web_password` contains at least 16 characters and is readable by the downloader, then recreate the downloader. Password protection is the default when the setting is absent. Changing modes invalidates existing browser sessions; reload the dashboard before submitting a form.
