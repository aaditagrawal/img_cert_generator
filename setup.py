"""Build the owned PNG filtering kernel; no external C libraries are linked."""

from setuptools import Extension, setup

setup(
    py_modules=["certificate_template", "png_encoder", "png", "jpeg"],
    ext_modules=[Extension("_png_filters", ["png_filters.c"])],
)
