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

from brand import brand_row

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
        print(
            f"[!] Missing required .env values: {', '.join(missing)}", file=sys.stderr
        )
        print("    Copy .env.example to .env and fill it in.", file=sys.stderr)
        return False
    return True


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------


def _collector_cmd(script: str, args: argparse.Namespace) -> list[str]:
    cmd = [sys.executable, script]
    if getattr(args, "proxy", None):
        cmd += ["--proxy", args.proxy]
    if getattr(args, "channel_concurrency", None) is not None:
        cmd += ["--concurrency", str(args.channel_concurrency)]
    return cmd


def cmd_collect_configs(args: argparse.Namespace) -> int:
    if not require_env("TELEGRAM_API_ID", "TELEGRAM_API_HASH", "CONFIG_CHANNELS_FILE"):
        return 1
    return run(
        _collector_cmd("collectors/config_collector.py", args),
        cwd=ROOT,
        label="Collecting configs from Telegram channels",
    )


def cmd_collect_proxies(args: argparse.Namespace) -> int:
    if not require_env("TELEGRAM_API_ID", "TELEGRAM_API_HASH", "PROXY_CHANNELS_FILE"):
        return 1
    return run(
        _collector_cmd("collectors/proxy_collector.py", args),
        cwd=ROOT,
        label="Collecting MTProto proxies from Telegram channels",
    )


def cmd_test_configs(args: argparse.Namespace) -> int:
    script = ROOT / "delay-test" / "test_configs.sh"
    xray_knife = env("XRAY_KNIFE", "xray-knife")
    if not (Path(xray_knife).exists() or which(xray_knife)):
        print(
            f"[!] xray-knife not found at '{xray_knife}'. Set XRAY_KNIFE in .env.",
            file=sys.stderr,
        )
        return 1
    return run(
        ["bash", str(script)], cwd=ROOT, label="Speed-testing configs with xray-knife"
    )


def cmd_test_proxies(args: argparse.Namespace) -> int:
    input_file = ROOT / (
        getattr(args, "input", None)
        or env("RAW_PROXIES_FILE", "output/raw_proxies.txt")
    )
    if not input_file.exists() or not input_file.read_text(encoding="utf-8").strip():
        # Not a real failure — collect-proxies can legitimately come back
        # empty (e.g. its channels were rate-limited that run). Don't let an
        # optional, secondary collection stream hard-stop the whole `all`
        # pipeline before it reaches `best`.
        print(f"\n==> Testing proxies")
        print(f"[i] {input_file} is empty or missing — no proxies to test, skipping.")
        return 0

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
    output_dir = ROOT / env("OUTPUT_DIR", "output")
    top_n = getattr(args, "top_n", None) or int(env("TOP_N", "20"))
    out_path = output_dir / f"top{top_n}_configs.txt"
    label = env("REMARK_LABEL", "Coxy")

    if not input_csv.exists():
        print(f"[!] {input_csv} not found. Run `test-configs` first.", file=sys.stderr)
        return 1

    with input_csv.open(newline="", encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f) if r.get("status", "").lower() == "passed"]

    if not rows:
        print("[!] No passing configs found in result CSV.", file=sys.stderr)
        return 1

    delay_key = next((k for k in ("delay", "Delay", "delay_ms") if k in rows[0]), None)
    raw_key = next((k for k in ("link", "raw", "url") if k in rows[0]), None)
    loc_key = next((k for k in ("location", "loc", "country") if k in rows[0]), None)
    if delay_key is None or raw_key is None:
        print(f"[!] Unexpected CSV columns: {list(rows[0].keys())}", file=sys.stderr)
        return 1

    rows.sort(key=lambda r: float(r.get(delay_key, "9999") or 9999))
    top = rows[:top_n]

    output_dir.mkdir(parents=True, exist_ok=True)
    branded = [
        brand_row(r[raw_key], r.get(loc_key) if loc_key else None, label) for r in top
    ]
    out_path.write_text("\n".join(branded) + "\n", encoding="utf-8")
    print(f"Wrote top {len(top)} branded configs to {out_path}")
    return 0


