import os
import re
import asyncio
from telethon import TelegramClient
from telethon.tl.types import KeyboardButtonUrl
from dotenv import load_dotenv

load_dotenv("../.env")

API_ID = int(os.getenv("TELEGRAM_API_ID"))
API_HASH = os.getenv("TELEGRAM_API_HASH")
SESSION = os.getenv("TELEGRAM_SESSION_NAME")

channels_file = os.getenv("PROXY_CHANNELS_FILE")

CHANNELS = [l.strip() for l in open(channels_file) if l.strip()]
PROXY_RE = re.compile(
    r'(?:tg://proxy|https?://(?:t\.me|telegram\.me)/proxy)\?[^\s<>"\']+',
    re.IGNORECASE
)


def normalize(proxy: str) -> str:
    """Dedup key: server+port+secret, ignoring incidental query param order/casing."""
    from urllib.parse import urlparse, parse_qs
    q = parse_qs(urlparse(proxy.replace("tg://", "https://")).query)
    return (q.get("server", [""])[0].lower(), q.get("port", [""])[0], q.get("secret", [""])[0].lower())


def extract_button_urls(msg) -> list[str]:
    """Pull URLs off inline keyboard buttons attached to the message."""
    urls = []
    if msg.reply_markup:
        for row in msg.reply_markup.rows:
            for button in row.buttons:
                if isinstance(button, KeyboardButtonUrl):
                    urls.append(button.url)
    return urls


async def main():
    client = TelegramClient(SESSION, API_ID, API_HASH)
    await client.start()

    seen = set()
    out = open(os.getenv("RAW_PROXIES_FILE"), "w")

    limit = int(os.getenv("MESSAGES_PER_CHANNEL", 10))

    for channel in CHANNELS:
        try:
            entity = await client.get_entity(channel)
        except Exception as e:
            print(f"skip {channel}: {e}")
            continue

        async for msg in client.iter_messages(entity, limit=limit):
            texts = [msg.text] if msg.text else []
            texts += extract_button_urls(msg)

            for text in texts:
                for match in PROXY_RE.finditer(text):
                    p = match.group(0)
                    k = normalize(p)
                    if k in seen:
                        continue
                    seen.add(k)
                    out.write(p + "\n")

    out.close()
    print(f"{len(seen)} unique proxies written to raw_proxies.txt")


asyncio.run(main())