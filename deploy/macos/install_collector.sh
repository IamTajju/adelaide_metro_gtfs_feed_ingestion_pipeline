#!/bin/sh
# Student Name: Tahzeeb Ahmed
# Student FAN:  ahme0423
# File:         deploy/macos/install_collector.sh
# Date:         21-10-2026
# Description:  Runs the collector as a launchd agent: starts at login, restarts if it stops.
# Usage:        sh deploy/macos/install_collector.sh [--uninstall]
set -e

LABEL=au.edu.comp9742.gtfs-collector
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
DOMAIN="gui/$(id -u)"

launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
if [ "$1" = "--uninstall" ]; then
    rm -f "$PLIST"
    echo "collector agent removed"
    exit 0
fi

mkdir -p "$HOME/Library/LaunchAgents" "$REPO/data/logs"
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>$LABEL</string>
    <key>ProgramArguments</key>
    <array>
        <string>$REPO/venv/bin/python</string>
        <string>-m</string>
        <string>gtfs_position_collection</string>
    </array>
    <key>WorkingDirectory</key><string>$REPO</string>
    <key>RunAtLoad</key><true/>
    <key>KeepAlive</key><true/>
    <key>ThrottleInterval</key><integer>60</integer>
    <key>StandardOutPath</key><string>$REPO/data/logs/collector.service.log</string>
    <key>StandardErrorPath</key><string>$REPO/data/logs/collector.service.log</string>
</dict>
</plist>
EOF
launchctl bootstrap "$DOMAIN" "$PLIST"
echo "collector agent installed and started: $PLIST"
echo "status: launchctl print $DOMAIN/$LABEL | grep state"
