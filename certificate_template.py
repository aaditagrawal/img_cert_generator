"""Share one decoded template during overlapping certificate calls only."""

import os
import threading
from collections.abc import Generator
from contextlib import contextmanager

from PIL import Image


class _TemplatePool:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.key: tuple | None = None
        self.image: Image.Image | None = None
        self.active = 0

    def clear_if_idle(self) -> None:
        if self.active == 0 and self.image is not None:
            self.image.close()
            self.image = None
            self.key = None

    @contextmanager
    def borrow(self, path) -> Generator[Image.Image, None, None]:
        # File-like templates keep Image.open's existing behavior and ownership.
        if not isinstance(path, (str, bytes, os.PathLike)):
            with Image.open(path) as source:
                image = source.convert("RGBA")
            try:
                yield image
            finally:
                image.close()
            return

        with self.lock:
            stat = os.stat(path)
            key = (os.path.abspath(path), stat.st_dev, stat.st_ino, stat.st_size,
                   stat.st_mtime_ns, stat.st_ctime_ns)
            if key != self.key:
                with Image.open(path) as source:
                    decoded = source.convert("RGBA")
                # Copies already handed out own their pixels and metadata.
                if self.image is not None:
                    self.image.close()
                self.image, self.key = decoded, key
            assert self.image is not None
            try:
                image = self.image.copy()
            except BaseException:
                self.clear_if_idle()
                raise
            self.active += 1
        try:
            yield image
        finally:
            image.close()
            with self.lock:
                self.active -= 1
                self.clear_if_idle()


rgba_template = _TemplatePool().borrow