STEP_LABELS = {
    "cmd_collect_configs": "collect-configs",
    "cmd_collect_proxies": "collect-proxies",
    "cmd_test_configs": "test-configs",
    "cmd_test_proxies": "test-proxies",
    "cmd_best": "best",
}


def cmd_all(args: argparse.Namespace) -> int:
    steps = [
        cmd_collect_proxies,
        cmd_collect_configs,
        cmd_test_configs,
        cmd_test_proxies,
        cmd_best,
    ]

    print(
        f"Running the full pipeline: {' -> '.join(STEP_LABELS[s.__name__] for s in steps)}\n"
    )

    if not getattr(args, "yes", False):
        try:
            input(
                "[i] test-configs measures delay from *your* connection, so results will be "
                "skewed if you're on a VPN during that step. Press ENTER to continue, or Ctrl+C to stop "
                "(skip this prompt next time with --yes).\n"
            )
        except KeyboardInterrupt:
            print("\nAborted.")
            return 130

    for step in steps:
        rc = step(args)
        if rc != 0 and not getattr(args, "keep_going", False):
            print(
                f"\n[!] Pipeline stopped at '{STEP_LABELS[step.__name__]}' (exit {rc}). "
                "Use --keep-going to ignore failures and continue with the remaining steps.",
                file=sys.stderr,
            )
            return rc

    print("\nPipeline finished. See output/ for results.")
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

    proxy_help = (
        "Proxy for reaching Telegram (socks5://, socks4://, http://, or mtproxy://secret@host:port). "
        "Defaults to TELEGRAM_PROXY in .env."
    )
    channel_concurrency_help = (
        "How many channels to scan at once (default: CHANNEL_CONCURRENCY in .env, or 5)"
    )

    p = sub.add_parser(
        "collect-configs", help="Scrape VLESS/VMess/Trojan configs from Telegram"
    )
    p.add_argument("--proxy", help=proxy_help)
    p.add_argument(
        "-j",
        "--channel-concurrency",
        type=int,
        default=None,
        help=channel_concurrency_help,
    )
    p.set_defaults(func=cmd_collect_configs)

    p = sub.add_parser(
        "collect-proxies", help="Scrape MTProto/HTTP/SOCKS5 proxies from Telegram"
    )
    p.add_argument("--proxy", help=proxy_help)
    p.add_argument(
        "-j",
        "--channel-concurrency",
        type=int,
        default=None,
        help=channel_concurrency_help,
    )
    p.set_defaults(func=cmd_collect_proxies)

    p = sub.add_parser(
        "test-configs", help="Speed-test scraped configs with xray-knife"
    )
    p.set_defaults(func=cmd_test_configs)

    p = sub.add_parser("test-proxies", help="Check liveness/latency of scraped proxies")
    p.add_argument("-i", "--input", help="Override input proxy file")
    p.add_argument("-o", "--output", help="Override output proxy file")
    p.add_argument(
        "-t", "--timeout", type=float, default=None, help="Per-proxy timeout (s)"
    )
    p.add_argument(
        "-c", "--concurrency", type=int, default=None, help="Max concurrent checks"
    )
    p.add_argument(
        "--strict", action="store_true", help="Slower, more accurate verification"
    )
    p.set_defaults(func=cmd_test_proxies)

    p = sub.add_parser("best", help="Pick the top-N fastest passing configs")
    p.add_argument(
        "-n",
        "--top-n",
        type=int,
        default=None,
        help="How many configs to keep (default: TOP_N in .env)",
    )
    p.set_defaults(func=cmd_best)

    p = sub.add_parser("all", help="Run the full pipeline: collect -> test -> rank")
    p.add_argument(
        "--keep-going", action="store_true", help="Continue even if a step fails"
    )
    p.add_argument("--proxy", help=proxy_help + " Applies to both collect steps.")
    p.add_argument(
        "-j",
        "--channel-concurrency",
        type=int,
        default=None,
        help=channel_concurrency_help + " Applies to both collect steps.",
    )
    p.add_argument("-y", "--yes", action="store_true", help="Skip confirmation prompts")
    p.set_defaults(func=cmd_all)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
