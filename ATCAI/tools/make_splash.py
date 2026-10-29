#!/usr/bin/env python3
"""Shrink the README banner into the splash image the Manager shows at startup.

Run it when the banner changes:

    python tools/make_splash.py

Why a build step rather than resizing at runtime: Tk can only shrink by dropping pixels
(`PhotoImage.subsample`), which at a 3x reduction throws away eight pixels in every nine
and leaves text visibly ragged. This averages each 3x3 block instead - a box filter,
which is a real resample - so the result is smooth. Doing it here also keeps the full
2 MB banner out of the exe; only the ~100 KB result is bundled.

Standard library only, deliberately. Pillow would do this in three lines, but it is not
installed on this machine and would be a dependency carried for one image. The banner is
8-bit RGB, non-interlaced PNG - the simplest case there is - so the arithmetic below is
all that is needed.
"""

from __future__ import annotations

import os
import struct
import sys
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SOURCE = os.path.join(ROOT, "assets", "ATCAI_Banner.png")
TARGET = os.path.join(ROOT, "assets", "ATCAI_Splash.png")

# Chosen against the 900x700 main window: 1086 is wider than the app itself and 543 reads
# as incidental. The banner is 3:1, so this is 2172x724 reduced by exactly 3.
FACTOR = 3


def read_png(path):
    """(width, height, rows) for an 8-bit RGB non-interlaced PNG.

    Raises rather than guessing on anything else: a silently mangled splash is worse
    than a build step that stops and says why.
    """
    with open(path, "rb") as handle:
        data = handle.read()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("%s is not a PNG" % path)

    width = height = None
    compressed = bytearray()
    offset = 8
    while offset < len(data):
        (length,) = struct.unpack(">I", data[offset:offset + 4])
        kind = data[offset + 4:offset + 8]
        body = data[offset + 8:offset + 8 + length]
        if kind == b"IHDR":
            width, height, depth, colour, _, _, interlace = struct.unpack(
                ">IIBBBBB", body)
            if (depth, colour, interlace) != (8, 2, 0):
                raise ValueError(
                    "expected 8-bit RGB non-interlaced; got depth=%d colour=%d "
                    "interlace=%d" % (depth, colour, interlace))
        elif kind == b"IDAT":
            compressed += body
        elif kind == b"IEND":
            break
        offset += 12 + length           # length + type + data + CRC

    if width is None:
        raise ValueError("no IHDR in %s" % path)

    raw = zlib.decompress(bytes(compressed))
    stride = width * 3
    rows = []
    previous = bytearray(stride)
    position = 0
    for _ in range(height):
        filter_type = raw[position]
        position += 1
        line = bytearray(raw[position:position + stride])
        position += stride
        _unfilter(filter_type, line, previous, 3)
        rows.append(line)
        previous = line
    return width, height, rows


def _unfilter(filter_type, line, previous, pixel_bytes):
    """Undo one scanline's PNG filter, in place. The five types are from the spec."""
    if filter_type == 0:                                        # None
        return
    if filter_type == 1:                                        # Sub
        for i in range(pixel_bytes, len(line)):
            line[i] = (line[i] + line[i - pixel_bytes]) & 0xFF
    elif filter_type == 2:                                      # Up
        for i in range(len(line)):
            line[i] = (line[i] + previous[i]) & 0xFF
    elif filter_type == 3:                                      # Average
        for i in range(len(line)):
            left = line[i - pixel_bytes] if i >= pixel_bytes else 0
            line[i] = (line[i] + ((left + previous[i]) >> 1)) & 0xFF
    elif filter_type == 4:                                      # Paeth
        for i in range(len(line)):
            left = line[i - pixel_bytes] if i >= pixel_bytes else 0
            up = previous[i]
            upper_left = previous[i - pixel_bytes] if i >= pixel_bytes else 0
            estimate = left + up - upper_left
            da, db, dc = (abs(estimate - left), abs(estimate - up),
                          abs(estimate - upper_left))
            if da <= db and da <= dc:
                nearest = left
            elif db <= dc:
                nearest = up
            else:
                nearest = upper_left
            line[i] = (line[i] + nearest) & 0xFF
    else:
        raise ValueError("unknown PNG filter type %d" % filter_type)


def box_shrink(width, height, rows, factor):
    """Average each factor x factor block. Blocks are clipped at the right and bottom
    edges, so a dimension that does not divide evenly still uses every pixel."""
    out_width = (width + factor - 1) // factor
    out_height = (height + factor - 1) // factor
    out = []
    for block_y in range(out_height):
        line = bytearray(out_width * 3)
        y0 = block_y * factor
        y1 = min(y0 + factor, height)
        for block_x in range(out_width):
            x0 = block_x * factor
            x1 = min(x0 + factor, width)
            red = green = blue = count = 0
            for y in range(y0, y1):
                source = rows[y]
                for x in range(x0, x1):
                    at = x * 3
                    red += source[at]
                    green += source[at + 1]
                    blue += source[at + 2]
                    count += 1
            at = block_x * 3
            line[at] = red // count
            line[at + 1] = green // count
            line[at + 2] = blue // count
        out.append(line)
    return out_width, out_height, out


def write_png(path, width, height, rows):
    """Write 8-bit RGB with every scanline unfiltered - simple, and the file is small
    enough that the extra compression a filter would buy does not matter."""
    raw = bytearray()
    for line in rows:
        raw.append(0)
        raw += line

    def chunk(kind, body):
        header = struct.pack(">I", len(body)) + kind
        return header + body + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)

    png = bytearray(b"\x89PNG\r\n\x1a\n")
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(bytes(raw), 9))
    png += chunk(b"IEND", b"")
    with open(path, "wb") as handle:
        handle.write(png)


def main():
    if not os.path.isfile(SOURCE):
        print("missing %s" % SOURCE, file=sys.stderr)
        return 1

    width, height, rows = read_png(SOURCE)
    out_width, out_height, out_rows = box_shrink(width, height, rows, FACTOR)
    write_png(TARGET, out_width, out_height, out_rows)

    print("%s  %dx%d  %.1f MB" % (os.path.basename(SOURCE), width, height,
                                  os.path.getsize(SOURCE) / 1048576.0))
    print("%s  %dx%d  %.0f KB" % (os.path.basename(TARGET), out_width, out_height,
                                  os.path.getsize(TARGET) / 1024.0))
    return 0


if __name__ == "__main__":
    sys.exit(main())
