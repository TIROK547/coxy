import re, asyncio, os
from telethon import TelegramClient
from dotenv import load_dotenv

load_dotenv("../.env")

API_ID = int(os.getenv("TELEGRAM_API_ID"))
API_HASH = os.getenv("TELEGRAM_API_HASH")
SESSION = os.getenv("TELEGRAM_SESSION_NAME")

channels_file = "../"+os.getenv("CONFIG_CHANNELS_FILE")

CHANNELS = [l.strip() for l in open(channels_file) if l.strip()]
CONFIG_RE = re.compile(r'(vless|vmess|trojan)://[^\s<>"\']+', re.IGNORECASE)


def normalize(cfg: str) -> str:
    """Dedup key: strip the #remark, keep everything else."""
    return cfg.split("#", 1)[0]


async def main():
    client = TelegramClient(SESSION, API_ID, API_HASH)
    await client.start()

    seen = set()
    out = open("raw_configs.txt", "w")

    limit = os.getenv("MESSAGES_PER_CHANNEL", 10)

    for channel in CHANNELS:
        try:
            entity = await client.get_entity(channel)
        except Exception as e:
            print(f"skip {channel}: {e}")
            continue

        async for msg in client.iter_messages(entity, limit):
            if not msg.text:
                continue
            for match in CONFIG_RE.finditer(msg.text):
                for c in match.group(0):
                    k = normalize(c)
                    if k in seen:
                        continue
                    seen.add(k)
                    out.write(c + "\n")

    out.close()
    print(f"{len(seen)} unique configs written to raw_configs.txt")


asyncio.run(main())
