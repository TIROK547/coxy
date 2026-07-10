#!/usr/bin/env bash
set -e

XRAY_KNIFE=/usr/bin/xray-knife

$XRAY_KNIFE http -f ../output/raw_configs.txt \
  --speedtest \
  --sort \
  --type csv \
  -o ../output/ranked.csv \
  --thread 20