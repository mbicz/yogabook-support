#!/usr/bin/env python3
"""Repair Yoga Book temperature methods; requires native CHT WC thermal support.

Apply to the camera-corrected revision-6 DSDT and stock revision-3 DptfTab
SSDT. Each output retains its exact length, all enclosing AML package lengths,
method flags, trip points and unrelated bytes. Only the three known _TMP
bodies, OEM revision and checksum change. Unknown firmware is rejected.

The original methods gate ADC reads on an absent virtual-GPIO provider and
return 0 K (STR0/STR2) or a dummy 0 C (TZ00). The native PMIC thermal opregion
performs the conversion itself; these methods must read it directly.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
import struct
import sys

TABLES = {
    (b"DSDT", b"EDK2"): (6, 7, [
        (b"TZ00", b"\x5b\x85", b"TMP2", "6bfcdc624de9604cbd7e2fc7d73ce3d9d0bb3aac5932c1df12565fb5c70da012"),
    ]),
    (b"SSDT", b"DptfTab"): (3, 4, [
        (b"STR0", b"\x5b\x82", b"TMP0", "c054eb8d9ce81d1d5b3b759ad4804bbb321c9507b487d413d28170708d13db9a"),
        (b"STR2", b"\x5b\x82", b"TMP2", "4636b8b923936b21f397fdb7d25f91a4e0321d82a68160846e763bf4194b9b06"),
    ]),
}

TABLE_HASHES = {
    (b"DSDT", 6): "0d1a87d41d0064fd1dba88c81c126d5f8aa22621b55102709e183bf384fec065",
    (b"DSDT", 7): "4ea630083c22f4ca85667f5ef522613f7e62d9c1dbc8074c58b7f8d23b86f114",
    (b"SSDT", 3): "da86013f0e413cf4b6494b69abc3ef782a20ded7315eb42c06b2a102549bc8ce",
    (b"SSDT", 4): "434d733be62e5669ed5f2b92215bc84af670483ccde3ae45be46aad198be9246",
}


def package(data: bytes, offset: int) -> tuple[int, int]:
    if offset >= len(data):
        raise ValueError("truncated AML package")
    follow = data[offset] >> 6
    width = follow + 1
    if offset + width > len(data):
        raise ValueError("truncated AML package length")
    size = data[offset] & (0x0f if follow else 0x3f)
    for index in range(follow):
        size |= data[offset + 1 + index] << (4 + 8 * index)
    return width, size


def named_object(data: bytes, name: bytes, opcode: bytes, start: int, end: int) -> tuple[int, int]:
    matches = []
    for position in range(start, end - len(opcode)):
        if not data.startswith(opcode, position):
            continue
        pkg = position + len(opcode)
        width, size = package(data, pkg)
        offset = pkg + width
        if data[offset:offset + 4] == name and offset + 4 <= pkg + size <= end:
            matches.append((offset + 4, pkg + size))
    if len(matches) != 1:
        raise ValueError(f"{name!r}: expected one AML object, found {len(matches)}")
    return matches[0]


def patch(data: bytes) -> bytes:
    if len(data) < 36 or struct.unpack_from("<I", data, 4)[0] != len(data) or sum(data) & 0xff:
        raise ValueError("invalid ACPI table length/checksum")
    identity = (data[:4], data[16:24].rstrip(b" \x00"))
    if data[10:16].rstrip(b" ") != b"INTEL" or identity not in TABLES:
        raise ValueError("not a supported Yoga Book thermal table")
    original, updated, methods = TABLES[identity]
    revision = struct.unpack_from("<I", data, 24)[0]
    if revision not in (original, updated):
        raise ValueError(f"unexpected OEM revision {revision}")
    if hashlib.sha256(data).hexdigest() != TABLE_HASHES[(data[:4], revision)]:
        raise ValueError("unknown firmware table contents; refusing thermal patch")
    output = bytearray(data)
    for name, opcode, channel, digest in methods:
        start, end = named_object(data, name, opcode, 36, len(data))
        flags, finish = named_object(data, b"_TMP", b"\x14", start, end)
        if data[flags] != 0x08:
            raise ValueError(f"{name!r}: unexpected method arguments/serialization")
        body = flags + 1
        # Return (\\_SB.PCI0.I2C7.PMI5.TMPn), followed by AML Noop padding.
        replacement = b"\xa4\x5c\x2f\x05_SB_PCI0I2C7PMI5" + channel
        if len(replacement) > finish - body:
            raise ValueError("replacement does not fit the original method")
        replacement += b"\xa3" * (finish - body - len(replacement))
        if revision == original:
            if hashlib.sha256(data[body:finish]).hexdigest() != digest:
                raise ValueError(f"{name!r}: unknown original _TMP body; refusing firmware patch")
        elif data[body:finish] != replacement:
            raise ValueError(f"{name!r}: inconsistent already-patched table")
        output[body:finish] = replacement
    struct.pack_into("<I", output, 24, updated)
    output[9] = 0
    output[9] = (-sum(output)) & 0xff
    return bytes(output)


def main():
    if len(sys.argv) != 3:
        raise SystemExit(f"usage: {sys.argv[0]} <input-table.aml> <output-table.aml>")
    source, destination = map(Path, sys.argv[1:])
    try:
        output = patch(source.read_bytes())
    except ValueError as error:
        raise SystemExit(str(error)) from error
    destination.write_bytes(output)
    print(f"{output[:4].decode()} thermal correction: {len(output)} bytes -> {destination}")


if __name__ == "__main__":
    main()
