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
- Owner enters new web and SMB passwords through `/root/ezshare-set-passwords.sh` in CT 114. The script reads hidden input, confirms it, applies file ownership, and starts Compose. Passwords are not printed or stored in Git.
- Confirm web login, scheduler health, authenticated read-only SMB, and a local OSCAR import.
- Reserve the DHCP address, confirm Proxmox backup coverage, and test a future host reboot during an agreed maintenance window. No host reboot was performed.
