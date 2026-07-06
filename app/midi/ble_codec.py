"""BLE-MIDI packet codec (Milestone 14) — pure logic, no Bluetooth imports.

BLE MIDI (Apple/MMA spec) frames MIDI inside GATT packets:
    header byte:    0x80 | (timestamp_ms >> 7 & 0x3F)
    per message:    timestamp byte 0x80 | (timestamp_ms & 0x7F),
                    then the MIDI status + data bytes.
Running status may omit the status byte (and optionally the timestamp) of
subsequent messages. Timestamps are 13-bit milliseconds and only matter for
inter-message jitter; we send our own clock and ignore received ones.

decode_packet() is deliberately forgiving: unknown/system-common messages
are skipped, sysex is ignored (not needed for this controller), realtime
bytes never disturb running status.
"""


def _data_length(status: int) -> int | None:
    """Number of data bytes for a status byte; None for sysex/unsupported."""
    if 0x80 <= status <= 0xBF:  # note off/on, poly pressure, control change
        return 2
    if 0xC0 <= status <= 0xDF:  # program change, channel pressure
        return 1
    if 0xE0 <= status <= 0xEF:  # pitch bend
        return 2
    return {0xF1: 1, 0xF2: 2, 0xF3: 1, 0xF6: 0}.get(status)


def encode_message(midi_bytes: bytes | list[int], timestamp_ms: int) -> bytes:
    """One MIDI message -> one BLE-MIDI packet (fits any 23-byte MTU)."""
    ts = timestamp_ms & 0x1FFF
    return bytes([0x80 | (ts >> 7), 0x80 | (ts & 0x7F), *midi_bytes])


def decode_packet(packet: bytes) -> list[list[int]]:
    """BLE-MIDI packet -> list of complete MIDI messages (status + data)."""
    messages: list[list[int]] = []
    if len(packet) < 2 or not packet[0] & 0x80:
        return messages
    i = 1  # skip header
    running: int | None = None
    while i < len(packet):
        byte = packet[i]
        if byte & 0x80:
            # Timestamp byte; a status byte may follow (or running status).
            i += 1
            if i >= len(packet):
                break
            if packet[i] & 0x80:
                status = packet[i]
                i += 1
                if 0xF8 <= status:  # realtime: standalone, keeps running status
                    messages.append([status])
                    continue
                if status == 0xF0 or _data_length(status) is None:
                    break  # sysex/unsupported: drop the rest of the packet
                running = status
                # fall through to read this message's data bytes
        if running is None:
            break
        length = _data_length(running)
        data = packet[i:i + length]
        if len(data) < length or any(b & 0x80 for b in data):
            break  # truncated or corrupt
        messages.append([running, *data])
        i += length
    return messages
