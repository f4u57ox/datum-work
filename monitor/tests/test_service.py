import json
from pathlib import Path
import socket
import sys
import threading
import unittest
from unittest.mock import patch
from urllib.request import urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from service import (MonitorState, ThreadingHTTPServer, coinbase_height, make_handler,
                     normalize_notify, normalize_template, public_url, sources_from_env,
                     subscription_messages, watch_stratum, watch_templates)


def source(algorithm="blake2b"):
    return {"id": "test", "name": "Test Pool", "url": "stratum+tcp://localhost:3333",
            "kind": "stratum", "powAlgorithm": algorithm}


class NormalizationTests(unittest.TestCase):
    def test_nine_field_blake2b_job_is_not_a_bitcoin_coinbase(self):
        message = {"method": "mining.notify", "params": ["job-a", "ab" * 32, "cd" * 39,
                   "", [], "20000000", "1903c2d4", "000000008252a06a", True]}
        event = normalize_notify(message, source())
        self.assertEqual(event["format"], "sia-stratum")
        self.assertEqual(event["workCommitment"], "cd" * 39)
        self.assertEqual(event["ntime"], "000000008252a06a")
        self.assertEqual(event["raw"], message)
        for field in ("height", "coinbase1", "coinbase2", "previousBlockHash", "transactionCount", "merkleBranches"):
            self.assertNotIn(field, event)

    def test_short_sia_job_preserves_opaque_parameters(self):
        message = {"method": "mining.notify", "params": ["job-b", "ab" * 32, "cd" * 39, True]}
        event = normalize_notify(message, source())
        self.assertEqual(event["format"], "sia-stratum")
        self.assertEqual(event["workFields"], message["params"][1:])
        self.assertNotIn("height", event)

    def test_bitcoin_height_and_parent_order(self):
        height = 969923
        coinbase1 = "0100000001" + "00" * 32 + "ffffffff" + "1003" + height.to_bytes(3, "little").hex()
        previous = "".join(f"{value:08x}" for value in range(8))
        message = {"method": "mining.notify", "params": ["btc", previous, coinbase1,
                   "00", ["ef" * 32], "20000000", "1701ffff", "6aa05200", True]}
        event = normalize_notify(message, source("sha256d"))
        self.assertEqual(event["height"], height)
        self.assertEqual(event["previousBlockHash"], "".join(f"{value:08x}" for value in reversed(range(8))))
        self.assertEqual(event["format"], "bitcoin-stratum-v1")
        self.assertNotIn("transactionCount", event)  # Merkle branches do not reveal the tx count.

    def test_bad_or_non_coinbase_height_is_omitted(self):
        for value in ("", "abcd", "zz", "0100000001" + "aa" * 32 + "ffffffff0403010203"):
            self.assertIsNone(coinbase_height(value))

    def test_own_gateway_and_index_formats_preserve_full_fields(self):
        for timestamp_key in ("createdAtMs", "acceptedAtUnixMs"):
            row = {"jobId": "own", timestamp_key: 1788891542476, "height": 969923,
                   "jobSequence": 4751, "previousBlockHash": "aa" * 32, "coinbase1": "0100",
                   "coinbase2": "00", "merkleBranches": ["bb" * 32], "nbits": 419676884,
                   "ntime": 1788891542, "blake2bCommitment": "cc" * 32, "template": "public-template"}
            event = normalize_template(row, source())
            self.assertEqual(event["format"], "datum-template")
            self.assertEqual(event["height"], 969923)
            self.assertEqual(event["raw"], row)
            self.assertEqual(event["publishedAt"], "2026-09-08T18:19:02.476Z")
            self.assertEqual(event["solanaTemplate"], "public-template")

    def test_own_header_transaction_count_includes_coinbase(self):
        event = normalize_template({"jobId": "own", "headerTransactionCount": 17}, source())
        self.assertEqual(event["transactionCount"], 17)
        event = normalize_template({"jobId": "own", "headerTransactionCount": 17, "transactionCount": 18}, source())
        self.assertEqual(event["transactionCount"], 18)
        for unavailable in (0, None, False):
            event = normalize_template({"jobId": "own", "headerTransactionCount": unavailable}, source())
            self.assertNotIn("transactionCount", event)


