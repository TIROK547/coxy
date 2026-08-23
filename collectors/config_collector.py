#!/usr/bin/env python3
"""
Scrapes VLESS/VMess/Trojan links AND downloads NapsternetV (.npvt/...) file
attachments from the same list of Telegram channels — in a single pass.

Both come from CONFIG_CHANNELS_FILE, so scanning it twice (once per collector)
meant every message in every channel was fetched from Telegram twice for no
reason. This does one iter_messages() per channel and checks each message for
both: text -> regex match -> RAW_CONFIGS_FILE; document -> extension match ->
NPV_OUTPUT_DIR. Two separate outputs, one scan.

Channels are scanned concurrently (see --concurrency / CHANNEL_CONCURRENCY)
instead of one by one, which is the main thing that makes this slow.

If Telegram is blocked where you're running this, point coxy at a proxy
instead of turning your VPN on/off around it — see --proxy below, or set
TELEGRAM_PROXY in .env once and forget about it.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import random
import re
from io import BytesIO
from pathlib import Path

from common import (ROOT, Progress, build_client, die, env, env_int,
                    resolve_proxy, scan_channels)
from telethon.errors import FloodWaitError

CONFIG_RE = re.compile(r'(vless|vmess|trojan)://[^\s<>"\']+', re.IGNORECASE)

DEFAULT_NPV_EXTENSIONS = (".npvt", ".npv4", ".npv2", ".npv", ".npv3", ".inpv")

# Random decorative emoji pool for npv output filenames (Coxy{emoji}_{hash}.ext).
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


def normalize(cfg: str) -> str:
    """Dedup key for text links: strip the #remark, keep everything else."""
    return cfg.split("#", 1)[0]


def npv_extensions() -> tuple[str, ...]:
    """NPV_EXTENSIONS in .env overrides the default list, comma-separated."""
    raw = env("NPV_EXTENSIONS")
    if not raw:
        return DEFAULT_NPV_EXTENSIONS
    exts = tuple(e.strip().lower() for e in raw.split(",") if e.strip())
    exts = tuple(e if e.startswith(".") else f".{e}" for e in exts)
    return exts or DEFAULT_NPV_EXTENSIONS


def doc_filename(msg) -> str | None:
    """Original filename of a message's document attachment, if it has one."""
    if not msg.document:
        return None
    for attr in msg.document.attributes:
        name = getattr(attr, "file_name", None)
        if name:
            return name
    return None


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Scrape VLESS/VMess/Trojan configs and NapsternetV files from Telegram channels"
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
    p.add_argument(
        "--skip-npv",
        action="store_true",
        help="Only scrape text links, skip downloading NapsternetV file attachments",
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
    npv_dir = ROOT / env("NPV_OUTPUT_DIR", "output/npv")
    limit = args.messages_per_channel or env_int("MESSAGES_PER_CHANNEL", 40)
    concurrency = args.concurrency or env_int("CHANNEL_CONCURRENCY", 5)
    extensions = npv_extensions()
    collect_npv = not args.skip_npv

    client = build_client(
        str(ROOT / env("TELEGRAM_SESSION_NAME", "coxysession")),
        int(api_id),
        api_hash,
        resolve_proxy(args.proxy),
    )
    await client.start()

    print(
        f"Scanning {len(channels)} channel(s), {concurrency} at a time, {limit} messages each"
        + (
            f" (links + {', '.join(extensions)} files)..."
            if collect_npv
            else " (links only)..."
        )
    )

    seen_configs: set[str] = set()
    configs: list[str] = []
    seen_npv_hashes: set[str] = set()
    npv_saved = 0

    write_lock = asyncio.Lock()
    progress = Progress(len(channels))

    if collect_npv:
        npv_dir.mkdir(parents=True, exist_ok=True)

    async def worker(channel: str) -> None:
        nonlocal npv_saved
        try:
            entity = await client.get_entity(channel)
        except Exception as e:
            await progress.report(channel, ok=False, found=0, error=str(e))
            return

        found = 0
        try:
            async for msg in client.iter_messages(entity, limit=limit):
                # --- text links (vless/vmess/trojan) ---
                if msg.text:
                    for match in CONFIG_RE.finditer(msg.text):
                        c = match.group(0)
                        k = normalize(c)
                        async with write_lock:
                            if k not in seen_configs:
                                seen_configs.add(k)
                                configs.append(c)
                                found += 1

                # --- npv file attachments ---
                if collect_npv:
                    fname = doc_filename(msg)
                    if fname and fname.lower().endswith(extensions):
                        buf = BytesIO()
                        try:
                            await msg.download_media(file=buf)
                        except Exception:
                            buf = None

                        data = buf.getvalue() if buf else None
                        if data:
                            digest = hashlib.sha256(data).hexdigest()
                            async with write_lock:
                                if digest not in seen_npv_hashes:
                                    seen_npv_hashes.add(digest)
                                    ext = Path(fname).suffix
                                    emoji = random.choice(EMOJI_POOL)
                                    out_path = (
                                        npv_dir / f"Coxy{emoji}_{digest[:8]}{ext}"
                                    )
                                    out_path.write_bytes(data)
                                    npv_saved += 1
                                    found += 1
        except FloodWaitError as e:
            await progress.report(
                channel, ok=False, found=found, error=f"rate-limited, wait {e.seconds}s"
            )
            return

        await progress.report(channel, ok=True, found=found)

    await scan_channels(channels, concurrency, worker)

    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(
        "\n".join(configs) + ("\n" if configs else ""), encoding="utf-8"
    )

    print(f"\nDone: {len(configs)} unique link(s) written to {output_file}")
    if collect_npv:
        print(f"      {npv_saved} unique NapsternetV file(s) saved to {npv_dir}")


if __name__ == "__main__":
    asyncio.run(main())
