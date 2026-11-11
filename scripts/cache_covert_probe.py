#!/usr/bin/env python3
"""Opt-in, real-wall-clock counterpart to the deterministic covert-channel scenario.

The `agent-covert-channel` lab scenario models Prime+Probe deterministically so
its switch and tests never depend on hardware timing. This script instead measures
real `time.perf_counter()` latencies on a large shared buffer to show the same
idea on actual silicon: a sender evicts chosen cache sets, a receiver times its
own lines and recovers the transmitted bits.

Real microarchitectural timing is noisy, and a Docker/VM host (for example macOS
or CI) smooths much of it away, so the bit-error rate here is expected to be
non-zero and host-dependent. This is a demonstration, not a reliable channel, and
it is never part of the automated suite. Run it directly, or through the pytest
case guarded by RUN_SIDECHANNEL=1.

    python scripts/cache_covert_probe.py --byte 0x41 --trials 9
"""
import argparse
import time

SETS = 8                 # One set per transmitted bit, matching the lab model.
WAYS = 16                # Lines timed per set.
STRIDE = 4096            # Spread lines across cache sets by page stride.
BUFFER_LINES = 1 << 16   # Shared buffer large enough to overflow low-level caches.
MISS_FACTOR = 1.6        # A line counts as evicted when it times this much over the hit floor.


def _buffer():
    # A list of small objects whose reads the interpreter cannot fold away.
    return [[0] for _ in range(BUFFER_LINES)]


def _touch(buffer, index):
    buffer[index % BUFFER_LINES][0] ^= 1


def _time_line(buffer, index):
    start = time.perf_counter()
    _touch(buffer, index)
    return time.perf_counter() - start


def _prime(buffer, set_index):
    base = set_index * STRIDE
    for way in range(WAYS):
        _touch(buffer, base + way * SETS)


def _evict(buffer, set_index):
    # A second region mapping to the same sets, used by the "sender" to evict.
    base = set_index * STRIDE + (BUFFER_LINES // 2)
    for way in range(WAYS * 4):
        _touch(buffer, base + way * SETS)


def _probe(buffer, set_index, floor):
    base = set_index * STRIDE
    misses = 0
    for way in range(WAYS):
        if _time_line(buffer, base + way * SETS) > floor * MISS_FACTOR:
            misses += 1
    return misses


def _floor(buffer):
    samples = sorted(_time_line(buffer, i * SETS) for i in range(WAYS * 4))
    return samples[len(samples) // 2] or 1e-9


def run(byte=0x41, trials=9):
    """Transmit one byte repeatedly over real timing; return the recovery stats."""
    buffer = _buffer()
    bits = [(byte >> i) & 1 for i in range(SETS)]
    floor = _floor(buffer)
    recovered_votes = [0] * SETS
    for _ in range(trials):
        for set_index in range(SETS):
            _prime(buffer, set_index)
        for set_index, bit in enumerate(bits):
            if bit:
                _evict(buffer, set_index)
        for set_index in range(SETS):
            if _probe(buffer, set_index, floor) >= WAYS // 2:
                recovered_votes[set_index] += 1
    recovered_bits = [1 if votes * 2 >= trials else 0 for votes in recovered_votes]
    recovered = sum(bit << i for i, bit in enumerate(recovered_bits))
    errors = sum(a != b for a, b in zip(bits, recovered_bits))
    return {'sent': byte, 'recovered': recovered, 'bits': SETS, 'trials': trials,
            'bit_error_rate': errors / SETS, 'floor_seconds': floor}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--byte', type=lambda v: int(v, 0), default=0x41)
    parser.add_argument('--trials', type=int, default=9)
    args = parser.parse_args()
    report = run(byte=args.byte, trials=args.trials)
    print(f"sent      0x{report['sent']:02X} ({report['sent']:08b})")
    print(f"recovered 0x{report['recovered']:02X} ({report['recovered']:08b})")
    print(f"bit error rate {report['bit_error_rate']:.3f} over {report['trials']} trials")
    print('Note: real timing is host-dependent and noisy; the deterministic lab scenario is the reliable one.')


if __name__ == '__main__':
    main()
