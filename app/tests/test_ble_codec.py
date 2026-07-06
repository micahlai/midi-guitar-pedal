"""Milestone 14: BLE-MIDI packet encode/decode."""

import unittest

from midi.ble_codec import decode_packet, encode_message


class EncodeTest(unittest.TestCase):
    def test_note_on(self):
        packet = encode_message([0x90, 60, 127], timestamp_ms=1000)
        # 1000 ms -> high 6 bits 0x07, low 7 bits 0x68.
        self.assertEqual(packet, bytes([0x80 | 0x07, 0x80 | 0x68, 0x90, 60, 127]))

    def test_timestamp_wraps_13_bits(self):
        packet = encode_message([0xC0, 5], timestamp_ms=8192 + 3)
        self.assertEqual(packet[0], 0x80)
        self.assertEqual(packet[1], 0x83)

    def test_round_trip(self):
        for msg in ([0x90, 60, 127], [0xB0, 21, 0], [0xC5, 9], [0xE0, 0, 64]):
            packet = encode_message(msg, 555)
            self.assertEqual(decode_packet(packet), [msg])


class DecodeTest(unittest.TestCase):
    def test_multiple_messages_with_timestamps(self):
        packet = bytes([0x87, 0xE8, 0x90, 60, 127, 0xE9, 0x80, 60, 0])
        self.assertEqual(decode_packet(packet),
                         [[0x90, 60, 127], [0x80, 60, 0]])

    def test_running_status_without_status_byte(self):
        # Second message: timestamp then data only (running status).
        packet = bytes([0x87, 0xE8, 0xB0, 21, 127, 0xE9, 22, 127])
        self.assertEqual(decode_packet(packet),
                         [[0xB0, 21, 127], [0xB0, 22, 127]])

    def test_running_status_data_only(self):
        # Data bytes immediately following a complete message.
        packet = bytes([0x87, 0xE8, 0xB0, 21, 127, 22, 0])
        self.assertEqual(decode_packet(packet),
                         [[0xB0, 21, 127], [0xB0, 22, 0]])

    def test_program_change_single_data_byte(self):
        packet = bytes([0x87, 0xE8, 0xC0, 42])
        self.assertEqual(decode_packet(packet), [[0xC0, 42]])

    def test_realtime_keeps_running_status(self):
        # Clock byte between two running-status CC messages.
        packet = bytes([0x87, 0xE8, 0xB0, 21, 127, 0xE9, 0xF8, 0xEA, 22, 64])
        self.assertEqual(decode_packet(packet),
                         [[0xB0, 21, 127], [0xF8], [0xB0, 22, 64]])

    def test_sysex_dropped(self):
        packet = bytes([0x87, 0xE8, 0xF0, 1, 2, 3, 0xF7])
        self.assertEqual(decode_packet(packet), [])

    def test_garbage_and_truncation(self):
        self.assertEqual(decode_packet(b""), [])
        self.assertEqual(decode_packet(bytes([0x12, 0x34])), [])  # no header bit
        self.assertEqual(decode_packet(bytes([0x87, 0xE8, 0x90, 60])), [])  # short
        self.assertEqual(decode_packet(bytes([0x87, 0xE8])), [])  # ts only
        # Data before any status byte.
        self.assertEqual(decode_packet(bytes([0x87, 10, 20])), [])


if __name__ == "__main__":
    unittest.main()
