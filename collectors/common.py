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
#   tg://proxy?server=...&port=...&secret=...            (Telegram share link)
#   https://t.me/proxy?server=...&port=...&secret=...    (same, as a web link)
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


def _mtproxy_kwargs_from_parts(host: str | None, port, secret: str | None, source: str) -> dict:
    from telethon.network import ConnectionTcpMTProxyRandomizedIntermediate

    if not secret or not host or not port:
        die(
            f"Couldn't read server/port/secret from the {source}. "
            "Expected mtproxy://SECRET@host:port, or a tg://proxy / t.me/proxy link "
            "with server=, port=, and secret= query params."
        )
    return {
        "connection": ConnectionTcpMTProxyRandomizedIntermediate,
        "proxy": (host, int(port), secret),
    }


def _mtproxy_kwargs(parsed) -> dict:
    # mtproxy://SECRET@host:port
    return _mtproxy_kwargs_from_parts(parsed.hostname, parsed.port, parsed.username, "mtproxy:// URL")


def _mtproxy_link_kwargs(parsed) -> dict:
    # tg://proxy?server=...&port=...&secret=...
    # https://t.me/proxy?server=...&port=...&secret=...
    from urllib.parse import parse_qs
    q = parse_qs(parsed.query)
    host = q.get("server", [None])[0]
    port = q.get("port", [None])[0]
    secret = q.get("secret", [None])[0]
    return _mtproxy_kwargs_from_parts(host, port, secret, "proxy link")


def build_client(session: str, api_id: int, api_hash: str, proxy_url: str | None) -> TelegramClient:
    """Build a TelegramClient, optionally routed through a SOCKS/HTTP/MTProto proxy."""
    kwargs = {}
    if proxy_url:
        parsed = urlparse(proxy_url)
        scheme = parsed.scheme.lower()
        is_web_share_link = scheme in ("http", "https") and parsed.netloc.lower() in (
            "t.me", "telegram.me", "www.t.me", "www.telegram.me",
        ) and parsed.path.lower() == "/proxy"

        if is_web_share_link:
            kwargs.update(_mtproxy_link_kwargs(parsed))
            desc = f"mtproxy (from {parsed.netloc}{parsed.path} link)"
        elif scheme == "tg" and parsed.netloc.lower() == "proxy":
            kwargs.update(_mtproxy_link_kwargs(parsed))
            desc = "mtproxy (from tg://proxy link)"
        elif scheme in ("socks5", "socks4", "http"):
            kwargs.update(_socks_kwargs(scheme, parsed))
            desc = f"{scheme}://{parsed.hostname}:{parsed.port}"
        elif scheme == "mtproxy":
            kwargs.update(_mtproxy_kwargs(parsed))
            desc = f"mtproxy://{parsed.hostname}:{parsed.port}"
        else:
            die(
                f"Unrecognized proxy value starting with '{proxy_url[:30]}...'. "
                "Use socks5://, socks4://, http://, mtproxy://secret@host:port, "
                "or a tg://proxy / t.me/proxy share link."
            )
        print(f"[i] Connecting to Telegram via {desc}")
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
