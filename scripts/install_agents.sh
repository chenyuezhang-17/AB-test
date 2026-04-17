#!/bin/bash
# Install LaunchAgent plists for Leego daily + warmup daemons.
# Usage: bash scripts/install_agents.sh

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
AGENT_DIR="$HOME/Library/LaunchAgents"

echo "Installing Leego LaunchAgents..."

# Unload if already loaded
launchctl unload "$AGENT_DIR/com.lessie.leego-daily.plist" 2>/dev/null
launchctl unload "$AGENT_DIR/com.lessie.leego-warmup.plist" 2>/dev/null

# Copy plist files
cp "$SCRIPT_DIR/com.lessie.leego-daily.plist" "$AGENT_DIR/"
cp "$SCRIPT_DIR/com.lessie.leego-warmup.plist" "$AGENT_DIR/"

# Load
launchctl load "$AGENT_DIR/com.lessie.leego-daily.plist"
launchctl load "$AGENT_DIR/com.lessie.leego-warmup.plist"

echo "Installed:"
echo "  com.lessie.leego-daily   -> 9:05 AM daily"
echo "  com.lessie.leego-warmup  -> 10:00 AM daily"
echo ""
echo "Check status: launchctl list | grep lessie"
echo "Uninstall:    launchctl unload ~/Library/LaunchAgents/com.lessie.leego-*.plist"
echo ""
echo "NOTE: Mac must not be asleep at trigger time."
echo "      Consider: System Settings > Energy > Prevent automatic sleeping."
