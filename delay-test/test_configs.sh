#!/usr/bin/env bash
set -e

XRAY_KNIFE=/opt/xray-knife/xray-knife   # download from GitHub releases

$XRAY_KNIFE http -f ../collectors/channels/raw_configs.txt \
  --speedtest \
  --sort \
  --type csv \
  -o ranked.csv \
  --threads 20

# ranked.csv columns include: protocol, address, port, delay(ms), download, upload, remark, ...