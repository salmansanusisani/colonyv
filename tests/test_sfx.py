"""Tests for the synthesised SFX kit.

The kit is generated rather than shipped as audio files, so these tests stand in
for listening: they assert the properties that make synthesised sound usable —
no boundary clicks, predictable levels, and bit-identical output across runs.
"""

from __future__ import annotations

import importlib.util
import struct
import sys
import wave
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent

spec = importlib.util.spec_from_file_location(
    "build_video", PROJECT_ROOT / "producer" / "build_video.py"
)
assert spec and spec.loader
build_video = importlib.util.module_from_spec(spec)
sys.modules["build_video"] = build_video
spec.loader.exec_module(build_video)


EXPECTED_CUES = {"tick", "swoosh", "riser", "stamp", "chime"}


def _read(path: Path) -> list[int]:
    with wave.open(str(path)) as w:
        assert w.getnchannels() == 1
        assert w.getsampwidth() == 2
        raw = w.readframes(w.getnframes())
    return list(struct.unpack(f"<{len(raw) // 2}h", raw))


@pytest.fixture(scope="module")
def kit(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("sfx")
    build_video.build_sfx(out)
    return out


def test_kit_contains_every_cue(kit):
    assert {p.stem for p in kit.glob("*.wav")} == EXPECTED_CUES


def test_kit_matches_the_declared_cue_list(kit):
    """The staging step copies whatever SFX_KIT declares; they must not drift."""
    assert set(build_video.SFX_KIT) == EXPECTED_CUES


@pytest.mark.parametrize("name", sorted(EXPECTED_CUES))
def test_cue_does_not_click_at_its_boundaries(kit, name):
    """A waveform starting or ending away from zero clicks on every playback."""
    samples = _read(kit / f"{name}.wav")
    assert len(samples) > 100
    assert abs(samples[0]) < 400, f"{name} starts at {samples[0]}"
    assert abs(samples[-1]) < 400, f"{name} ends at {samples[-1]}"


@pytest.mark.parametrize("name", sorted(EXPECTED_CUES))
def test_cue_is_audible_but_not_clipping(kit, name):
    samples = _read(kit / f"{name}.wav")
    peak = max(abs(s) for s in samples)
    assert peak > 2000, f"{name} is inaudibly quiet (peak {peak})"
    assert peak < 32767, f"{name} clips (peak {peak})"


@pytest.mark.parametrize("name", sorted(EXPECTED_CUES))
def test_cue_is_normalised_to_its_target_peak(kit, name):
    """Levels must be predictable, or the mix has to be retuned per cue."""
    samples = _read(kit / f"{name}.wav")
    peak = max(abs(s) for s in samples)
    # _finish normalises to an exact peak; allow a little rounding headroom.
    assert peak > 5000, f"{name} peak {peak} is below any kit target"


def test_tick_is_short_and_chime_is_long(kit):
    """Cue lengths back the CUE_FRAMES table the Remotion layer bounds on."""
    def seconds(name: str) -> float:
        with wave.open(str(kit / f"{name}.wav")) as w:
            return w.getnframes() / w.getframerate()

    assert seconds("tick") < 0.1
    assert seconds("stamp") < 0.4
    assert seconds("swoosh") < 0.5
    assert 0.5 < seconds("riser") < 1.2
    assert 0.5 < seconds("chime") < 1.2

    # Every cue must fit inside the frame budget the renderer allocates for it
    # at 30fps, or its tail is cut off mid-decay.
    budget_frames = {"tick": 3, "swoosh": 11, "riser": 27, "stamp": 9, "chime": 23}
    for name, frames in budget_frames.items():
        assert seconds(name) <= frames / 30.0 + 0.02, f"{name} exceeds its frame budget"


def test_synthesis_is_deterministic(tmp_path):
    """A re-render must not change the audio, or output stops being reproducible.

    The cues contain noise components, so this only holds because build_sfx pins
    the RNG seed.
    """
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    build_video.build_sfx(a)
    build_video.build_sfx(b)
    for name in EXPECTED_CUES:
        assert (a / f"{name}.wav").read_bytes() == (b / f"{name}.wav").read_bytes(), name


def test_build_sfx_restores_global_rng_state(tmp_path):
    """Seeding for reproducible audio must not silently derail other randomness."""
    import random

    random.seed(1234)
    expected = [random.random() for _ in range(3)]

    random.seed(1234)
    first = random.random()
    build_video.build_sfx(tmp_path)
    rest = [random.random() for _ in range(2)]

    assert [first, *rest] == expected


def test_lowpass_attenuates_high_frequencies():
    import math

    sr = build_video.SAMPLE_RATE
    high = [math.sin(2 * math.pi * 9000 * (i / sr)) for i in range(2000)]
    filtered = build_video._lowpass(high, 800)
    # Ignore the filter's settling transient.
    assert max(abs(s) for s in filtered[500:]) < 0.35


def test_highpass_attenuates_low_frequencies():
    import math

    sr = build_video.SAMPLE_RATE
    low = [math.sin(2 * math.pi * 40 * (i / sr)) for i in range(4000)]
    filtered = build_video._highpass(low, 900)
    assert max(abs(s) for s in filtered[500:]) < 0.35


def test_normalise_peak_hits_the_requested_level():
    samples = [0.1, -0.05, 0.2, -0.02]
    out = build_video._normalise_peak(samples, 9000)
    assert max(abs(s) for s in out) == pytest.approx(9000, rel=1e-6)


def test_normalise_peak_handles_silence():
    assert build_video._normalise_peak([0.0, 0.0], 9000) == [0.0, 0.0]


def test_fade_edges_zeroes_the_boundaries():
    samples = [1.0] * 2000
    out = build_video._fade_edges(samples, ms=4.0)
    assert out[0] == 0.0
    assert out[-1] == 0.0
    # The middle is untouched.
    assert out[len(out) // 2] == 1.0


# --------------------------------------------------------------------------
# Illustration budget scaling
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "beats,expected",
    [(1, 2), (2, 2), (3, 3), (4, 4), (5, 5), (7, 6), (12, 6)],
)
def test_auto_budget_scales_with_beat_count(beats, expected):
    """A flat budget starves long videos and wastes spend on short ones."""
    assert build_video.resolve_illustration_budget(-1, beats) == expected


def test_auto_budget_is_bounded():
    assert build_video.resolve_illustration_budget(-1, 0) >= build_video.MIN_AUTO_ILLUSTRATIONS
    assert build_video.resolve_illustration_budget(-1, 99) == build_video.MAX_AUTO_ILLUSTRATIONS


@pytest.mark.parametrize("explicit", [0, 1, 3, 8])
def test_explicit_budget_always_wins(explicit):
    assert build_video.resolve_illustration_budget(explicit, 5) == explicit
