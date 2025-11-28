import os
import time
import unittest

from engine.idempotency import DB_PATH, IdempotencyCache


class TestIdempotencyPersistence(unittest.TestCase):
    def setUp(self):
        # Clean up DB before test
        if DB_PATH.exists():
            os.remove(DB_PATH)

    def tearDown(self):
        # Clean up DB after test
        if DB_PATH.exists():
            os.remove(DB_PATH)

    def test_persistence(self):
        # 1. Create cache and set a value
        cache1 = IdempotencyCache(ttl_seconds=10)
        key = "test_key"
        data = {"status": "processed"}
        cache1.set(key, data)

        # 2. Verify it's there
        self.assertEqual(cache1.get(key), data)

        # 3. Simulate restart by creating a new instance
        cache2 = IdempotencyCache(ttl_seconds=10)

        # 4. Verify data persists
        self.assertEqual(cache2.get(key), data)

    def test_ttl_expiration(self):
        cache = IdempotencyCache(ttl_seconds=1)
        key = "expired_key"
        data = {"status": "old"}
        cache.set(key, data)

        # Wait for expiration
        time.sleep(1.1)

        # Verify it's gone (get checks TTL)
        self.assertIsNone(cache.get(key))


if __name__ == "__main__":
    unittest.main()
