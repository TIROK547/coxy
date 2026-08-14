"""
Shared helpers for coxy's Telegram collectors:

  - .env loading (from repo root, regardless of cwd)
  - Telegram connection proxy setup (SOCKS/HTTP/MTProto) — an alternative
    to routing your whole system through a VPN just to reach Telegram
  - concurrent, rate-limited channel scanning with clean progress output
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv
from telethon import TelegramClient

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def env(key: str, default=None):
    return os.getenv(key, default)


def env_int(key: str, default: int) -> int:
    val = os.getenv(key)
    return int(val) if val not in (None, "") else default


def die(msg: str) -> None:
    print(f"[!] {msg}", file=sys.stderr)
    sys.exit(1)


# ---------------------------------------------------------------------------
# Telegram connection proxy
#
# Two ways to set it, checked in this order:
#   1. --proxy on the command line (highest priority)
#   2. TELEGRAM_PROXY in .env (used as the default when no flag is given)
#
# Accepted formats:
#   socks5://[user:pass@]host:port
#   socks4://[user:pass@]host:port
#   http://[user:pass@]host:port
#   mtproxy://secret@host:port
# ---------------------------------------------------------------------------

def resolve_proxy(cli_value: str | None) -> str | None:
    """Return the proxy URL to use: --proxy flag wins, else TELEGRAM_PROXY from .env."""
    return cli_value or env("TELEGRAM_PROXY") or None


def _socks_kwargs(scheme: str, parsed) -> dict:
    try:
        import socks
    except ImportError:
        die("socks5/socks4/http proxies need PySocks. Install it with: pip install PySocks")

    proxy_types = {"socks5": socks.SOCKS5, "socks4": socks.SOCKS4, "http": socks.HTTP}
    if not parsed.hostname or not parsed.port:
        die(f"Proxy URL is missing host or port: '{scheme}://{parsed.netloc}'")

    return {
        "proxy": (
            proxy_types[scheme],
            parsed.hostname,
            parsed.port,
            True,                # rdns
            parsed.username,     # username (or None)
            parsed.password,     # password (or None)
        )
    }


def _mtproxy_kwargs(parsed) -> dict:
    from telethon.network import ConnectionTcpMTProxyRandomizedIntermediate

    secret = parsed.username  # mtproxy://SECRET@host:port
    if not secret or not parsed.hostname or not parsed.port:
        die(
            "mtproxy:// URL must look like mtproxy://SECRET@host:port "
            "(the secret comes from your MTProto proxy provider or a tg://proxy link)"
        )
    return {
        "connection": ConnectionTcpMTProxyRandomizedIntermediate,
        "proxy": (parsed.hostname, parsed.port, secret),
    }


def build_client(session: str, api_id: int, api_hash: str, proxy_url: str | None) -> TelegramClient:
    """Build a TelegramClient, optionally routed through a SOCKS/HTTP/MTProto proxy."""
    kwargs = {}
    if proxy_url:
        parsed = urlparse(proxy_url)
        scheme = parsed.scheme.lower()
        if scheme in ("socks5", "socks4", "http"):
            kwargs.update(_socks_kwargs(scheme, parsed))
        elif scheme == "mtproxy":
            kwargs.update(_mtproxy_kwargs(parsed))
        else:
            die(
                f"Unrecognized proxy scheme '{scheme}://'. "
                "Use socks5://, socks4://, http://, or mtproxy://"
            )
        print(f"[i] Connecting to Telegram via {scheme}://{parsed.hostname}:{parsed.port}")
    return TelegramClient(session, api_id, api_hash, **kwargs)


# ---------------------------------------------------------------------------
# Concurrent channel scanning
# ---------------------------------------------------------------------------

class Progress:
    """Thread/task-safe-ish progress printer for concurrent channel scans."""

    def __init__(self, total: int):
        self.total = total
        self.done = 0
        self._lock = asyncio.Lock()

    async def report(self, channel: str, ok: bool, found: int, error: str | None = None) -> None:
        async with self._lock:
            self.done += 1
            tag = f"[{self.done}/{self.total}]"
            if ok:
                print(f"{tag} {channel}: {found} found")
            else:
                print(f"{tag} {channel}: skipped ({error})")


async def scan_channels(channels: list[str], concurrency: int, worker) -> None:
    """
    Run `worker(channel)` for every channel, `concurrency` at a time, instead of
    one channel after another. `worker` is an async callable that does its own
    error handling / progress reporting.
    """
    sem = asyncio.Semaphore(max(1, concurrency))

    async def guarded(channel: str):
        async with sem:
            await worker(channel)

    await asyncio.gather(*(guarded(ch) for ch in channels))