class StateAndConfigTests(unittest.TestCase):
    def test_invalid_template_rows_do_not_mark_source_live(self):
        config = {**source(), "kind": "http"}
        state = MonitorState([config])
        stop = threading.Event()
        def fetch(_url):
            stop.set()
            return [{}]
        with patch("service.fetch_template_feed", side_effect=fetch):
            watch_templates(config, state, stop, interval=0)
        self.assertEqual(state.snapshot()["sources"][0]["status"], "awaiting-work")

    def test_template_without_publication_time_has_unverified_freshness(self):
        config = {**source(), "kind": "http"}
        state = MonitorState([config])
        state.add(normalize_template({"jobId": "legacy"}, config))
        self.assertEqual(state.snapshot()["sources"][0]["status"], "stale")

    def test_old_source_template_does_not_become_live_on_fresh_http_receipt(self):
        config = {**source(), "kind": "http"}
        state = MonitorState([config])
        event = normalize_template({"jobId": "old", "createdAtMs": 1000}, config)
        state.add(event)
        self.assertEqual(state.snapshot()["sources"][0]["status"], "stale")

    def test_quiet_remote_becomes_stale(self):
        state = MonitorState([source()])
        event = normalize_notify({"method": "mining.notify", "params": ["old", "aa", "bb", True]}, source(), "2000-01-01T00:00:00.000Z")
        state.add(event)
        self.assertEqual(state.snapshot()["sources"][0]["status"], "stale")

    def test_explicit_inactive_or_stale_template_is_not_live(self):
        for flags in ({"active": False}, {"stale": True}):
            state = MonitorState([source()])
            state.add(normalize_template({"jobId": "inactive", **flags}, source()))
            self.assertEqual(state.snapshot()["sources"][0]["status"], "stale")

    def test_deduplicate_bound_and_refresh_publication(self):
        state = MonitorState([source()], max_events=2)
        for number in range(3):
            state.add(normalize_template({"jobId": str(number), "jobSequence": number}, source()))
        latest = state.snapshot()["sources"][0]["latest"]
        updated = normalize_template({"jobId": "2", "jobSequence": 2, "publicationState": "materialized"}, source())
        self.assertFalse(state.add(updated))
        snapshot = state.snapshot()
        self.assertEqual(len(snapshot["events"]), 2)
        self.assertEqual(snapshot["events"][0]["jobId"], "2")
        self.assertEqual(snapshot["sources"][0]["latest"]["receivedAt"], latest["receivedAt"])
        self.assertEqual(snapshot["sources"][0]["latest"]["publicationState"], "materialized")

    def test_defaults_and_explicit_pyblock_algorithm_override(self):
        sources = sources_from_env({})
        pyblock = next(item for item in sources if item["id"] == "pyblock")
        self.assertEqual(pyblock["powAlgorithm"], "blake2b")
        self.assertEqual(pyblock["url"], "stratum+tcp://b.pyblock.xyz:23115")
        overridden = sources_from_env({"PYBLOCK_STRATUM_URL": "stratum+tcp://pool.pyblock.xyz:23334", "PYBLOCK_POW_ALGORITHM": "sha256d"})
        self.assertEqual(overridden[1]["powAlgorithm"], "sha256d")
        self.assertEqual(overridden[1]["url"], "stratum+tcp://pool.pyblock.xyz:23334")
        self.assertEqual(overridden[1]["name"], "PyBlock SHA-256")
        own = next(item for item in sources_from_env({"DATUM_MONITOR_OWN_URL": "http://private/templates"}) if item["id"] == "own")
        self.assertEqual(own["fallbackUrls"], [])

    def test_never_submits_and_authorization_is_opt_in(self):
        self.assertEqual([item["method"] for item in subscription_messages()], ["mining.subscribe"])
        messages = subscription_messages("observer:x")
        self.assertEqual([item["method"] for item in messages], ["mining.subscribe", "mining.authorize"])
        self.assertEqual(messages[1]["params"], ["observer", "x"])

    def test_public_urls_omit_credentials_and_query(self):
        self.assertEqual(public_url("http://user:secret@localhost:8810/templates?token=secret"), "http://localhost:8810/templates")

    def test_invalid_source_port_does_not_crash_the_other_sources(self):
        config = {**source(), "url": "stratum+tcp://localhost:invalid"}
        state = MonitorState([config])
        watch_stratum(config, state, threading.Event())
        self.assertEqual(state.snapshot()["sources"][0]["status"], "error")


class NetworkTests(unittest.TestCase):
    def test_subscribe_only_fake_pool_and_snapshot(self):
        stop = threading.Event()
        pool = socket.socket()
        pool.bind(("127.0.0.1", 0))
        pool.listen(1)
        pool.settimeout(3)
        config = source()
        config["url"] = f"stratum+tcp://127.0.0.1:{pool.getsockname()[1]}"
        state = MonitorState([config])
        worker = threading.Thread(target=watch_stratum, args=(config, state, stop), daemon=True)
        worker.start()
        server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(state))
        web = threading.Thread(target=server.serve_forever, daemon=True)
        web.start()
        try:
            connection, _ = pool.accept()
            with connection:
                connection.settimeout(3)
                request = connection.recv(4096)
                self.assertEqual(json.loads(request)["method"], "mining.subscribe")
                message = {"method": "mining.notify", "params": ["network-job", "ab" * 32, "cd" * 39, True]}
                connection.sendall((json.dumps(message) + "\n").encode())
                for _ in range(100):
                    if state.snapshot()["events"]:
                        break
                    stop.wait(0.01)
                url = f"http://127.0.0.1:{server.server_port}"
                with urlopen(url + "/api/snapshot", timeout=3) as response:
                    snapshot = json.load(response)
                self.assertEqual(snapshot["events"][0]["jobId"], "network-job")
                self.assertEqual(snapshot["sources"][0]["status"], "live")
                with urlopen(url + "/health", timeout=3) as response:
                    self.assertEqual(json.load(response)["status"], "ok")
                connection.settimeout(0.05)
                with self.assertRaises(socket.timeout):
                    connection.recv(4096)  # No authorize, submit, or miner traffic follows.
        finally:
            stop.set()
            server.shutdown()
            server.server_close()
            pool.close()
            worker.join(timeout=3)


if __name__ == "__main__":
    unittest.main()
