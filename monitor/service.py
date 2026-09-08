#!/usr/bin/env python3
"""Read-only Stratum and DATUM observer. Python 3.10+, standard library only."""

from __future__ import annotations

import argparse
from collections import OrderedDict
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
import os
import socket
import ssl
import threading
import time
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen

LOG = logging.getLogger("datum-monitor")
MAX_PAYLOAD = 4 * 1024 * 1024
MAX_STRATUM_MESSAGE = 256 * 1024


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def public_url(url: str) -> str:
    """Do not disclose endpoint credentials or query-string tokens in snapshots."""
    try:
        parts = urlsplit(url)
        hostname = parts.hostname or ""
        host = f"[{hostname}]" if ":" in hostname else hostname
        if parts.port:
            host += f":{parts.port}"
        return urlunsplit((parts.scheme, host, parts.path, "", ""))
    except ValueError:
        return "invalid endpoint"


def _hex(value, length=None):
    if not isinstance(value, str) or len(value) % 2 or (length is not None and len(value) != length):
        return False
    try:
        bytes.fromhex(value)
        return True
    except ValueError:
        return False


def _compact_size(data: bytes, offset: int):
    value = data[offset]
    offset += 1
    if value < 253:
        return value, offset
    size = {253: 2, 254: 4, 255: 8}[value]
    if offset + size > len(data):
        raise ValueError("Truncated CompactSize")
    return int.from_bytes(data[offset:offset + size], "little"), offset + size


def coinbase_height(coinbase1: str):
    """Decode only an actual BIP34 coinbase input, without inventing nonce bytes."""
    try:
        data = bytes.fromhex(coinbase1)
        offset = 6 if data[4:6] == b"\x00\x01" else 4
        inputs, offset = _compact_size(data, offset)
        if inputs != 1 or data[offset:offset + 36] != b"\x00" * 32 + b"\xff" * 4:
            return None
        _, offset = _compact_size(data, offset + 36)
        size = data[offset]
        if not 1 <= size <= 5 or offset + 1 + size > len(data):
            return None
        number = data[offset + 1:offset + 1 + size]
        if number[-1] & 0x80:
            return None
        return int.from_bytes(number, "little")
    except (ValueError, IndexError, TypeError):
        return None


def normalize_notify(message: dict, source: dict, received_at=None):
    params = message.get("params")
    if message.get("method") != "mining.notify" or not isinstance(params, list) or not params:
        return None
    event = {
        "sourceId": source["id"], "sourceName": source["name"],
        "receivedAt": received_at or iso_now(), "jobId": str(params[0]),
        "powAlgorithm": source["powAlgorithm"], "raw": deepcopy(message),
    }
    if len(params) == 9 and isinstance(params[4], list) and source["powAlgorithm"].lower() == "blake2b":
        # The observed DATUM BLAKE2b dialect retains nine notify parameters,
        # but its 35/39-byte "coinbase1" is an opaque commitment and its parent
        # can be transformed. It cannot be decoded as Bitcoin transaction work.
        event.update(format="sia-stratum", workFields=deepcopy(params[1:]),
                     workPreviousHash=params[1], workCommitment=params[2],
                     version=params[5], nbits=params[6], ntime=params[7], cleanJobs=params[8])
    elif len(params) == 9 and isinstance(params[4], list) and source["powAlgorithm"].lower() in ("sha256", "sha256d"):
        event.update(format="bitcoin-stratum-v1", stratumPreviousHash=params[1],
                     coinbase1=params[2], coinbase2=params[3], merkleBranches=params[4],
                     version=params[5], nbits=params[6], ntime=params[7], cleanJobs=params[8])
        if _hex(params[1], 64):
            event["previousBlockHash"] = "".join(reversed([params[1][i:i + 8] for i in range(0, 64, 8)]))
        if isinstance(params[2], str):
            height = coinbase_height(params[2])
            if height is not None:
                event["height"] = height
    elif len(params) in (4, 5):
        # Sia-shaped BLAKE2b work is not a Bitcoin coinbase or block template.
        # Retain opaque fields without treating a hidden parent as a block hash.
        event.update(format="sia-stratum", workFields=deepcopy(params[1:]))
        if isinstance(params[-1], bool):
            event["cleanJobs"] = params[-1]
    else:
        event["format"] = "unknown-stratum"
    identity = json.dumps([source["id"], message], sort_keys=True, separators=(",", ":"))
    event["id"] = hashlib.sha256(identity.encode()).hexdigest()[:24]
    return event


