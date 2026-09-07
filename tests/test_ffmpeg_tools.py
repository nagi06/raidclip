import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from raidclip import ffmpeg_tools as ft  # noqa: E402

FFMPEG = ft.find_binary("ffmpeg")
pytestmark = pytest.mark.skipif(FFMPEG is None, reason="ffmpeg がありません")


def test_parse_time():
    assert ft.parse_time("83.5") == 83.5
    assert ft.parse_time("1:23.5") == 83.5
    assert ft.parse_time("0:01:23") == 83
    with pytest.raises(ValueError):
        ft.parse_time("a:b")


def test_fmt_time():
    assert ft.fmt_time(83.5) == "00:01:23.500"
    assert ft.fmt_time(3600) == "01:00:00.000"


def test_parse_progress_line():
    assert ft.parse_progress_line("out_time_us=1500000") == 1.5
    assert ft.parse_progress_line("out_time=00:00:02.500000") == 2.5
    assert ft.parse_progress_line("frame=12") is None


def test_plan_fit_scales_down_when_bitrate_low():
    p = ft.plan_fit(10, 120, 1080, "x")  # 10MB に 2 分 → 約 650kbps
    assert p.scale_height == 480
    p = ft.plan_fit(500, 60, 1080, "x")
    assert p.scale_height is None
    with pytest.raises(ValueError):
        ft.plan_fit(10, 3600, 1080, "x")


@pytest.fixture(scope="module")
def sample(tmp_path_factory):
    d = tmp_path_factory.mktemp("v")
    src = d / "src.mp4"
    subprocess.run(
        [FFMPEG, "-hide_banner", "-y",
         "-f", "lavfi", "-i", "testsrc=size=640x360:rate=30",
         "-f", "lavfi", "-i", "sine=frequency=440",
         "-t", "6", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
         "-c:a", "aac", str(src)],
        check=True, capture_output=True,
    )
    return src


def _run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-2000:]
    assert "out_time" in r.stdout
    return r


def test_probe(sample):
    info = ft.probe(str(sample))
    assert 5.5 < info.duration < 6.5
    assert (info.width, info.height) == (640, 360)


def test_copy_cut(sample, tmp_path):
    dst = tmp_path / "copy.mp4"
    _run(ft.build_copy_cmd(FFMPEG, str(sample), str(dst), 1.0, 4.0))
    info = ft.probe(str(dst))
    assert 2.0 < info.duration < 4.5  # キーフレーム単位なので幅を持たせる


def test_accurate_cut(sample, tmp_path):
    dst = tmp_path / "acc.mp4"
    _run(ft.build_accurate_cmd(FFMPEG, str(sample), str(dst), 1.0, 4.0))
    info = ft.probe(str(dst))
    assert 2.8 < info.duration < 3.2


def test_fit_cut(sample, tmp_path):
    dst = tmp_path / "fit.mp4"
    plan = ft.plan_fit(0.5, 5.0, 360, str(tmp_path / "log"))
    for cmd in ft.build_fit_cmds(FFMPEG, str(sample), str(dst), 0.0, 5.0, plan):
        _run(cmd)
    assert os.path.getsize(dst) <= 0.5 * 1024 * 1024
    info = ft.probe(str(dst))
    assert 4.8 < info.duration < 5.2


def test_default_output_path(tmp_path):
    src = tmp_path / "raid.mp4"
    src.write_bytes(b"")
    assert ft.default_output_path(str(src)).endswith("raid_clip.mp4")
    (tmp_path / "raid_clip.mp4").write_bytes(b"")
    assert ft.default_output_path(str(src)).endswith("raid_clip2.mp4")
