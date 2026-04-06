#!/bin/bash
set -e

LOGFILE="/tmp/edbian-updater.log"
echo "" > "$LOGFILE"

for pkg in "$@"; do
    echo "Instalando $pkg" | tee -a "$LOGFILE"
    dpkg -i "$pkg" >> "$LOGFILE" 2>&1 || apt install -f -y >> "$LOGFILE" 2>&1
done
