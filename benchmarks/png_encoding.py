"""Compare the committed Pillow path with the owned encoder, including file I/O.

uv run python benchmarks/png_encoding.py --template /path/cert.png --font /path/font.ttf
"""

import argparse
import concurrent.futures
import contextlib
import importlib.util
import io
import json
import os
import platform
import random
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from PIL import Image
from PIL import __version__ as pillow_version

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import png
from png_encoder import save_rgba_png

BASE = "1559e1cc3f3427aa8b6823566704986703b39b24"


def measure(operations, samples, warmups, iterations=1):
    timings = {name: [] for name in operations}
    cpu_timings = {name: [] for name in operations}
    for repeat in range(samples + warmups):
        order = list(operations) if repeat % 2 else list(reversed(operations))
        for name in order:
            start = time.perf_counter_ns()
            cpu_start = time.process_time_ns()
            for _ in range(iterations):
                operations[name]()
            elapsed = (time.perf_counter_ns() - start) / 1_000_000 / iterations
            cpu_elapsed = (time.process_time_ns() - cpu_start) / 1_000_000 / iterations
            if repeat >= warmups:
                timings[name].append(elapsed)
                cpu_timings[name].append(cpu_elapsed)
    return {
        name: {
            "median_ms": statistics.median(values),
            "min_ms": min(values), "max_ms": max(values), "samples_ms": values,
            "cpu_median_ms": statistics.median(cpu_timings[name]),
            "cpu_samples_ms": cpu_timings[name], "iterations_per_sample": iterations,
        }
        for name, values in timings.items()
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--template", required=True, type=Path)
    parser.add_argument("--font", required=True, type=Path)
    parser.add_argument("--samples", type=int, default=7)
    parser.add_argument("--warmups", type=int, default=2)
    parser.add_argument("--batch-size", type=int, default=4)
    cpu_count = os.cpu_count()
    parser.add_argument("--workers", type=int, default=min(32, cpu_count + 4 if cpu_count is not None else 4))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.samples < 3 or args.warmups < 1 or args.workers < 1 or args.batch_size < 1:
        parser.error("use at least 3 samples, 1 warmup, 1 worker, and 1 participant")
    repository = Path(__file__).resolve().parents[1]
    source = subprocess.check_output(
        ["git", "show", f"{BASE}:png.py"], cwd=repository, text=True,
    )
    with Image.open(args.template) as template:
        full = template.convert("RGBA")
    rng = random.Random(17)
    cases = {
        "tiny_1x1": Image.new("RGBA", (1, 1), "white"),
        "small_64x32": Image.frombytes("RGBA", (64, 32), rng.randbytes(64 * 32 * 4)),
        "solid_800x600": Image.new("RGBA", (800, 600), "white"),
        "pattern_800x600": Image.frombytes("RGBA", (800, 600), bytes(range(256)) * 7500),
        "template": full,
        "noise_full_size": Image.frombytes("RGBA", full.size, rng.randbytes(full.width * full.height * 4)),
        "wide_20000x2": Image.frombytes("RGBA", (20000, 2), rng.randbytes(20000 * 2 * 4)),
        "tall_solid_1x20000": Image.new("RGBA", (1, 20000), "white"),
        "tall_noise_1x20000": Image.frombytes("RGBA", (1, 20000), rng.randbytes(20000 * 4)),
    }
    report = {
        "baseline": BASE,
        "environment": {
            "python": platform.python_version(), "pillow": pillow_version,
            "platform": platform.platform(), "cpu_count": os.cpu_count(),
            "machine": platform.machine(), "processor": platform.processor(),
            "load_average": os.getloadavg() if hasattr(os, "getloadavg") else None,
            "samples": args.samples, "warmups": args.warmups,
            "batch_workers": args.workers,
        },
        "encoding": {},
    }
    with tempfile.TemporaryDirectory(prefix="png-benchmark-") as directory:
        root = Path(directory)
        baseline_file = root / "baseline_png.py"
        baseline_file.write_text(source, encoding="utf-8")
        spec = importlib.util.spec_from_file_location("baseline_png", baseline_file)
        assert spec is not None and spec.loader is not None
        baseline = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(baseline)
        old_path, new_path = root / "baseline.png", root / "candidate.png"
        for name, image in cases.items():
            operations = {
                "baseline": lambda image=image: image.save(old_path),
                "candidate": lambda image=image: save_rgba_png(
                    new_path, *image.size, image.tobytes(),
                    icc_profile=image.info.get("icc_profile"),
                ),
            }
            iterations = 100 if name == "tiny_1x1" else 20 if name == "small_64x32" else 1
            timings = measure(operations, args.samples, args.warmups, iterations)
            with Image.open(old_path) as previous, Image.open(new_path) as current:
                assert previous.size == current.size == image.size
                assert previous.tobytes() == current.tobytes() == image.tobytes()
                assert previous.info == current.info
            report["encoding"][name] = {
                "size": image.size, "timings": timings,
                "baseline_bytes": old_path.stat().st_size,
                "candidate_bytes": new_path.stat().st_size,
            }
            print(f"Measured encoding: {name}", file=sys.stderr, flush=True)

        names = ["Ada Lovelace", "Zoë José", "A\u0301 Smith", "A very long participant name"]
        rows = [{"name": names[index % len(names)]} for index in range(args.batch_size)]
        folders = {name: root / name for name in ["baseline", "candidate"]}
        for folder in folders.values():
            folder.mkdir()

        def batch(process, folder):
            with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as executor:
                futures = [
                    executor.submit(
                        process, row, index, args.template, args.font, folder, 92, "black", -82,
                    )
                    for index, row in enumerate(rows, 1)
                ]
                for future in futures:
                    future.result()

        with contextlib.redirect_stdout(io.StringIO()):
            report["batch"] = measure({
                "baseline": lambda: batch(baseline.process_certificate, folders["baseline"]),
                "candidate": lambda: batch(png.process_certificate, folders["candidate"]),
            }, args.samples, args.warmups)
        for index in range(1, len(rows) + 1):
            filename = f"certificate_{index:03d}.png"
            with (
                Image.open(folders["baseline"] / filename) as previous,
                Image.open(folders["candidate"] / filename) as current,
            ):
                assert previous.tobytes() == current.tobytes()
                assert previous.info == current.info
        report["batch_certificates"] = len(rows)
        report["pixel_and_metadata_checks"] = "pass"
    encoded = json.dumps(report, indent=2)
    if args.output:
        args.output.write_text(encoded + "\n", encoding="utf-8")
    print(encoded)


if __name__ == "__main__":
    main()
