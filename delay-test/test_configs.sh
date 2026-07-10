#!/usr/bin/env bash
set -e

set -a
source .env
set +a
#XRAY_KNIFE=/usr/bin/xray-knife

$XRAY_KNIFE http -f "$RAW_CONFIGS_FILE"\
  --speedtest \
  --sort \
  --type csv \
  -o "$OUTPUT_CONFIGS_FILE" \
  --thread "$XRAY_KNIFE_THREADS"