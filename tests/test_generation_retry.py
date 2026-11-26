"""Transient upstream failures must not surface as 「服务未返回可用候选」."""
import sys
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import generate


class _Response:
    def __init__(self, status, body=b"{}", headers=None):
        self.status = status
        self.reason = "simulated"
        self.headers = headers or {}
        self.will_close = False
        self._body = body

    def read(self):
        return self._body


class _Conn:
    def __init__(self, responses):
        self._responses = list(responses)
        self.requests = 0

    def request(self, *args, **kwargs):
        self.requests += 1

    def getresponse(self):
        return self._responses.pop(0)

    def close(self):
        pass


class RetryBackoffTests(unittest.TestCase):
    def test_retry_after_header_wins(self):
        self.assertEqual(generate._retry_delay({"Retry-After": "3"}, 2), 3.0)

    def test_backoff_is_bounded(self):
        with patch.object(generate.random, "uniform", return_value=0):
            self.assertEqual(generate._retry_delay(None, 9), 4.0)


class PostJsonRetryTests(unittest.TestCase):
    def _pool_with(self, responses):
        pool = generate._KeepAlivePool()
        conn = _Conn(responses)
        with patch.object(pool, "_checkout", return_value=("key", conn)), \
             patch.object(generate.time, "sleep"):
            yield pool, conn

    def test_rate_limit_then_success(self):
        for pool, conn in self._pool_with([
                _Response(429), _Response(200, b'{"ok": true}')]):
            self.assertEqual(pool.post_json("https://x/v1", {}, {}, 1), {"ok": True})
        self.assertEqual(conn.requests, 2)

    def test_rate_limit_exhausts_retries(self):
        for pool, conn in self._pool_with([_Response(429)] * generate._MAX_ATTEMPTS):
            with self.assertRaises(urllib.error.HTTPError) as caught:
                pool.post_json("https://x/v1", {}, {}, 1)
        self.assertEqual(caught.exception.code, 429)
        self.assertEqual(conn.requests, generate._MAX_ATTEMPTS)

    def test_bad_request_is_not_retried(self):
        for pool, conn in self._pool_with([_Response(400), _Response(200)]):
            with self.assertRaises(urllib.error.HTTPError) as caught:
                pool.post_json("https://x/v1", {}, {}, 1)
        self.assertEqual(caught.exception.code, 400)
        self.assertEqual(conn.requests, 1)


class ErrorCopyTests(unittest.TestCase):
    def test_rate_limit_names_the_real_cause(self):
        generator = generate.Generator()
        err = urllib.error.HTTPError("url", 429, "Too Many Requests", {}, None)
        with patch.object(generator, "_call", side_effect=err):
            texts, error = generator._one_tone("hi", "闲聊", "高情商话术")
        self.assertEqual(texts, [])
        self.assertIn("限流 429", error)


if __name__ == "__main__":
    unittest.main()
