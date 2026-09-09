"""Tests for JournalStore's time-lapse still tracking and GIF compilation
(B5 — automated time-lapse tied to the stage timeline).

Bypasses JournalStore.__init__ (which needs a real HA Store/hass.data) and
builds a minimal instance directly, with a fake hass whose
async_add_executor_job just runs the function inline — exercises the real
Pillow-based GIF assembly against real temporary JPEG files.
"""
from __future__ import annotations

import copy
import os

import pytest
from PIL import Image

from custom_components.helix_cultivate.journal_store import EMPTY_STORE, JournalStore


class _FakeHass:
    async def async_add_executor_job(self, func, *args):
        return func(*args)


def _make_store() -> JournalStore:
    store = JournalStore.__new__(JournalStore)
    store._hass = _FakeHass()
    store._data = copy.deepcopy(EMPTY_STORE)
    store._save = _noop_save.__get__(store)
    return store


async def _noop_save(self) -> None:
    return None


def _write_jpeg(path: str, color: tuple[int, int, int]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    Image.new("RGB", (20, 15), color=color).save(path, format="JPEG")


@pytest.mark.asyncio
async def test_add_and_pop_timelapse_images(tmp_path):
    store = _make_store()
    p1 = str(tmp_path / "day1.jpg")
    p2 = str(tmp_path / "day2.jpg")
    _write_jpeg(p1, (255, 0, 0))
    _write_jpeg(p2, (0, 255, 0))

    await store.async_add_timelapse_image("entry_a", p1)
    await store.async_add_timelapse_image("entry_a", p2)
    await store.async_add_timelapse_image("entry_b", str(tmp_path / "other.jpg"))

    popped = await store.async_pop_timelapse_images("entry_a")
    assert [r["path"] for r in popped] == [p1, p2]

    # Popping clears only entry_a's images — entry_b's remain, and entry_a
    # popping again returns nothing (already cleared for the next cycle).
    assert await store.async_pop_timelapse_images("entry_a") == []
    remaining_b = await store.async_pop_timelapse_images("entry_b")
    assert len(remaining_b) == 1


@pytest.mark.asyncio
async def test_compile_timelapse_gif_writes_animated_gif(tmp_path):
    store = _make_store()
    paths = []
    for i, color in enumerate([(255, 0, 0), (0, 255, 0), (0, 0, 255)]):
        p = str(tmp_path / f"still_{i}.jpg")
        _write_jpeg(p, color)
        paths.append(p)

    out_path = str(tmp_path / "out" / "timelapse.gif")
    ok = await store.async_compile_timelapse_gif(paths, out_path)

    assert ok is True
    assert os.path.isfile(out_path)
    with Image.open(out_path) as gif:
        assert gif.n_frames == 3


@pytest.mark.asyncio
async def test_compile_timelapse_gif_no_readable_stills_returns_false(tmp_path):
    store = _make_store()
    out_path = str(tmp_path / "timelapse.gif")

    ok = await store.async_compile_timelapse_gif(
        [str(tmp_path / "does_not_exist.jpg")], out_path
    )

    assert ok is False
    assert not os.path.isfile(out_path)
