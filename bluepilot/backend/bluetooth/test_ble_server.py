#!/usr/bin/env python3
"""
Unit test and loopback verification for BluePilot BLE Protocol & Backend Service
"""

import os
import json
import unittest
import tempfile
import shutil
from ble_protocol import BLEMessageAssembler, BLEMessageChunker
from bp_ble_service import BluePilotBLEHandler, FallbackParams


class TestBLEProtocol(unittest.TestCase):
    def test_single_chunk_roundtrip(self):
        assembler = BLEMessageAssembler()
        msg = {"id": "req-1", "op": "ping", "time": 123456}

        chunks = BLEMessageChunker.chunk_message(msg, max_chunk_size=180)
        self.assertEqual(len(chunks), 1)

        result = assembler.feed_chunk(chunks[0])
        self.assertIsNotNone(result)
        self.assertEqual(result["id"], "req-1")
        self.assertEqual(result["op"], "ping")

    def test_multi_chunk_fragmentation(self):
        assembler = BLEMessageAssembler()
        # Large payload with 50 parameters
        params = {f"Param_{i}": {"value": i % 2 == 0, "type": "bool", "flags": ["PERSISTENT"]} for i in range(50)}
        msg = {"id": "req-large", "op": "get_all_params", "data": params}

        # Small chunk size (25 bytes) to force heavy fragmentation
        chunks = BLEMessageChunker.chunk_message(msg, max_chunk_size=25)
        self.assertGreater(len(chunks), 10)

        assembled = None
        for i, chunk in enumerate(chunks):
            res = assembler.feed_chunk(chunk)
            if i == len(chunks) - 1:
                assembled = res
            else:
                self.assertIsNone(res)

        self.assertIsNotNone(assembled)
        self.assertEqual(assembled["id"], "req-large")
        self.assertEqual(len(assembled["data"]), 50)
        self.assertEqual(assembled["data"]["Param_0"]["value"], True)

    def test_handler_operations(self):
        tmp_dir = tempfile.mkdtemp()
        try:
            params = FallbackParams(p_dir=tmp_dir)
            handler = BluePilotBLEHandler(params=params)

            # Test ping
            res = handler.handle_request({"id": "1", "op": "ping"})
            self.assertTrue(res["success"])
            self.assertIn("pong", res["data"])

            # Test set_param
            set_res = handler.handle_request({"id": "2", "op": "set_param", "key": "Mads", "value": True})
            self.assertTrue(set_res["success"])
            self.assertEqual(params.get_bool("Mads"), True)

            # Test get_param
            get_res = handler.handle_request({"id": "3", "op": "get_param", "key": "Mads"})
            self.assertTrue(get_res["success"])
            self.assertEqual(get_res["data"]["value"], True)

            # Test get_status
            status_res = handler.handle_request({"id": "4", "op": "get_status"})
            self.assertTrue(status_res["success"])
            self.assertEqual(status_res["data"]["device"], "comma four")

        finally:
            shutil.rmtree(tmp_dir)


if __name__ == "__main__":
    unittest.main()
