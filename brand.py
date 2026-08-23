"""
Rebrands passing configs from xray-knife's result CSV: sets each link's
remark to "{country flag}| Coxy", using the two-letter country code that
xray-knife already reports in its `location` column (it's just the `loc=`
field from Cloudflare's /cdn-cgi/trace response, no extra geoIP lookup
needed).

vless/trojan/ss carry their remark in the URI fragment (`...#remark`).
vmess is different: the whole link is a base64-encoded JSON blob and the
remark lives in the `"ps"` key inside it, not in a fragment — rewriting it
means decoding, patching, and re-encoding that JSON.
"""

from __future__ import annotations

import base64
import json
from urllib.parse import quote


def flag_emoji(country_code: str | None) -> str:
    """Two-letter ISO country code -> regional-indicator flag emoji."""
    cc = (country_code or "").strip().upper()
    if len(cc) != 2 or not cc.isalpha():
        return "🏳️"
    return "".join(chr(0x1F1E6 + ord(ch) - ord("A")) for ch in cc)


def _rebrand_vmess(raw: str, remark: str) -> str:
    b64 = raw[len("vmess://") :].split("#", 1)[0]
    padded = b64 + "=" * (-len(b64) % 4)
    try:
        data = json.loads(base64.b64decode(padded).decode("utf-8"))
    except Exception:
        return raw  # malformed / can't safely patch — leave it untouched
    data["ps"] = remark
    new_b64 = base64.b64encode(
        json.dumps(data, ensure_ascii=False).encode("utf-8")
    ).decode()
    return f"vmess://{new_b64}"


def rebrand_link(raw: str, remark: str) -> str:
    """Return `raw` with its remark replaced by `remark`."""
    scheme = raw.split("://", 1)[0].lower()
    if scheme == "vmess":
        return _rebrand_vmess(raw, remark)
    # vless / trojan / ss / etc.: remark is the URI fragment.
    base = raw.split("#", 1)[0]
    return f"{base}#{quote(remark, safe='')}"


def brand_row(raw: str, country_code: str | None, label: str = "Coxy") -> str:
    """Convenience wrapper: build the "{flag}| {label}" remark and apply it."""
    remark = f"{flag_emoji(country_code)}| {label}"
    return rebrand_link(raw, remark)
