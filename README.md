# The Image Certificate Maker

Making certificates for a large quantity of participants can be a tedious task for an event. This tool automates the process of creating certificates in bulk, saving time and effort.

## Usage
- Clone the repo, and `cd` into it.
- Run `init.sh` to initiate the environment. This installs `uv`, and installs `pillow` as the dependency, and activates the virtual environment.
```bash
chmod +x init.sh
./init.sh
```
- In the repo folder, add a `participants.csv` where the names are listed under the `name` column.
- Add `cert.jpg` or `cert.png` to the folder, depending on which format you want to use.
- Import the font of your liking into the folder, and specify the filename under `font_path = ""`
- Run the script using uv.

For JPEG, Run
```bash
uv run jpeg.py
```

For PNG, Run
```bash
uv run png.py
```

This generates a `certificates` folder.

PNG output uses the owned writer in `png_encoder.py` and adaptive row filters in `png_filters.c`. It preserves RGBA pixels, inherited ICC profiles and the previous compression settings, exporting small row batches to bound memory. Pillow remains required for decoding, fonts, text drawing and JPEG. This partially replaces Pillow's PNG encoding without removing its package.

Overlapping PNG certificate calls share one decoded template and draw on separate copies. File changes invalidate the shared template, and the last active call frees it. This avoids decoding the same file in every worker without retaining images between batches.

Source installs now require a C compiler and Python development headers to build the small filter extension with setuptools. Run `uv sync` before running either script. No external C libraries are needed by the extension, and no compiler is used at runtime. For example, Debian/Ubuntu source builds need `build-essential` and `python3-dev`. The extension uses the CPython C API and must be rebuilt for each Python ABI and platform. The kernel follows the [PNG filter specification](https://www.w3.org/TR/png-3/#9Filters); its independent predictor oracle is in `tests/test_png_filters.py`.

Run the regression checks with `uv run python -m unittest discover -s tests`.

**NOTE**: If your certificate does not have names right in the center, you might have to adjust the y offset in the script. Moreover, if the name is too long, you might have to modify font sizes as well.

Multithreading ensures that the process is faster.

Made by Aadit Agrawal, 2025
