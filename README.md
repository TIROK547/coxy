# coxy

Scrapes, tests, and ranks VPN configs (VLESS / VMess / Trojan) and MTProto proxies collected from public Telegram channels.

coxy pulls raw links from Telegram, speed-tests them, and produces a clean, ranked list of the fastest working configs and proxies — ready to publish or import into a client.

## How it works

The pipeline has five stages, run individually or all at once via the `coxy` CLI (`main.py`):

| Stage | Command | Script | What it does |
|---|---|---|---|
| 1 | `collect-configs` | `collectors/config_collector.py` | Scrapes VLESS/VMess/Trojan links from a list of Telegram channels |
| 2 | `collect-proxies` | `collectors/proxy_collector.py` | Scrapes MTProto/HTTP/SOCKS5 proxy links from Telegram |
| 3 | `test-configs` | `delay-test/test_configs.sh` | Speed-tests scraped configs using [xray-knife](https://github.com/lilendian0x00/xray-knife) |
| 4 | `test-proxies` | `delay-test/test_proxies.py` | Checks liveness/latency of scraped proxies |
| 5 | `best` | `best_result.py` (via `main.py best`) | Picks the top-N fastest passing configs from the test results |

Run `all` to execute the whole pipeline in order. The two `collect-*` steps scan their channels concurrently rather than one at a time, and can go through a proxy if Telegram is blocked where you're running coxy (see [Reaching Telegram from a censored region](#reaching-telegram-from-a-censored-region)). Before `test-configs` runs, `all` will remind you to turn any VPN **off** for that step, since it measures delay from your own connection — pass `--yes`/`-y` to skip that prompt.

## Requirements

- Python 3.10+
- [xray-knife](https://github.com/lilendian0x00/xray-knife) available on `PATH` (or point to it via `XRAY_KNIFE` in `.env`)
- A Telegram account with an API ID/hash ([my.telegram.org](https://my.telegram.org))

## Installation

```bash
git clone https://github.com/TIROK547/coxy.git
cd coxy
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` and fill in at least:

```env
TELEGRAM_API_ID=
TELEGRAM_API_HASH=
```

Then populate the channel lists coxy will scrape from:

- `collectors/channels/config_channels.lst` — Telegram channels to pull VLESS/VMess/Trojan configs from
- `collectors/channels/proxy_channels.lst` — Telegram channels to pull MTProto/HTTP/SOCKS5 proxies from

(one channel per line)

## Usage

Run the full pipeline:

```bash
python main.py all
```

Or run individual stages:

```bash
python main.py collect-configs
python main.py collect-proxies
python main.py test-configs
python main.py test-proxies
python main.py best -n 20
```

`test-proxies` supports extra flags:

```bash
python main.py test-proxies -i output/raw_proxies.txt -o output/result_proxies.txt -t 5 -c 300 --strict
```

| Flag | Description |
|---|---|
| `-i, --input` | Override input proxy file |
| `-o, --output` | Override output proxy file |
| `-t, --timeout` | Per-proxy timeout (seconds) |
| `-c, --concurrency` | Max concurrent checks |
| `--strict` | Slower but more accurate verification |

`all` accepts `--keep-going` to continue the pipeline even if a step fails.

## Reaching Telegram from a censored region

If Telegram is blocked where you're running coxy, point the `collect-*` steps at a proxy instead of turning a system-wide VPN on and off around them. Two ways to set it, checked in this order:

1. **Per-run flag** (highest priority):

   ```bash
   python main.py collect-configs --proxy socks5://user:pass@host:port
   python main.py all --proxy mtproxy://SECRET@host:port
   ```

2. **Default in `.env`** — set it once and every `collect-*`/`all` run uses it automatically:

   ```env
   TELEGRAM_PROXY=socks5://user:pass@host:port
   ```

Supported formats for both:

| Scheme | Example |
|---|---|
| `socks5://` | `socks5://user:pass@1.2.3.4:1080` (auth optional) |
| `socks4://` | `socks4://1.2.3.4:1080` |
| `http://` | `http://user:pass@1.2.3.4:8080` |
| `mtproxy://` | `mtproxy://SECRET@1.2.3.4:443` (secret from your MTProto provider or a `tg://proxy` link) |

`socks5`/`socks4`/`http` proxies need `PySocks` (already in `requirements.txt`).

## Speeding up collection

By default `collect-configs` and `collect-proxies` scan up to 5 channels concurrently instead of going through the channel list one by one. Tune it with `-j/--channel-concurrency`, or `CHANNEL_CONCURRENCY` in `.env`:

```bash
python main.py collect-configs -j 10
```

Push this too high and you're more likely to hit Telegram's rate limits (coxy will report and skip a channel if that happens, rather than stalling the whole run) — 5–10 is a reasonable range for most accounts.

## Configuration reference (`.env`)

| Variable | Purpose |
|---|---|
| `TELEGRAM_API_ID` / `TELEGRAM_API_HASH` | Telegram API credentials |
| `TELEGRAM_SESSION_NAME` | Telethon session file name |
| `CONFIG_CHANNELS_FILE` / `PROXY_CHANNELS_FILE` | Paths to channel list files |
| `OUTPUT_DIR` | Directory for all output files |
| `RAW_CONFIGS_FILE` / `RAW_PROXIES_FILE` | Raw scrape output |
| `OUTPUT_CONFIGS_FILE` / `OUTPUT_PROXIES_FILE` | Test-result output |
| `TOP_N` | Default number of configs kept by `best` |
| `TELEGRAM_PROXY` | Default proxy for reaching Telegram (`socks5://`, `socks4://`, `http://`, or `mtproxy://`) — see [Reaching Telegram from a censored region](#reaching-telegram-from-a-censored-region) |
| `MESSAGES_PER_CHANNEL` | How many recent messages to scan per channel |
| `CHANNEL_CONCURRENCY` | How many channels `collect-configs`/`collect-proxies` scan at once (default 5) |
| `XRAY_KNIFE` | Path to the xray-knife binary |
| `XRAY_KNIFE_THREADS` | Concurrency for config speed-testing |
| `PROXY_CHECK_TIMEOUT` / `PROXY_CHECK_CONCURRENCY` | Proxy liveness-check tuning |

## Output

After a full run, `output/` contains:

- `raw_configs.txt` / `raw_proxies.txt` — everything scraped, unfiltered
- `result_configs.csv` — configs with test status and delay
- `result_proxies.txt` — proxies with liveness/latency results
- `top{N}_configs.txt` — the final ranked shortlist, ready to share or import

## Notes

- If Telegram is restricted in your region, use `--proxy`/`TELEGRAM_PROXY` for the `collect-*` steps rather than a system-wide VPN — see [Reaching Telegram from a censored region](#reaching-telegram-from-a-censored-region).
- Run `test-configs` with your VPN **off** to get accurate delay measurements — `all` will remind you.
- coxy is a scraping/aggregation tool — it doesn't generate configs or proxies itself, and the quality of results depends entirely on the source channels you configure.

## License

No license specified yet — add one if you intend for others to reuse this code.
