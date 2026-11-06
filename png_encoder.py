"""Encode rendered RGBA8 certificates without a third-party PNG encoder.

Only encoding lives here. Template decoding and text rendering still use Pillow.
The output follows https://www.w3.org/TR/png-3/. An owned C kernel selects
adaptive row filters; the standard library handles chunks, CRCs and deflate.
"""

import os
import struct
import zlib
from collections.abc import Callable
from typing import BinaryIO

from _png_filters import filter_rows


def _write_chunk(stream: BinaryIO, kind: bytes, data: bytes | bytearray | memoryview) -> None:
    stream.write(struct.pack(">I", len(data)))
    stream.write(kind)
    stream.write(data)
    stream.write(struct.pack(">I", zlib.crc32(data, zlib.crc32(kind))))


def save_rgba_png(
    path: str | os.PathLike[str],
    width: int,
    height: int,
    pixels: bytes | Callable[[int, int], bytes],
    *,
    icc_profile: bytes | None = None,
) -> None:
    """Save packed, row-major RGBA bytes as a non-interlaced 8-bit PNG.

    Preserve an inherited ICC profile, as the previous PNG save path did.
    Other template metadata was not automatically saved by that path.
    Invalid dimensions and packed buffers fail before opening the output file.
    A callback can export rows [first, last) on demand to bound pixel memory.
    """
    if not isinstance(width, int) or not isinstance(height, int):
        raise TypeError("PNG dimensions must be integers")
    if not (0 < width <= 0x7FFFFFFF and 0 < height <= 0x7FFFFFFF):
        raise ValueError("PNG dimensions must be between 1 and 2**31 - 1")
    if isinstance(pixels, bytes) and len(pixels) != width * height * 4:
        raise ValueError("Expected exactly width * height * 4 RGBA bytes")

    profile = b"ICC Profile\0\0" + zlib.compress(icc_profile) if icc_profile else None
    if profile is not None and len(profile) > 0x7FFFFFFF:
        raise ValueError("ICC profile exceeds PNG chunk size limit")

    stride = width * 4
    # Match the original encoder's output buffer, including very wide rows.
    # Smaller chunks would add framing bytes without changing compressed data.
    idat_size = min(0x7FFFFFFF, max(65536, stride))
    # Keep the previous PNG compression policy instead of trading size for speed.
    compressor = zlib.compressobj(level=-1, memLevel=9, strategy=zlib.Z_FILTERED)
    rows_per_export = max(1, 65536 // (stride + 1))
    # Export small crops, but amortize GIL handoffs over larger codec batches.
    # Working buffers depend on this limit and row width, never image height.
    exports_per_batch = max(1, 1048576 // (rows_per_export * (stride + 1)))
    rows_per_batch = rows_per_export * exports_per_batch
    previous = bytes(stride)
    pending = bytearray()
    created = not os.path.exists(path)
    try:
        with open(path, "wb") as stream:
            stream.write(b"\x89PNG\r\n\x1a\n")
            _write_chunk(stream, b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
            if profile is not None:
                _write_chunk(stream, b"iCCP", profile)

            # Batch small rows; bound both filtering buffers and IDAT chunks.
            for first_row in range(0, height, rows_per_batch):
                last_row = min(first_row + rows_per_batch, height)
                if isinstance(pixels, bytes):
                    block = pixels[first_row * stride : last_row * stride]
                else:
                    exports = []
                    for first in range(first_row, last_row, rows_per_export):
                        last = min(first + rows_per_export, last_row)
                        part = pixels(first, last)
                        if len(part) != (last - first) * stride:
                            raise ValueError("Expected exactly width * row_count * 4 RGBA bytes")
                        exports.append(part)
                    block = b"".join(exports)
                    exports.clear()
                filtered = filter_rows(block, previous, stride)
                previous = block[-stride:]
                compressed = compressor.compress(filtered)
                if first_row + rows_per_batch >= height:
                    compressed += compressor.flush()
                pending.extend(compressed)
                complete = len(pending) // idat_size * idat_size
                for offset in range(0, complete, idat_size):
                    _write_chunk(stream, b"IDAT", memoryview(pending)[offset:offset + idat_size])
                del pending[:complete]
            if pending:
                _write_chunk(stream, b"IDAT", pending)
            _write_chunk(stream, b"IEND", b"")
    except BaseException:
        # Match the previous save path: remove a newly created partial output.
        if created:
            try:
                os.unlink(path)
            except OSError:
                pass
        raise
