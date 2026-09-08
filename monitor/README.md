# Datum Work read-only monitor

Run from the repository root with Python 3.10 or newer. There are no Python package dependencies:

```sh
python3 monitor/service.py
```

The service listens on `127.0.0.1:8810`. The Next.js application proxies it on the server; browser clients do not need access to private gateway ports. `GET /api/snapshot` returns `{generatedAt, sources, events}`, with up to 100 newest work events, source connection state, last work receipt time, and each source's latest event. `GET /health` reports process health and individual source states. A healthy process can have disconnected sources. Data is kept in memory and resets on restart.

| Source | Default endpoint | Declared PoW |
| --- | --- | --- |
| AlphaPool | `stratum+tcp://us1.alphapool.tech:5555` | BLAKE2b |
| PyBlock BLAKE2b | `stratum+tcp://b.pyblock.xyz:23115` | BLAKE2b |
| XOR Pool | `stratum+tcp://datum.xorpool.com:23335` | BLAKE2b |
| Our DATUM | `http://127.0.0.1:7152/templates.json` | BLAKE2b |

The PyBlock link originally supplied is their SHA-256 site. The default here uses the operator's [BLAKE2b WAVICLES gateway](https://b.pyblock.xyz:8443/), consistent with the other three sources. Change both endpoint and PoW declaration to monitor their original SHA-256 DATUM service:

```sh
PYBLOCK_STRATUM_URL=stratum+tcp://pool.pyblock.xyz:23334 \
PYBLOCK_POW_ALGORITHM=sha256d \
python3 monitor/service.py
```

Defaults come from the operators' public [AlphaPool](https://knots.alphapool.tech), [PyBlock](https://b.pyblock.xyz:8443/), and [XOR Pool](https://xorpool.com/connect) pages. Availability is observed at runtime.

## Configuration

- `DATUM_MONITOR_HOST` / `DATUM_MONITOR_PORT`: bind address and port; also `--host` / `--port` flags.
- `DATUM_MONITOR_STALE_SECONDS`: age after which a source is shown as stale, default 600 seconds. Own template age uses its publication timestamp; remote work age uses monitor receipt. A successful HTTP response does not make an old template fresh. Own records without a publication time, or explicitly marked inactive/stale, also show as stale.
- `DATUM_MONITOR_ALPHA_URL`, `DATUM_MONITOR_PYBLOCK_URL`, `DATUM_MONITOR_XOR_URL`, `DATUM_MONITOR_OWN_URL`: source endpoints. An empty URL disables that source. Stratum TCP and TLS (`stratum+ssl`) are supported.
- `DATUM_MONITOR_ALPHA_POW`, `DATUM_MONITOR_PYBLOCK_POW`, `DATUM_MONITOR_XOR_POW`, `DATUM_MONITOR_OWN_POW`: declared algorithm, normally `blake2b` or `sha256d`. Algorithm labels describe configured endpoints, not verified work.
- `PYBLOCK_STRATUM_URL` / `PYBLOCK_POW_ALGORITHM` are convenience aliases; the `DATUM_MONITOR_…` settings take precedence.
- `DATUM_MONITOR_OWN_FALLBACK_URL`: alternate full-template feed. With the default own URL, this defaults to the existing read-only index at `http://127.0.0.1:3336/v1/templates?limit=100`. An explicit own URL disables that automatic fallback unless a fallback is also supplied. An empty fallback disables it.
- `DATUM_MONITOR_USERPASS`: optional `username:password` to send `mining.authorize`. Per-source `DATUM_MONITOR_ALPHA_USERPASS`, `DATUM_MONITOR_PYBLOCK_USERPASS`, and `DATUM_MONITOR_XOR_USERPASS` override it. Keep values in the process environment; they are never returned by snapshot endpoints.

Remote connections send `mining.subscribe` only by default. They never send `mining.submit`, proxy miner traffic, or change pool settings. Some pools may withhold jobs without authorization; their source will remain `awaiting-work` until work arrives. Pool retries run every 10 seconds. Own feeds are polled every 5 seconds. A successful fallback is shown in `activeUrl`. Keep the monitor and private DATUM gateway bound to loopback; when running in a container, configure the host-accessible feed address explicitly.

## Protocol limits

BLAKE2b pools here use a Sia-shaped dialect. The observed nine-parameter `mining.notify` includes a 35- or 39-byte work commitment in the position Bitcoin Stratum calls `coinbase1`. This is not a Bitcoin coinbase transaction. Its previous-hash field can also be transformed. These jobs use `format: "sia-stratum"`, preserve `raw`, `workFields`, `workCommitment`, and `workPreviousHash`, and do not invent heights, Bitcoin parents, coinbase payouts, transaction counts, or complete transaction lists. Short four/five-field jobs are also retained as opaque Sia work.

The own HTTP feeds provide real full template fields: height, previous block hash, coinbase parts, merkle branches, BLAKE2b commitments, and publication metadata. Both gateway `templates.json` and the read-only share index `/v1/templates` are supported. `format: "datum-template"` identifies these events. The index's positive `headerTransactionCount` is also exposed as `transactionCount`; the local publisher defines this as the full transaction count including coinbase. Original rows remain in `raw`; `publishedAt` comes from their source timestamp, while `receivedAt` records monitor receipt. Publication state can refresh without generating a duplicate job event. These are template data, not a claim that a block was mined or confirmed.

SHA-256 nine-parameter jobs use `format: "bitcoin-stratum-v1"`. Height is decoded only from an actual BIP34 coinbase prefix, and the prior block hash is converted from Stratum word order. Merkle branches alone cannot establish the transaction count. This service is independent of upstream Stratum Work's Bitcoin-only analytics and does not feed BLAKE2b jobs into them.

## Tests

```sh
python3 -m unittest discover -s monitor/tests -v
```

Tests verify both live-feed shapes, Bitcoin/Sia separation, absent inferred metadata, bounded deduplication, receipt updates, configuration precedence, URL redaction, an actual local HTTP snapshot, and subscribe-only behavior against a local fake Stratum server. They do not connect to mining pools or submit shares.
