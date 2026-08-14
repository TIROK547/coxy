#!/usr/bin/env python3
"""
Scrapes VLESS/VMess/Trojan links from a list of Telegram channels.

Channels are scanned concurrently (see --concurrency / CHANNEL_CONCURRENCY)
instead of one by one, which is the main thing that makes this slow.

If Telegram is blocked where you're running this, point coxy at a proxy
instead of turning your VPN on/off around it — see --proxy below, or set
TELEGRAM_PROXY in .env once and forget about it.
"""

from __future__ import annotations

import argparse
import asyncio
import re

from telethon.errors import FloodWaitError

from common import (
    ROOT,
    build_client,
    die,
    env,
    env_int,
    resolve_proxy,
    scan_channels,
    Progress,
)


def normalize(cfg: str) -> str:
    """Dedup key: strip the #remark, keep everything else."""
    return cfg.split("#", 1)[0]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Scrape VLESS/VMess/Trojan configs from Telegram channels")
    p.add_argument(
        "--proxy",
        help="Proxy for reaching Telegram: socks5://[user:pass@]host:port, "
             "socks4://..., http://..., or mtproxy://secret@host:port. "
             "Defaults to TELEGRAM_PROXY in .env if not given.",
    )
    p.add_argument(
        "-j", "-c", "--concurrency",
        type=int,
        default=None,
        help="How many channels to scan at once (default: CHANNEL_CONCURRENCY in .env, or 5)",
    )
    p.add_argument(
        "-n", "--messages-per-channel",
        type=int,
        default=None,
        help="Recent messages to scan per channel (default: MESSAGES_PER_CHANNEL in .env, or 40)",
    )
    return p.parse_args()


CONFIG_RE = re.compile(r'(vless|vmess|trojan)://[^\s<>"\']+', re.IGNORECASE)


async def main() -> None:
    args = parse_args()

    api_id = env("TELEGRAM_API_ID")
    api_hash = env("TELEGRAM_API_HASH")
    if not api_id or not api_hash:
        die("TELEGRAM_API_ID / TELEGRAM_API_HASH are not set. Copy .env.example to .env and fill them in.")

    channels_file = env("CONFIG_CHANNELS_FILE")
    if not channels_file:
        die("CONFIG_CHANNELS_FILE is not set in .env.")

    channels_path = ROOT / channels_file
    if not channels_path.exists():
        die(f"Channel list not found: {channels_path}")

    channels = [l.strip() for l in channels_path.read_text().splitlines() if l.strip()]
    if not channels:
        die(f"{channels_path} is empty — add at least one channel (one per line).")

    output_file = ROOT / env("RAW_CONFIGS_FILE", "output/raw_configs.txt")
    limit = args.messages_per_channel or env_int("MESSAGES_PER_CHANNEL", 40)
    concurrency = args.concurrency or env_int("CHANNEL_CONCURRENCY", 5)

    client = build_client(str(ROOT / env("TELEGRAM_SESSION_NAME", "coxysession")), int(api_id), api_hash, resolve_proxy(args.proxy))
    await client.start()

    print(f"Scanning {len(channels)} channel(s), {concurrency} at a time, {limit} messages each...")

    seen: set[str] = set()
    results: list[str] = []
    write_lock = asyncio.Lock()
    progress = Progress(len(channels))

    async def worker(channel: str) -> None:
        try:
            entity = await client.get_entity(channel)
        except Exception as e:
            await progress.report(channel, ok=False, found=0, error=str(e))
            return

        found = 0
        try:
            async for msg in client.iter_messages(entity, limit=limit):
                if not msg.text:
                    continue
                for match in CONFIG_RE.finditer(msg.text):
                    c = match.group(0)
                    k = normalize(c)
                    async with write_lock:
                        if k in seen:
                            continue
                        seen.add(k)
                        results.append(c)
                    found += 1
        except FloodWaitError as e:
            await progress.report(channel, ok=False, found=found, error=f"rate-limited, wait {e.seconds}s")
            return

        await progress.report(channel, ok=True, found=found)

    await scan_channels(channels, concurrency, worker)

    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text("\n".join(results) + ("\n" if results else ""), encoding="utf-8")

    print(f"\nDone: {len(results)} unique configs written to {output_file}")


if __name__ == "__main__":
    asyncio.run(main())
