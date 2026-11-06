"""Independent PNG predictor oracle for the native filtering boundary."""

import concurrent.futures
import random
import unittest

from _png_filters import filter_rows


def oracle(raw, previous, stride):
    rows = []
    for start in range(0, len(raw), stride):
        row = raw[start:start + stride]
        candidates = {0: row, 2: bytearray(), 1: bytearray(), 4: bytearray()}
        for i, value in enumerate(row):
            a = row[i - 4] if i >= 4 else 0
            b = previous[i]
            c = previous[i - 4] if i >= 4 else 0
            p = a + b - c
            distances = [abs(p - neighbor) for neighbor in [a, b, c]]
            paeth = [a, b, c][distances.index(min(distances))]
            for kind, predictor in [(2, b), (1, a), (4, paeth)]:
                candidates[kind].append((value - predictor) % 256)
        kind = min(candidates, key=lambda kind: sum(min(v, 256 - v) for v in candidates[kind]))
        rows.append(bytes([kind]) + bytes(candidates[kind]))
        previous = row
    return b"".join(rows)


class NativeFilterTests(unittest.TestCase):
    def test_predictors_and_strict_ties_match_independent_oracle(self):
        rng = random.Random(3351)
        for width, height in [(1, 1), (1, 127), (2, 47), (79, 61)]:
            stride = width * 4
            for raw in [rng.randbytes(stride * height), bytes(stride * height),
                        bytes([255]) * stride * height, bytes([128]) * stride * height,
                        (bytes(range(256)) * ((stride * height + 255) // 256))[:stride * height]]:
                for previous in [bytes(stride), rng.randbytes(stride)]:
                    with self.subTest(size=(width, height), previous=previous[:8]):
                        self.assertEqual(filter_rows(raw, previous, stride), oracle(raw, previous, stride))

    def test_arbitrary_batch_boundaries_preserve_previous_row(self):
        stride = 28
        raw = random.Random(837).randbytes(stride * 91)
        expected = oracle(raw, bytes(stride), stride)
        for count in [1, 2, 7, 91]:
            previous = bytes(stride)
            parts = []
            for start in range(0, len(raw), count * stride):
                block = raw[start:start + count * stride]
                parts.append(filter_rows(block, previous, stride))
                previous = block[-stride:]
            self.assertEqual(b"".join(parts), expected)

    def test_empty_batch_and_invalid_native_arguments(self):
        self.assertEqual(filter_rows(b"", bytes(4), 4), b"")
        for raw, previous, stride in [(b"", b"", 0), (b"", b"", -4),
                                      (b"1234", b"1234", 3), (b"123", b"1234", 4),
                                      (b"1234", b"123", 4)]:
            with self.assertRaises(ValueError):
                filter_rows(raw, previous, stride)
        with self.assertRaises(TypeError):
            filter_rows(bytearray(4), bytes(4), 4)

    def test_concurrent_calls_have_no_shared_filter_state(self):
        stride = 52
        raw = random.Random(51).randbytes(stride * 63)
        expected = oracle(raw, bytes(stride), stride)
        with concurrent.futures.ThreadPoolExecutor(max_workers=16) as executor:
            jobs = [executor.submit(filter_rows, raw, bytes(stride), stride) for _ in range(64)]
            self.assertTrue(all(job.result() == expected for job in jobs))
