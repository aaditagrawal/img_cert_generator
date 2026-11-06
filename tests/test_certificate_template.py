import concurrent.futures
import io
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from certificate_template import _TemplatePool


class TemplateSharingTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "template.png"
        Image.new("RGBA", (37, 23), "white").save(self.path, icc_profile=b"profile")
        self.pool = _TemplatePool()

    def test_overlapping_calls_share_decode_but_own_their_pixels(self):
        ready = threading.Barrier(16)

        def render(index):
            with self.pool.borrow(self.path) as image:
                self.assertEqual(image.getpixel((0, 0)), (255, 255, 255, 255))
                self.assertEqual(image.info["icc_profile"], b"profile")
                image.putpixel((0, 0), (index, 1, 2, 3))
                ready.wait(timeout=10)
                self.assertEqual(image.getpixel((0, 0)), (index, 1, 2, 3))

        with patch("certificate_template.Image.open", wraps=Image.open) as load:
            with concurrent.futures.ThreadPoolExecutor(max_workers=16) as executor:
                list(executor.map(render, range(16)))
            self.assertEqual(load.call_count, 1)
        self.assertEqual(self.pool.active, 0)
        self.assertIsNone(self.pool.image)
        self.assertIsNone(self.pool.key)

    def test_modified_and_missing_template_are_not_hidden_by_active_lease(self):
        with self.pool.borrow(self.path) as previous:
            Image.new("RGB", (43, 29), "black").save(self.path)
            with self.pool.borrow(self.path) as current:
                self.assertEqual(current.size, (43, 29))
                self.assertEqual(current.getpixel((0, 0)), (0, 0, 0, 255))
                self.assertEqual(previous.size, (37, 23))
                self.path.unlink()
                with self.assertRaises(FileNotFoundError), self.pool.borrow(self.path):
                    self.fail("missing template reused")
        self.assertIsNone(self.pool.image)

    def test_failure_releases_template_and_next_call_reopens_file(self):
        with self.assertRaisesRegex(RuntimeError, "render failed"), self.pool.borrow(self.path):
            raise RuntimeError("render failed")
        self.assertEqual(self.pool.active, 0)
        self.assertIsNone(self.pool.image)
        with patch("certificate_template.Image.open", wraps=Image.open) as load:
            with self.pool.borrow(self.path):
                pass
            with self.pool.borrow(self.path):
                pass
            self.assertEqual(load.call_count, 2)

    def test_file_like_template_keeps_original_support(self):
        with self.pool.borrow(io.BytesIO(self.path.read_bytes())) as image:
            self.assertEqual(image.size, (37, 23))
            self.assertEqual(image.info["icc_profile"], b"profile")
        self.assertIsNone(self.pool.image)
