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

Run `all` to execute the whole pipeline in order, with prompts to toggle your VPN on/off at the points where that matters (censorship-region scraping vs. accurate local latency testing).

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
| `MESSAGES_PER_CHANNEL` | How many recent messages to scan per channel |
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

- Run `collect-*` from behind a VPN if you're in a region where Telegram is restricted.
- Run `test-configs` with your VPN **off** to get accurate delay measurements.
- coxy is a scraping/aggregation tool — it doesn't generate configs or proxies itself, and the quality of results depends entirely on the source channels you configure.

## License

No license specified yet — add one if you intend for others to reuse this code.
