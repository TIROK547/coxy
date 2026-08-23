#!/usr/bin/env python3
"""
Downloads NapsternetV (.npv/.npv2/.npv3/.npv4) config file attachments from
the same Telegram channels used for VLESS/VMess/Trojan link scraping.

NapsternetV configs are posted as file attachments, not plain-text links, so
this collector scans messages for documents instead of regexing message text
the way config_collector.py does. Everything else (channel list, proxy,
concurrency, progress reporting) reuses the same shared plumbing.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import random
from io import BytesIO
from pathlib import Path

from common import (ROOT, Progress, build_client, die, env, env_int,
                    resolve_proxy, scan_channels)
from telethon.errors import FloodWaitError

DEFAULT_EXTENSIONS = (".npvt", ".npv4", ".npv2", ".npv", ".npv3", ".inpv")

# Random decorative emoji pool for output filenames (Coxy{emoji}_{hash}.ext).
# Kept deliberately unrelated to country/flag semantics — this is just a
# branding flourish for the saved file, not geo data like the vless remarks.
EMOJI_POOL = (
    "🚀",
    "⚡",
    "🔥",
    "🌟",
    "✨",
    "🎯",
    "🛸",
    "🦊",
    "🐉",
    "🦅",
    "🌊",
    "🌈",
    "🍀",
    "🎲",
    "🧭",
    "🛰️",
    "🪐",
    "🌀",
    "💎",
    "🔮",
    "🎃",
    "🍉",
    "🍁",
    "🌵",
    "🦄",
    "🐺",
    "🦉",
    "🐋",
    "🦋",
    "🌙",
)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Download NapsternetV config files from Telegram channels"
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


def _extensions() -> tuple[str, ...]:
    """NPV_EXTENSIONS in .env overrides the default list, comma-separated."""
    raw = env("NPV_EXTENSIONS")
    if not raw:
        return DEFAULT_EXTENSIONS
    exts = tuple(e.strip().lower() for e in raw.split(",") if e.strip())
    exts = tuple(e if e.startswith(".") else f".{e}" for e in exts)
    return exts or DEFAULT_EXTENSIONS


def _doc_filename(msg) -> str | None:
    """Original filename of a message's document attachment, if it has one."""
    if not msg.document:
        return None
    for attr in msg.document.attributes:
        name = getattr(attr, "file_name", None)
        if name:
            return name
    return None


async def main() -> None:
    args = parse_args()

    api_id = env("TELEGRAM_API_ID")
    api_hash = env("TELEGRAM_API_HASH")
    if not api_id or not api_hash:
        die(
            "TELEGRAM_API_ID / TELEGRAM_API_HASH are not set. Copy .env.example to .env and fill them in."
        )

    channels_file = env("CONFIG_CHANNELS_FILE")
    if not channels_file:
        die("CONFIG_CHANNELS_FILE is not set in .env.")

    channels_path = ROOT / channels_file
    if not channels_path.exists():
        die(f"Channel list not found: {channels_path}")

    channels = [l.strip() for l in channels_path.read_text().splitlines() if l.strip()]
    if not channels:
        die(f"{channels_path} is empty — add at least one channel (one per line).")

    output_dir = ROOT / env("NPV_OUTPUT_DIR", "output/npv")
    limit = args.messages_per_channel or env_int("MESSAGES_PER_CHANNEL", 40)
    concurrency = args.concurrency or env_int("CHANNEL_CONCURRENCY", 5)
    extensions = _extensions()

    client = build_client(
        str(ROOT / env("TELEGRAM_SESSION_NAME", "coxysession")),
        int(api_id),
        api_hash,
        resolve_proxy(args.proxy),
    )
    await client.start()

    print(
        f"Scanning {len(channels)} channel(s), {concurrency} at a time, {limit} messages each, "
        f"for {', '.join(extensions)} files..."
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    seen_hashes: set[str] = set()
    write_lock = asyncio.Lock()
    progress = Progress(len(channels))
    saved = 0

    async def worker(channel: str) -> None:
        nonlocal saved
        try:
            entity = await client.get_entity(channel)
        except Exception as e:
            await progress.report(channel, ok=False, found=0, error=str(e))
            return

        found = 0
        try:
            async for msg in client.iter_messages(entity, limit=limit):
                fname = _doc_filename(msg)
                if not fname or not fname.lower().endswith(extensions):
                    continue

                buf = BytesIO()
                try:
                    await msg.download_media(file=buf)
                except Exception:
                    continue

                data = buf.getvalue()
                if not data:
                    continue

                digest = hashlib.sha256(data).hexdigest()

                async with write_lock:
                    if digest in seen_hashes:
                        continue
                    seen_hashes.add(digest)
                    # Coxy{random emoji}_{short hash}{original extension}.
                    # The hash suffix isn't decorative — it's what keeps two
                    # files from clobbering each other if they happen to draw
                    # the same emoji; content-based, so re-runs are stable.
                    ext = Path(fname).suffix
                    emoji = random.choice(EMOJI_POOL)
                    out_path = output_dir / f"Coxy{emoji}_{digest[:8]}{ext}"
                    out_path.write_bytes(data)
                    saved += 1
                found += 1
        except FloodWaitError as e:
            await progress.report(
                channel, ok=False, found=found, error=f"rate-limited, wait {e.seconds}s"
            )
            return

        await progress.report(channel, ok=True, found=found)

    await scan_channels(channels, concurrency, worker)

    print(f"\nDone: {saved} unique NapsternetV file(s) saved to {output_dir}")


if __name__ == "__main__":
    asyncio.run(main())