def normalize_template(row: dict, source: dict, received_at=None):
    if not isinstance(row, dict):
        return None
    job_id = row.get("datumJobId") or row.get("jobId") or row.get("jobSequence")
    if job_id is None:
        return None
    event = {
        "sourceId": source["id"], "sourceName": source["name"],
        "receivedAt": received_at or iso_now(), "jobId": str(job_id),
        "format": "datum-template", "powAlgorithm": row.get("powAlgorithm", source["powAlgorithm"]),
        "raw": deepcopy(row),
    }
    for field in ("height", "previousBlockHash", "coinbase1", "coinbase2", "merkleBranches",
                  "transactionCount", "coinbaseValueSats", "cleanJobs", "version", "nbits", "ntime",
                  "jobSequence", "registered", "registrationSignature", "publicationState",
                  "active", "stale", "headerVersion", "headerTimeOffset", "headerTransactionCount",
                  "headerFlags", "xorKeyMaskClearBits", "xorKey", "mergeMiningRhs", "blake2bCommitment"):
        if row.get(field) is not None:
            event[field] = deepcopy(row[field])
    # The M1N3 publisher populates this from header-v2 transaction_count,
    # falling back to non-coinbase txn_count + 1 in datum_local_pool.c.
    # It is an actual declared count including coinbase, not a merkle inference.
    header_count = row.get("headerTransactionCount")
    if "transactionCount" not in event and isinstance(header_count, int) and not isinstance(header_count, bool) and header_count > 0:
        event["transactionCount"] = header_count
    if row.get("solanaTemplate") or row.get("template"):
        event["solanaTemplate"] = row.get("solanaTemplate") or row["template"]
    published_ms = row.get("createdAtMs") or row.get("acceptedAtUnixMs")
    if isinstance(published_ms, (float, int)) and not isinstance(published_ms, bool):
        try:
            event["publishedAt"] = datetime.fromtimestamp(published_ms / 1000, timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        except (ValueError, OverflowError, OSError):
            pass
    identity = [source["id"], str(job_id), row.get("jobSequence"), published_ms, row.get("previousBlockHash")]
    event["id"] = hashlib.sha256(json.dumps(identity).encode()).hexdigest()[:24]
    return event


class MonitorState:
    def __init__(self, sources, max_events=100, stale_seconds=600):
        self.lock = threading.Lock()
        self.max_events = max_events
        self.stale_seconds = stale_seconds
        self.events = OrderedDict()
        self.seen = OrderedDict()
        self.sources = {source["id"]: {
            **{key: source[key] for key in ("id", "name", "kind", "powAlgorithm")},
            "url": public_url(source["url"]), "status": "connecting", "lastSeen": None,
            "lastCheckedAt": None, "error": None, "latest": None,
        } for source in sources}

    def update(self, source_id, **fields):
        with self.lock:
            self.sources[source_id].update(fields, lastCheckedAt=iso_now())

    def add(self, event):
        with self.lock:
            source = self.sources[event["sourceId"]]
            source.update(status="live", error=None, lastCheckedAt=iso_now())
            event_id = event["id"]
            if event_id in self.seen:
                # Publication receipts can mature while the underlying job stays identical.
                old = self.events.get(event_id)
                if old is not None:
                    event["receivedAt"] = old["receivedAt"]
                    self.events[event_id] = deepcopy(event)
                    if source["latest"] and source["latest"]["id"] == event_id:
                        source["latest"] = deepcopy(event)
                return False
            self.seen[event_id] = None
            if len(self.seen) > 2000:
                self.seen.popitem(last=False)
            self.events[event_id] = deepcopy(event)
            while len(self.events) > self.max_events:
                self.events.popitem(last=False)
            source.update(lastSeen=event["receivedAt"], latest=deepcopy(event))
            return True

    def snapshot(self):
        with self.lock:
            sources = deepcopy(list(self.sources.values()))
            for source in sources:
                latest = source["latest"]
                if source["status"] == "live" and latest:
                    if source["kind"] == "http" and not latest.get("publishedAt"):
                        source["status"] = "stale"
                        continue
                    timestamp = latest.get("publishedAt", latest["receivedAt"]) if source["kind"] == "http" else latest["receivedAt"]
                    try:
                        age = (datetime.now(timezone.utc) - datetime.fromisoformat(timestamp.replace("Z", "+00:00"))).total_seconds()
                        if age > self.stale_seconds or latest.get("stale") is True or latest.get("active") is False:
                            source["status"] = "stale"
                    except (ValueError, TypeError):
                        source["status"] = "stale"
            return {"generatedAt": iso_now(), "sources": sources,
                    "events": deepcopy(list(reversed(self.events.values())))}


def subscription_messages(userpass=None):
    messages = [{"id": 1, "method": "mining.subscribe", "params": ["datum.work/0.1"]}]
    if userpass:
        username, _, password = userpass.partition(":")
        messages.append({"id": 2, "method": "mining.authorize", "params": [username, password]})
    return messages


def watch_stratum(source, state, stop, userpass=None):
    try:
        parsed = urlsplit(source["url"])
        valid = parsed.scheme in ("stratum+tcp", "stratum+ssl", "stratum+tls") and parsed.hostname and parsed.port
    except ValueError:
        valid = False
    if not valid:
        state.update(source["id"], status="error", error="Expected stratum+tcp://host:port or stratum+ssl://host:port")
        return
    while not stop.is_set():
        state.update(source["id"], status="connecting", error=None)
        try:
            with socket.create_connection((parsed.hostname, parsed.port), timeout=10) as connection:
                if parsed.scheme != "stratum+tcp":
                    connection = ssl.create_default_context().wrap_socket(connection, server_hostname=parsed.hostname)
                with connection:
                    connection.settimeout(2)
                    for message in subscription_messages(userpass):
                        connection.sendall((json.dumps(message) + "\n").encode())
                    state.update(source["id"], status="awaiting-work", error=None)
                    buffer = b""
                    while not stop.is_set():
                        try:
                            chunk = connection.recv(65536)
                        except socket.timeout:
                            continue
                        if not chunk:
                            raise ConnectionError("Pool closed the connection")
                        buffer += chunk
                        if len(buffer) > MAX_STRATUM_MESSAGE:
                            raise ValueError("Pool message exceeded size limit")
                        while b"\n" in buffer:
                            line, buffer = buffer.split(b"\n", 1)
                            if not line.strip():
                                continue
                            message = json.loads(line)
                            if not isinstance(message, dict):
                                continue
                            if message.get("id") == 2 and (message.get("error") or message.get("result") is False):
                                raise PermissionError("Pool rejected monitoring authorization")
                            if message.get("id") == 1 and message.get("error"):
                                raise PermissionError("Pool rejected mining.subscribe")
                            event = normalize_notify(message, source)
                            if event:
                                state.add(event)
        except Exception as exc:
            # Connection errors are bounded, and never contain credential-bearing requests.
            error = f"{type(exc).__name__}: {str(exc)[:160]}"
            state.update(source["id"], status="error", error=error)
            LOG.warning("%s: %s", source["name"], error)
        stop.wait(10)


def fetch_template_feed(url):
    request = Request(url, headers={"Accept": "application/json", "User-Agent": "datum.work/0.1"})
    with urlopen(request, timeout=5) as response:
        data = response.read(MAX_PAYLOAD + 1)
    if len(data) > MAX_PAYLOAD:
        raise ValueError("Template feed exceeded size limit")
    payload = json.loads(data)
    if not isinstance(payload, dict) or not isinstance(payload.get("templates"), list):
        raise ValueError("Expected a JSON object containing a templates array")
    return payload["templates"]


def watch_templates(source, state, stop, interval=5):
    endpoints = [source["url"]] + source.get("fallbackUrls", [])
    while not stop.is_set():
        errors = []
        for url in endpoints:
            try:
                rows = fetch_template_feed(url)
                def sort_key(row):
                    return row.get("createdAtMs") or row.get("acceptedAtUnixMs") or row.get("jobSequence") or 0
                rows = sorted((row for row in rows if isinstance(row, dict)), key=sort_key)[-100:]
                valid_rows = 0
                for row in rows:
                    event = normalize_template(row, source)
                    if event:
                        valid_rows += 1
                        state.add(event)
                state.update(source["id"], status="live" if valid_rows else "awaiting-work", error=None,
                             activeUrl=public_url(url))
                break
            except Exception as exc:
                errors.append(f"{type(exc).__name__}")
        else:
            state.update(source["id"], status="error", error="Template feed unavailable (" + ", ".join(errors) + ")")
        stop.wait(interval)


def sources_from_env(environ=None):
    environ = os.environ if environ is None else environ
    specs = [
        ("alpha", "AlphaPool", "ALPHA", "stratum+tcp://us1.alphapool.tech:5555", "blake2b"),
        ("pyblock", "PyBlock BLAKE2b", "PYBLOCK", "stratum+tcp://b.pyblock.xyz:23115", "blake2b"),
        ("xor", "XOR Pool", "XOR", "stratum+tcp://datum.xorpool.com:23335", "blake2b"),
        ("own", "Our DATUM", "OWN", "http://127.0.0.1:7152/templates.json", "blake2b"),
    ]
    sources = []
    for source_id, name, prefix, default_url, algorithm in specs:
        url = environ.get(f"DATUM_MONITOR_{prefix}_URL", environ.get(f"{prefix}_STRATUM_URL", default_url))
        if not url:
            continue
        source = {"id": source_id, "name": name, "kind": "http" if source_id == "own" else "stratum",
                  "url": url, "powAlgorithm": environ.get(f"DATUM_MONITOR_{prefix}_POW", environ.get(f"{prefix}_POW_ALGORITHM", algorithm))}
        if source_id == "pyblock":
            source["name"] = "PyBlock BLAKE2b" if source["powAlgorithm"].lower() == "blake2b" else "PyBlock SHA-256" if source["powAlgorithm"].lower() in ("sha256", "sha256d") else "PyBlock"
        if source_id == "own":
            default_fallback = "http://127.0.0.1:3336/v1/templates?limit=100" if url == default_url else ""
            fallback = environ.get("DATUM_MONITOR_OWN_FALLBACK_URL", default_fallback)
            source["fallbackUrls"] = [fallback] if fallback else []
        sources.append(source)
    return sources


def make_handler(state):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            path = urlsplit(self.path).path
            if path == "/api/snapshot":
                payload = state.snapshot()
            elif path == "/health":
                snapshot = state.snapshot()
                payload = {"status": "ok", "generatedAt": snapshot["generatedAt"],
                           "sources": {source["id"]: source["status"] for source in snapshot["sources"]}}
            else:
                self.send_error(404)
                return
            data = json.dumps(payload, separators=(",", ":")).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, format, *args):
            LOG.debug(format, *args)

    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=os.getenv("DATUM_MONITOR_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("DATUM_MONITOR_PORT", "8810")))
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    sources = sources_from_env()
    state = MonitorState(sources, stale_seconds=float(os.getenv("DATUM_MONITOR_STALE_SECONDS", "600")))
    stop = threading.Event()
    server = ThreadingHTTPServer((args.host, args.port), make_handler(state))
    for source in sources:
        if source["kind"] == "http":
            target, target_args = watch_templates, (source, state, stop)
        else:
            credentials = os.getenv(f"DATUM_MONITOR_{source['id'].upper()}_USERPASS") or os.getenv("DATUM_MONITOR_USERPASS")
            target, target_args = watch_stratum, (source, state, stop, credentials)
        threading.Thread(target=target, args=target_args, daemon=True, name=f"watch-{source['id']}").start()
    LOG.info("Datum Work monitor listening at http://%s:%s", args.host, args.port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        server.server_close()


if __name__ == "__main__":
    main()
