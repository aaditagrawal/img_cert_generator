"""Encode rendered RGBA8 certificates without a third-party PNG encoder.

Only encoding lives here. Template decoding and text rendering still use Pillow.
The output follows https://www.w3.org/TR/png-3/ and uses unfiltered scanlines.
"""

import os
import struct
import zlib
from collections.abc import Callable
from typing import BinaryIO


def _write_chunk(stream: BinaryIO, kind: bytes, data: bytes | memoryview) -> None:
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
    # Level 1 trades larger lossless files for lower measured encoding costs.
    compressor = zlib.compressobj(level=1)
    rows_per_batch = max(1, 65536 // (stride + 1))
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
                row_count = last_row - first_row
                block = (
                    pixels[first_row * stride : last_row * stride]
                    if isinstance(pixels, bytes) else pixels(first_row, last_row)
                )
                if len(block) != row_count * stride:
                    raise ValueError("Expected exactly width * row_count * 4 RGBA bytes")
                data = memoryview(block)
                if stride < row_count:
                    # Scatter columns in bulk to avoid a Python call per narrow row.
                    filtered = bytearray(row_count * (stride + 1))
                    for column in range(stride):
                        filtered[column + 1 :: stride + 1] = block[column::stride]
                else:
                    filtered = b"".join(
                        b"\0" + data[y * stride : (y + 1) * stride].tobytes()
                        for y in range(row_count)
                    )
                compressed = compressor.compress(filtered)
                if first_row + rows_per_batch >= height:
                    compressed += compressor.flush()
                for offset in range(0, len(compressed), 65536):
                    _write_chunk(stream, b"IDAT", compressed[offset : offset + 65536])
            _write_chunk(stream, b"IEND", b"")
    except BaseException:
        # Match the previous save path: remove a newly created partial output.
        if created:
            try:
                os.unlink(path)
            except OSError:
                pass
        raise
