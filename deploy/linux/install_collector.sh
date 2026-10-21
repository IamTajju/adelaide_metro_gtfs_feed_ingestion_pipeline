#!/bin/sh
# Student Name: Tahzeeb Ahmed
# Student FAN:  ahme0423
# File:         deploy/linux/install_collector.sh
# Date:         21-10-2026
# Description:  Runs the collector as a systemd user service: starts at boot, restarts if it stops.
# Usage:        sh deploy/linux/install_collector.sh [--uninstall]
set -e

UNIT=gtfs-collector.service
UNIT_FILE="$HOME/.config/systemd/user/$UNIT"
REPO="$(cd "$(dirname "$0")/../.." && pwd)"

if [ "$1" = "--uninstall" ]; then
    systemctl --user disable --now "$UNIT" 2>/dev/null || true
    rm -f "$UNIT_FILE"
    systemctl --user daemon-reload
    echo "collector service removed"
    exit 0
fi

mkdir -p "$(dirname "$UNIT_FILE")" "$REPO/data/logs"
cat > "$UNIT_FILE" <<EOF
[Unit]
Description=Adelaide Metro GTFS position collector
After=network-online.target
Wants=network-online.target

[Service]
WorkingDirectory=$REPO
ExecStart=$REPO/venv/bin/python -m gtfs_position_collection
Restart=always
RestartSec=60
StandardOutput=append:$REPO/data/logs/collector.service.log
StandardError=append:$REPO/data/logs/collector.service.log

[Install]
WantedBy=default.target
EOF
systemctl --user daemon-reload
systemctl --user enable --now "$UNIT"
# Keep user services running after logout and start them at boot without a login.
loginctl enable-linger "$USER"
echo "collector service installed and started: $UNIT_FILE"
echo "status: systemctl --user status $UNIT"
