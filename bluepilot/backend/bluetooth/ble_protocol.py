#!/usr/bin/env python3
"""
BluePilot BLE Framing Protocol
Handles chunking, framing, sequence numbering, and message assembly for BLE GATT communication.
Compatible with Comma 4 (AGNOS/Linux BlueZ) and iOS CoreBluetooth / Flutter.
"""

import json
import struct
import logging
from typing import List, Dict, Any, Optional, Tuple, Callable

logger = logging.getLogger("bp_ble_protocol")

# Protocol Flags (Byte 0)
FLAG_START = 0x80      # Bit 7: 1 if first chunk of a message
FLAG_END = 0x40        # Bit 6: 1 if last chunk of a message
FLAG_SEQ_MASK = 0x3F   # Bits 0-5: Sequence number (0..63)

# Default Max Chunk Size (safe default for BLE MTU 23 is 20 payload bytes; for MTU 247+ it will be larger)
DEFAULT_MAX_CHUNK_SIZE = 180


class BLEMessageAssembler:
    """
    Assembles incoming BLE packet chunks into complete messages.
    Handles fragmentation across multiple GATT packets.
    """
    def __init__(self, on_message: Optional[Callable[[Dict[str, Any]], None]] = None):
        self.on_message = on_message
        self._buffer = bytearray()
        self._expected_length = 0
        self._is_receiving = False
        self._last_seq = -1

    def reset(self):
        self._buffer.clear()
        self._expected_length = 0
        self._is_receiving = False
        self._last_seq = -1

    def feed_chunk(self, data: bytes) -> Optional[Dict[str, Any]]:
        """
        Feed a raw BLE packet chunk into the assembler.
        Returns parsed JSON dict if a complete message was received, else None.
        """
        if not data or len(data) < 1:
            return None

        header = data[0]
        is_start = bool(header & FLAG_START)
        is_end = bool(header & FLAG_END)
        seq = header & FLAG_SEQ_MASK

        payload_offset = 1

        if is_start:
            self._buffer.clear()
            self._is_receiving = True
            self._last_seq = seq

            if len(data) >= 3:
                self._expected_length = struct.unpack(">H", data[1:3])[0]
                payload_offset = 3
            else:
                self._expected_length = 0
                payload_offset = 1

            self._buffer.extend(data[payload_offset:])
        else:
            if not self._is_receiving:
                logger.warning("Received continuation chunk without start flag, ignoring")
                return None

            expected_seq = (self._last_seq + 1) & FLAG_SEQ_MASK
            if seq != expected_seq:
                logger.warning(f"BLE packet sequence mismatch: expected {expected_seq}, got {seq}")
            self._last_seq = seq
            self._buffer.extend(data[payload_offset:])

        if is_end:
            self._is_receiving = False
            complete_bytes = bytes(self._buffer)
            self._buffer.clear()
            try:
                msg_str = complete_bytes.decode('utf-8')
                parsed = json.loads(msg_str)
                if self.on_message:
                    self.on_message(parsed)
                return parsed
            except Exception as e:
                logger.error(f"Failed to decode BLE message JSON ({len(complete_bytes)} bytes): {e}")
                return None

        return None


class BLEMessageChunker:
    """
    Fragments outgoing JSON messages into framed BLE packet chunks.
    """
    @staticmethod
    def chunk_message(message: Dict[str, Any], max_chunk_size: int = DEFAULT_MAX_CHUNK_SIZE) -> List[bytes]:
        """
        Serializes message to JSON and splits into framed BLE packets.
        """
        payload = json.dumps(message, separators=(',', ':')).encode('utf-8')
        total_len = len(payload)

        # Ensure max_chunk_size is reasonable
        max_chunk_size = max(20, max_chunk_size)

        chunks: List[bytes] = []

        if total_len == 0:
            header = FLAG_START | FLAG_END | 0
            chunks.append(struct.pack(">BH", header, 0))
            return chunks

        # First chunk
        seq = 0
        header = FLAG_START | (seq & FLAG_SEQ_MASK)
        max_first_data_len = max_chunk_size - 3  # 1 byte header + 2 bytes total_len

        if total_len <= max_first_data_len:
            # Entire message fits in a single chunk
            header |= FLAG_END
            first_chunk = struct.pack(">BH", header, total_len) + payload
            chunks.append(first_chunk)
            return chunks

        # Multi-chunk message
        first_data = payload[:max_first_data_len]
        first_chunk = struct.pack(">BH", header, total_len) + first_data
        chunks.append(first_chunk)

        offset = max_first_data_len
        max_cont_data_len = max_chunk_size - 1  # 1 byte header

        while offset < total_len:
            seq = (seq + 1) & FLAG_SEQ_MASK
            remaining = total_len - offset
            is_end = remaining <= max_cont_data_len
            chunk_data_len = min(remaining, max_cont_data_len)

            header = (seq & FLAG_SEQ_MASK)
            if is_end:
                header |= FLAG_END

            chunk = bytes([header]) + payload[offset:offset + chunk_data_len]
            chunks.append(chunk)
            offset += chunk_data_len

        return chunks
