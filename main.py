#!/usr/bin/env python3
"""
coxy CLI

Orchestrates the full pipeline:
  collect-configs  -> scrape VLESS/VMess/Trojan links from Telegram   (collectors/config_collector.py)
  collect-proxies  -> scrape MTProto/HTTP/SOCKS5 links from Telegram  (collectors/proxy_collector.py)
  test-configs     -> speed-test configs with xray-knife              (delay-test/test_configs.sh)
  test-proxies     -> liveness/latency-test proxies                   (delay-test/test_proxies.py)
  best             -> pick the top-N fastest passing configs
  all              -> run the whole pipeline in order

Every subcommand is executed with the repo root as the working directory,
since that's what the underlying scripts' .env-relative paths expect --
run coxy from anywhere and it will still work.
"""

from __future__ import annotations

import argparse
import csv
import os
import subprocess
import sys
from pathlib import Path
from shutil import which

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")


def env(key: str, default: str | None = None) -> str | None:
    return os.getenv(key, default)


def run(cmd: list[str], cwd: Path, label: str) -> int:
    print(f"\n==> {label}")
    try:
        result = subprocess.run(cmd, cwd=cwd)
    except FileNotFoundError as exc:
        print(f"[!] Could not run {cmd[0]}: {exc}", file=sys.stderr)
        return 127
    if result.returncode != 0:
        print(f"[!] {label} exited with code {result.returncode}", file=sys.stderr)
    return result.returncode


def require_env(*keys: str) -> bool:
    missing = [k for k in keys if not env(k)]
    if missing:
        print(f"[!] Missing required .env values: {', '.join(missing)}", file=sys.stderr)
        print("    Copy .env.example to .env and fill it in.", file=sys.stderr)
        return False
    return True


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------

def cmd_collect_configs(args: argparse.Namespace) -> int:
    if not require_env("TELEGRAM_API_ID", "TELEGRAM_API_HASH", "CONFIG_CHANNELS_FILE"):
        return 1
    return run(
        [sys.executable, "collectors/config_collector.py"],
        cwd=ROOT,
        label="Collecting configs from Telegram channels",
    )


def cmd_collect_proxies(args: argparse.Namespace) -> int:
    if not require_env("TELEGRAM_API_ID", "TELEGRAM_API_HASH", "PROXY_CHANNELS_FILE"):
        return 1
    return run(
        [sys.executable, "collectors/proxy_collector.py"],
        cwd=ROOT,
        label="Collecting MTProto proxies from Telegram channels",
    )


def cmd_test_configs(args: argparse.Namespace) -> int:
    script = ROOT / "delay-test" / "test_configs.sh"
    xray_knife = env("XRAY_KNIFE", "xray-knife")
    if not (Path(xray_knife).exists() or which(xray_knife)):
        print(f"[!] xray-knife not found at '{xray_knife}'. Set XRAY_KNIFE in .env.", file=sys.stderr)
        return 1
    return run(["bash", str(script)], cwd=ROOT, label="Speed-testing configs with xray-knife")


def cmd_test_proxies(args: argparse.Namespace) -> int:
    cmd = [sys.executable, "delay-test/test_proxies.py"]
    if getattr(args, "input", None):
        cmd += ["-i", args.input]
    if getattr(args, "output", None):
        cmd += ["-o", args.output]
    if getattr(args, "timeout", None) is not None:
        cmd += ["-t", str(args.timeout)]
    if getattr(args, "concurrency", None) is not None:
        cmd += ["-c", str(args.concurrency)]
    if getattr(args, "strict", False):
        cmd.append("--strict")
    return run(cmd, cwd=ROOT, label="Testing proxies")


def cmd_best(args: argparse.Namespace) -> int:
    input_csv = ROOT / env("OUTPUT_CONFIGS_FILE", "output/result_configs.csv")
    top_n = getattr(args, "top_n", None) or int(env("TOP_N", "20"))
    output_dir = ROOT / env("OUTPUT_DIR", "output")
    out_path = output_dir / f"top{top_n}_configs.txt"

    if not input_csv.exists():
        print(f"[!] {input_csv} not found. Run `test-configs` first.", file=sys.stderr)
        return 1

    with input_csv.open(newline="", encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f) if r.get("status", "").lower() == "passed"]

    if not rows:
        print("[!] No passing configs found in result CSV.", file=sys.stderr)
        return 1

    delay_key = next((k for k in ("delay", "Delay", "delay_ms") if k in rows[0]), None)
    raw_key = next((k for k in ("raw", "link", "url") if k in rows[0]), None)
    if delay_key is None or raw_key is None:
        print(f"[!] Unexpected CSV columns: {list(rows[0].keys())}", file=sys.stderr)
        return 1

    rows.sort(key=lambda r: float(r.get(delay_key, "9999") or 9999))
    top = rows[:top_n]

    output_dir.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(r[raw_key] for r in top) + "\n", encoding="utf-8")
    print(f"Wrote top {len(top)} configs to {out_path}")
    return 0


def cmd_all(args: argparse.Namespace) -> int:
    steps = [
        cmd_collect_configs,
        cmd_collect_proxies,
        cmd_test_configs,
        cmd_test_proxies,
        cmd_best,
    ]
    for step in steps:
        if step == cmd_collect_configs:
            input("If you're in a censored region turn on your VPN before continuing and press ENTER.")
        elif step == cmd_test_configs:
            input("In order to get the most accurate delay-test results please turn off your VPN and press ENTER.")

        rc = step(args)
        if rc != 0 and not getattr(args, "keep_going", False):
            print(
                f"\n[!] Pipeline stopped at '{step.__name__}' (exit {rc}). "
                "Use --keep-going to ignore failures.",
                file=sys.stderr,
            )
            return rc
        if step == cmd_test_configs:
            input("In order to get the most accurate delay-test results please turn off your VPN.\n")

    return 0


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="coxy",
        description="Scrape, test, and rank VPN configs & MTProto proxies from Telegram channels.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("collect-configs", help="Scrape VLESS/VMess/Trojan configs from Telegram")
    p.set_defaults(func=cmd_collect_configs)

    p = sub.add_parser("collect-proxies", help="Scrape MTProto/HTTP/SOCKS5 proxies from Telegram")
    p.set_defaults(func=cmd_collect_proxies)

    p = sub.add_parser("test-configs", help="Speed-test scraped configs with xray-knife")
    p.set_defaults(func=cmd_test_configs)

    p = sub.add_parser("test-proxies", help="Check liveness/latency of scraped proxies")
    p.add_argument("-i", "--input", help="Override input proxy file")
    p.add_argument("-o", "--output", help="Override output proxy file")
    p.add_argument("-t", "--timeout", type=float, default=None, help="Per-proxy timeout (s)")
    p.add_argument("-c", "--concurrency", type=int, default=None, help="Max concurrent checks")
    p.add_argument("--strict", action="store_true", help="Slower, more accurate verification")
    p.set_defaults(func=cmd_test_proxies)

    p = sub.add_parser("best", help="Pick the top-N fastest passing configs")
    p.add_argument("-n", "--top-n", type=int, default=None, help="How many configs to keep (default: TOP_N in .env)")
    p.set_defaults(func=cmd_best)

    p = sub.add_parser("all", help="Run the full pipeline: collect -> test -> rank")
    p.add_argument("--keep-going", action="store_true", help="Continue even if a step fails")
    p.set_defaults(func=cmd_all)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()