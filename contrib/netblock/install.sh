#!/bin/bash
# One-time root setup of the network side of daykeeper's site block.
#   sudo bash contrib/netblock/install.sh
# Needs sing-box running as the `sing-box` systemd service with TUN and a `sniff` rule
# (domain rules only match after sniffing). Re-running is safe.
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo "запусти через sudo" >&2; exit 1; }
HERE=$(cd "$(dirname "$0")" && pwd)
USER_NAME=${SUDO_USER:?запусти через sudo из-под своего пользователя}

install -Dm755 "$HERE/daykeeper-netblock" /usr/local/bin/daykeeper-netblock
install -Dm644 "$HERE/blocked.json" /etc/daykeeper-netblock/blocked.json
install -Dm644 "$HERE/unblocked.json" /etc/daykeeper-netblock/unblocked.json
[[ -f /etc/daykeeper-netblock/active.json ]] || install -m644 "$HERE/blocked.json" /etc/daykeeper-netblock/active.json
install -Dm644 "$HERE/netblock.json" /etc/sing-box/netblock.json

# sing-box gets one more `-c`, last, so the reject rule sits after the existing sniff rule
argv=$(systemctl show sing-box -p ExecStart --value | sed -n 's/.*argv\[\]=\([^;]*\) ;.*/\1/p' | sed 's/ *$//')
[[ -n "$argv" ]] || { echo "не нашёл ExecStart у sing-box.service" >&2; exit 1; }
if [[ "$argv" != *netblock.json* ]]; then
  argv="$argv -c /etc/sing-box/netblock.json"
fi
mkdir -p /etc/systemd/system/sing-box.service.d
cat > /etc/systemd/system/sing-box.service.d/daykeeper-netblock.conf <<EOF
[Service]
ExecStart=
ExecStart=$argv
EOF

install -Dm644 "$HERE/daykeeper-netblock-boot.service" /etc/systemd/system/daykeeper-netblock-boot.service

SUDOERS=/etc/sudoers.d/daykeeper-netblock
echo "$USER_NAME ALL=(root) NOPASSWD: /usr/local/bin/daykeeper-netblock" > "$SUDOERS.tmp"
chmod 440 "$SUDOERS.tmp"
visudo -cf "$SUDOERS.tmp" >/dev/null
mv -f "$SUDOERS.tmp" "$SUDOERS"

systemctl daemon-reload
systemctl enable daykeeper-netblock-boot.service
sing-box check $(echo "$argv" | sed 's|^[^ ]* run ||')
systemctl restart sing-box
echo "готово: $(daykeeper-netblock status), sing-box: $(systemctl is-active sing-box)"
