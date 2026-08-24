#!/usr/bin/env python3
"""
Scrapes MTProto/HTTP/SOCKS5 proxy links from a list of Telegram channels.

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
from urllib.parse import parse_qs, urlparse

from common import (ROOT, Progress, build_client, die, env, env_int,
                    make_resolver, resolve_proxy, save_resolve_cache,
                    scan_channels)
from telethon.errors import FloodWaitError
from telethon.tl.types import KeyboardButtonUrl

PROXY_RE = re.compile(
    r'(?:tg://proxy|https?://(?:t\.me|telegram\.me)/proxy)\?[^\s<>"\']+',
    re.IGNORECASE,
)


def normalize(proxy: str) -> tuple:
    """Dedup key: server+port+secret, ignoring incidental query param order/casing."""
    q = parse_qs(urlparse(proxy.replace("tg://", "https://")).query)
    return (
        q.get("server", [""])[0].lower(),
        q.get("port", [""])[0],
        q.get("secret", [""])[0].lower(),
    )


def extract_button_urls(msg) -> list[str]:
    """Pull URLs off inline keyboard buttons attached to the message."""
    urls = []
    if msg.reply_markup:
        for row in msg.reply_markup.rows:
            for button in row.buttons:
                if isinstance(button, KeyboardButtonUrl):
                    urls.append(button.url)
    return urls


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Scrape MTProto/HTTP/SOCKS5 proxy links from Telegram channels"
    )
    p.add_argument(
        "--proxy",
        help="Proxy for reaching Telegram: socks5://[user:pass@]host:port, "
        "socks4://..., http://..., or mtproxy://secret@host:port. "
        "Defaults to TELEGRAM_PROXY in .env if not given.",
    )
    p.add_argument(
        "-j",
        "-c",
        "--concurrency",
        type=int,
        default=None,
        help="How many channels to scan at once (default: CHANNEL_CONCURRENCY in .env, or 5)",
    )
    p.add_argument(
        "-n",
        "--messages-per-channel",
        type=int,
        default=None,
        help="Recent messages to scan per channel (default: MESSAGES_PER_CHANNEL in .env, or 40)",
    )
    return p.parse_args()


async def main() -> None:
    args = parse_args()

    api_id = env("TELEGRAM_API_ID")
    api_hash = env("TELEGRAM_API_HASH")
    if not api_id or not api_hash:
        die(
            "TELEGRAM_API_ID / TELEGRAM_API_HASH are not set. Copy .env.example to .env and fill them in."
        )

    channels_file = env("PROXY_CHANNELS_FILE")
    if not channels_file:
        die("PROXY_CHANNELS_FILE is not set in .env.")

    channels_path = ROOT / channels_file
    if not channels_path.exists():
        die(f"Channel list not found: {channels_path}")

    channels = [l.strip() for l in channels_path.read_text().splitlines() if l.strip()]
    if not channels:
        die(f"{channels_path} is empty — add at least one channel (one per line).")

    output_file = ROOT / env("RAW_PROXIES_FILE", "output/raw_proxies.txt")
    limit = args.messages_per_channel or env_int("MESSAGES_PER_CHANNEL", 40)
    concurrency = args.concurrency or env_int("CHANNEL_CONCURRENCY", 5)

    client = build_client(
        str(ROOT / env("TELEGRAM_SESSION_NAME", "coxysession")),
        int(api_id),
        api_hash,
        resolve_proxy(args.proxy),
    )
    await client.start()

    print(
        f"Scanning {len(channels)} channel(s), {concurrency} at a time, {limit} messages each..."
    )

    seen: set = set()
    results: list[str] = []
    write_lock = asyncio.Lock()
    progress = Progress(len(channels))
    resolve_cache_path = ROOT / env("RESOLVE_CACHE_FILE", "output/.resolve_cache.json")
    resolve, resolve_cache = make_resolver(
        client,
        concurrency=env_int("RESOLVE_CONCURRENCY", 2),
        delay=env_int("RESOLVE_DELAY_MS", 300) / 1000,
        cache_path=resolve_cache_path,
        max_new=env_int("MAX_NEW_RESOLVES_PER_RUN", 40),
    )

    async def worker(channel: str) -> None:
        entity, err = await resolve(channel)
        if entity is None:
            await progress.report(channel, ok=False, found=0, error=err)
            return

        found = 0
        try:
            async for msg in client.iter_messages(entity, limit=limit):
                texts = [msg.text] if msg.text else []
                texts += extract_button_urls(msg)

                for text in texts:
                    for match in PROXY_RE.finditer(text):
                        p = match.group(0)
                        k = normalize(p)
                        async with write_lock:
                            if k in seen:
                                continue
                            seen.add(k)
                            results.append(p)
                        found += 1
        except FloodWaitError as e:
            await progress.report(
                channel, ok=False, found=found, error=f"rate-limited, wait {e.seconds}s"
            )
            return

        await progress.report(channel, ok=True, found=found)

    await scan_channels(channels, concurrency, worker)
    save_resolve_cache(resolve_cache_path, resolve_cache)

    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(
        "\n".join(results) + ("\n" if results else ""), encoding="utf-8"
    )

    print(f"\nDone: {len(results)} unique proxies written to {output_file}")


if __name__ == "__main__":
    asyncio.run(main())
