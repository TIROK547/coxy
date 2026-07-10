import re, asyncio, os
from telethon import TelegramClient
from dotenv import load_dotenv

load_dotenv(".env")

API_ID = int(os.getenv("TELEGRAM_API_ID"))
API_HASH = os.getenv("TELEGRAM_API_HASH")
SESSION = os.getenv("TELEGRAM_SESSION_NAME")

channels_file = os.getenv("CONFIG_CHANNELS_FILE")
output_file = os.getenv("RAW_CONFIGS_FILE")

CHANNELS = [l.strip() for l in open(channels_file) if l.strip()]
CONFIG_RE = re.compile(r'(vless|vmess|trojan)://[^\s<>"\']+', re.IGNORECASE)


def normalize(cfg: str) -> str:
    """Dedup key: strip the #remark, keep everything else."""
    return cfg.split("#", 1)[0]


async def main():
    client = TelegramClient(SESSION, API_ID, API_HASH)
    await client.start()

    seen = set()
    os.makedirs(os.path.dirname(output_file), exist_ok=True)
    out = open(output_file, "w")

    limit = int(os.getenv("MESSAGES_PER_CHANNEL", 10))

    for i in range(len(CHANNELS)):
        channel = CHANNELS[i]
        try:
            entity = await client.get_entity(channel)
        except Exception as e:
            print(f"{i}: skip {channel}: {e}")
            continue
        print(f"{i}: Scanned {channel} Successfuly")


        async for msg in client.iter_messages(entity, limit=limit):
            if not msg.text:
                continue
            for match in CONFIG_RE.finditer(msg.text):
                c = match.group(0)
                k = normalize(c)
                if k in seen:
                    continue
                seen.add(k)
                out.write(c + "\n")

    out.close()
    print(f"{len(seen)} unique configs written to {output_file}")


asyncio.run(main())