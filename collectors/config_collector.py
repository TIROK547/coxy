import re, asyncio, os
from telethon import TelegramClient
from dotenv import load_dotenv

load_dotenv("../.env")

API_ID = 12345  # from my.telegram.org
API_HASH = "xxxxxxxx"
SESSION = "collector"

CHANNELS = [l.strip() for l in open("channels.txt") if l.strip()]
CONFIG_RE = re.compile(r'(vless|vmess|trojan)://[^\s<>"\']+', re.IGNORECASE)


def normalize(cfg: str) -> str:
    """Dedup key: strip the #remark, keep everything else."""
    return cfg.split("#", 1)[0]


async def main():
    client = TelegramClient(SESSION, API_ID, API_HASH)
    await client.start()

    seen = set()
    out = open("raw_configs.txt", "w")

    for channel in CHANNELS:
        try:
            entity = await client.get_entity(channel)
        except Exception as e:
            print(f"skip {channel}: {e}")
            continue

        async for msg in client.iter_messages(entity, limit=10):
            if not msg.text:
                continue
            for match in CONFIG_RE.finditer(msg.text):
                cfg = match.group(0)
                key = normalize(cfg)
                if key in seen:
                    continue
                seen.add(key)
                out.write(cfg + "\n")

    out.close()
    print(f"{len(seen)} unique configs written to raw_configs.txt")


asyncio.run(main())
