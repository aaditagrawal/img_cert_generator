import contextlib
import io
import itertools
import random
import struct
import tempfile
import unittest
import zlib
from pathlib import Path
from unittest.mock import Mock, patch

from PIL import Image, ImageDraw, ImageFont, PngImagePlugin

import png
from png_encoder import save_rgba_png


class PngEncoderTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "output.png"

    def test_lossless_pixels_and_chunk_integrity(self):
        rng = random.Random(17)
        for width, height in [(1, 1), (1, 37), (1, 20000), (3, 20000), (73, 19), (20000, 2)]:
            with self.subTest(size=(width, height)):
                pixels = rng.randbytes(width * height * 4)
                save_rgba_png(self.path, width, height, pixels)
                with Image.open(self.path) as image:
                    image.verify()
                with Image.open(self.path) as image:
                    self.assertEqual(image.mode, "RGBA")
                    self.assertEqual(image.size, (width, height))
                    self.assertEqual(image.tobytes(), pixels)
                encoded = self.path.read_bytes()
                position = 8
                compressed = bytearray()
                kinds = []
                while position < len(encoded):
                    size = struct.unpack_from(">I", encoded, position)[0]
                    kind = encoded[position + 4 : position + 8]
                    data = encoded[position + 8 : position + 8 + size]
                    crc = struct.unpack_from(">I", encoded, position + 8 + size)[0]
                    self.assertEqual(crc, zlib.crc32(kind + data))
                    kinds.append(kind)
                    if kind == b"IDAT":
                        self.assertLessEqual(size, max(65536, width * 4))
                        compressed.extend(data)
                    position += size + 12
                self.assertEqual(position, len(encoded))
                self.assertEqual(kinds[0], b"IHDR")
                self.assertEqual(kinds[-1], b"IEND")
                self.assertEqual(set(kinds), {b"IHDR", b"IDAT", b"IEND"})
                scanlines = zlib.decompress(compressed)
                self.assertEqual(len(scanlines), height * (width * 4 + 1))
                self.assertTrue(all(kind in (0, 1, 2, 4) for kind in scanlines[::width * 4 + 1]))

    def test_wide_image_framing_does_not_increase_output_size(self):
        rng = random.Random(91)
        for width in [16384, 16385, 262144, 262145]:
            with self.subTest(width=width):
                pixels = rng.randbytes(width * 2 * 4)
                reference = io.BytesIO()
                Image.frombytes("RGBA", (width, 2), pixels).save(reference, format="PNG")
                save_rgba_png(self.path, width, 2, pixels)
                self.assertEqual(self.path.stat().st_size, len(reference.getvalue()))
                with Image.open(self.path) as output:
                    self.assertEqual(output.tobytes(), pixels)

    def test_inherited_metadata_matches_previous_save(self):
        source = Path(self.directory.name) / "source.png"
        text = PngImagePlugin.PngInfo()
        text.add_text("Comment", "certificate")
        text.add(b"gAMA", struct.pack(">I", 45455))
        text.add(b"sRGB", b"\0")
        exif = Image.Exif()
        exif[0x010E] = "participant"
        for profile in [None, b"profile bytes\0\xff" * 1000]:
            with self.subTest(profile=profile is not None):
                Image.new("RGBA", (7, 5), (10, 20, 30, 40)).save(
                    source, pnginfo=text, dpi=(300, 300), exif=exif,
                    icc_profile=profile,
                )
                with Image.open(source) as original:
                    image = original.convert("RGBA")
                reference = io.BytesIO()
                image.save(reference, format="PNG")
                save_rgba_png(
                    self.path, *image.size, image.tobytes(),
                    icc_profile=image.info.get("icc_profile"),
                )
                with (
                    Image.open(io.BytesIO(reference.getvalue())) as previous,
                    Image.open(self.path) as output,
                ):
                    self.assertEqual(output.info, previous.info)
                    self.assertEqual(output.tobytes(), previous.tobytes())

    def test_pixel_export_is_bounded_and_handles_batch_boundaries(self):
        width, height = 7, 10001
        pixels = random.Random(23).randbytes(width * height * 4)
        exports = []

        def export(first, last):
            exports.append((first, last))
            self.assertLessEqual((last - first) * (width * 4 + 1), 65536)
            return pixels[first * width * 4 : last * width * 4]

        save_rgba_png(self.path, width, height, export)
        self.assertEqual(exports[0][0], 0)
        self.assertEqual(exports[-1][1], height)
        self.assertGreater(len(exports), 1)
        for previous, current in itertools.pairwise(exports):
            self.assertEqual(previous[1], current[0])
        with Image.open(self.path) as image:
            self.assertEqual(image.tobytes(), pixels)

    def test_invalid_row_export_removes_partial_output(self):
        with self.assertRaises(ValueError):
            save_rgba_png(self.path, 2, 3, lambda first, last: b"1234")
        self.assertFalse(self.path.exists())

    def test_invalid_input_does_not_truncate_existing_output(self):
        self.path.write_bytes(b"existing certificate")
        for width, height, pixels in [
            (0, 1, b""), (-1, 1, b""), (1, 0, b""),
            (2**31, 1, b""), (1, 2**31, b""), (1, 1, b"123"),
            (1, 1, b"12345"),
        ]:
            with self.subTest(size=(width, height), length=len(pixels)):
                with self.assertRaises(ValueError):
                    save_rgba_png(self.path, width, height, pixels)
                self.assertEqual(self.path.read_bytes(), b"existing certificate")
        with self.assertRaises(TypeError):
            save_rgba_png(self.path, 1.0, 1, b"1234")
        self.assertEqual(self.path.read_bytes(), b"existing certificate")

    def test_io_errors_propagate_and_close_output(self):
        stream = io.BytesIO()
        with (
            patch("builtins.open", return_value=stream),
            patch.object(stream, "write", side_effect=OSError("disk full")),
            self.assertRaisesRegex(OSError, "disk full"),
        ):
            save_rgba_png(self.path, 1, 1, b"1234")
        self.assertTrue(stream.closed)
        with self.assertRaises(FileNotFoundError):
            save_rgba_png(self.path / "missing.png", 1, 1, b"1234")

    def test_failed_compression_removes_new_partial_output(self):
        compressor = Mock()
        compressor.compress.side_effect = OSError("encoding failed")
        with (
            patch("png_encoder.zlib.compressobj", return_value=compressor),
            self.assertRaisesRegex(OSError, "encoding failed"),
        ):
            save_rgba_png(self.path, 1, 1, b"1234")
        self.assertFalse(self.path.exists())

    def test_certificate_pixels_and_naming_match_previous_pipeline(self):
        font = ImageFont.load_default(size=28)
        for mode in ["RGBA", "RGB", "L", "P"]:
            with self.subTest(mode=mode):
                source = Path(self.directory.name) / "template.png"
                image = Image.new(mode, (420, 180))
                if mode == "P":
                    image.putpalette([20, 60, 90] * 256)
                else:
                    image.paste(80, (0, 0, 420, 180))
                image.save(source, transparency=0 if mode in ("L", "P") else None)
                with Image.open(source) as template:
                    expected = template.convert("RGBA")
                name = "Zoë, José & A\u0301".upper()
                draw = ImageDraw.Draw(expected)
                bbox = draw.textbbox((0, 0), name, font=font)
                x = (420 - (bbox[2] - bbox[0])) / 2
                y = (180 - (bbox[3] - bbox[1])) / 2 - 12
                draw.text((x, y), name, fill="black", font=font)
                # Source and oracle are ready; the live path must not save via Pillow.
                with (
                    patch("png.ImageFont.truetype", return_value=font) as load_font,
                    patch.object(Image.Image, "save", side_effect=AssertionError("Pillow encoder called")),
                    contextlib.redirect_stdout(io.StringIO()),
                ):
                    png.process_certificate(
                        {"name": "Zoë, José & A\u0301"}, 7, source,
                        "chosen.ttf", self.directory.name, 28, "black", -12,
                    )
                load_font.assert_called_once_with("chosen.ttf", 28)
                with Image.open(Path(self.directory.name) / "certificate_007.png") as output:
                    self.assertEqual(output.size, expected.size)
                    self.assertEqual(output.tobytes(), expected.tobytes())


if __name__ == "__main__":
    unittest.main()
