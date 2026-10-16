#!/bin/sh
set -eu
SHARE_UID=${SHARE_UID:-1000}
SHARE_GID=${SHARE_GID:-1000}
case "${SHARE_UID:-1000}:${SHARE_GID:-1000}" in *[!0-9:]*|0:*|*:0) echo 'Use non-root numeric UID/GID' >&2; exit 1;; esac
getent group "$SHARE_GID" >/dev/null || groupadd -g "$SHARE_GID" cpap
id cpap >/dev/null 2>&1 || useradd -M -u "$SHARE_UID" -g "$SHARE_GID" -s /usr/sbin/nologin cpap
password=$(cat /run/secrets/smb_password)
[ -n "$password" ] || { echo 'SMB password is empty' >&2; exit 1; }
printf '%s\n%s\n' "$password" "$password" | smbpasswd -s -a cpap >/dev/null
unset password
testparm -s >/dev/null
exec smbd --foreground --no-process-group --debug-stdout
