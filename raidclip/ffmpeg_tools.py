"""ffmpeg / ffprobe の探索とコマンド生成。GUI に依存しない純粋ロジック。"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------- バイナリ探索


def _exe(name: str) -> str:
    return f"{name}.exe" if sys.platform.startswith("win") else name


def _candidate_dirs() -> list[Path]:
    dirs: list[Path] = []
    # PyInstaller で固めた場合: exe と同じ場所 / その下の ffmpeg フォルダ
    if getattr(sys, "frozen", False):
        base = Path(sys.executable).resolve().parent
        dirs += [base, base / "ffmpeg"]
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            dirs += [Path(meipass), Path(meipass) / "ffmpeg"]
    # ソースから実行した場合: リポジトリ直下 / その下の ffmpeg フォルダ
    root = Path(__file__).resolve().parent.parent
    dirs += [root, root / "ffmpeg", Path.cwd(), Path.cwd() / "ffmpeg"]
    return dirs


def find_binary(name: str) -> Optional[str]:
    """ffmpeg / ffprobe を、同梱フォルダ -> PATH -> imageio-ffmpeg の順で探す。"""
    exe = _exe(name)
    for d in _candidate_dirs():
        p = d / exe
        if p.is_file():
            return str(p)
    found = shutil.which(name)
    if found:
        return found
    if name == "ffmpeg":
        try:  # 開発時・テスト用のフォールバック
            import imageio_ffmpeg  # type: ignore

            return imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:
            return None
    return None


def creation_flags() -> int:
    """Windows でコンソール窓が出ないようにするフラグ。"""
    return getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform.startswith("win") else 0


# ---------------------------------------------------------------- probe


@dataclass
class MediaInfo:
    path: str
    duration: float  # 秒
    width: int
    height: int
    video_codec: str
    audio_codec: str
    size_bytes: int


def probe(path: str) -> MediaInfo:
    """動画の長さ・解像度などを取得する。ffprobe が無ければ ffmpeg の stderr から推定。"""
    ffprobe = find_binary("ffprobe")
    if ffprobe:
        out = subprocess.run(
            [
                ffprobe, "-v", "error", "-print_format", "json",
                "-show_format", "-show_streams", path,
            ],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            creationflags=creation_flags(), check=True,
        ).stdout
        data = json.loads(out)
        fmt = data.get("format", {})
        streams = data.get("streams", [])
        v = next((s for s in streams if s.get("codec_type") == "video"), {})
        a = next((s for s in streams if s.get("codec_type") == "audio"), {})
        duration = float(fmt.get("duration") or v.get("duration") or 0.0)
        return MediaInfo(
            path=path,
            duration=duration,
            width=int(v.get("width") or 0),
            height=int(v.get("height") or 0),
            video_codec=str(v.get("codec_name") or ""),
            audio_codec=str(a.get("codec_name") or ""),
            size_bytes=int(fmt.get("size") or os.path.getsize(path)),
        )

    ffmpeg = find_binary("ffmpeg")
    if not ffmpeg:
        raise FileNotFoundError("ffmpeg が見つかりません")
    res = subprocess.run(
        [ffmpeg, "-hide_banner", "-i", path],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        creationflags=creation_flags(),
    )
    return _parse_ffmpeg_banner(path, res.stderr)


def _parse_ffmpeg_banner(path: str, text: str) -> MediaInfo:
    import re

    duration = 0.0
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", text)
    if m:
        h, mi, s = m.groups()
        duration = int(h) * 3600 + int(mi) * 60 + float(s)
    width = height = 0
    vcodec = acodec = ""
    mv = re.search(r"Video:\s*(\w+).*?(\d{2,5})x(\d{2,5})", text)
    if mv:
        vcodec, w, h = mv.groups()
        width, height = int(w), int(h)
    ma = re.search(r"Audio:\s*(\w+)", text)
    if ma:
        acodec = ma.group(1)
    return MediaInfo(path, duration, width, height, vcodec, acodec, os.path.getsize(path))


# ---------------------------------------------------------------- コマンド生成


DISCORD_PRESETS_MB = {
    "無料 (10MB)": 10,
    "旧無料枠 (25MB)": 25,
    "Nitro Basic (50MB)": 50,
    "Nitro (500MB)": 500,
}


def fmt_time(sec: float) -> str:
    """秒 -> ffmpeg に渡す HH:MM:SS.mmm"""
    sec = max(0.0, sec)
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = sec - h * 3600 - m * 60
    return f"{h:02d}:{m:02d}:{s:06.3f}"


def parse_time(text: str) -> float:
    """'1:23.5' / '83.5' / '0:01:23' のような表記を秒に変換する。"""
    text = text.strip()
    if not text:
        raise ValueError("空です")
    parts = text.split(":")
    if len(parts) > 3:
        raise ValueError("時刻の形式が不正です")
    total = 0.0
    for p in parts:
        total = total * 60 + float(p)
    if total < 0:
        raise ValueError("負の時刻です")
    return total


def build_copy_cmd(ffmpeg: str, src: str, dst: str, start: float, end: float) -> list[str]:
    """無劣化・高速。キーフレーム単位なので開始位置が数秒前にずれることがある。"""
    return [
        ffmpeg, "-hide_banner", "-y",
        "-ss", fmt_time(start), "-to", fmt_time(end),
        "-i", src,
        "-map", "0:v:0?", "-map", "0:a?",
        "-c", "copy",
        "-avoid_negative_ts", "make_zero",
        "-movflags", "+faststart",
        "-progress", "pipe:1", "-nostats",
        dst,
    ]


def build_accurate_cmd(
    ffmpeg: str, src: str, dst: str, start: float, end: float, crf: int = 20
) -> list[str]:
    """フレーム単位で正確。再エンコードするので時間はかかるが画質は十分。"""
    return [
        ffmpeg, "-hide_banner", "-y",
        "-ss", fmt_time(start),
        "-i", src,
        "-t", fmt_time(end - start),
        "-map", "0:v:0", "-map", "0:a?",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf),
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "160k",
        "-movflags", "+faststart",
        "-progress", "pipe:1", "-nostats",
        dst,
    ]


@dataclass
class FitPlan:
    video_kbps: int
    audio_kbps: int
    scale_height: Optional[int]  # None なら元のまま
    passlog: str


def plan_fit(target_mb: float, duration: float, src_height: int, passlog: str) -> FitPlan:
    """指定サイズに収まるビットレートを計算し、必要なら解像度も落とす。"""
    if duration <= 0:
        raise ValueError("長さが 0 です")
    # コンテナのオーバーヘッドと二パスの誤差を見込んで 5% 余裕を取る
    total_kbps = target_mb * 8 * 1024 * 0.95 / duration
    audio_kbps = 128 if total_kbps > 1200 else 96 if total_kbps > 500 else 64
    video_kbps = int(total_kbps - audio_kbps)
    if video_kbps < 150:
        raise ValueError(
            f"{target_mb:g}MB に収めるにはビットレートが低すぎます。範囲を短くしてください。"
        )
    scale: Optional[int] = None
    if src_height > 1080 and video_kbps < 8000:
        scale = 1080
    if src_height > 720 and video_kbps < 3000:
        scale = 720
    if src_height > 480 and video_kbps < 1000:
        scale = 480
    if src_height > 360 and video_kbps < 400:
        scale = 360
    return FitPlan(video_kbps, audio_kbps, scale, passlog)


def build_fit_cmds(
    ffmpeg: str, src: str, dst: str, start: float, end: float, plan: FitPlan
) -> list[list[str]]:
    """二パスエンコード。戻り値は [pass1, pass2] のコマンド列。"""
    common = [
        ffmpeg, "-hide_banner", "-y",
        "-ss", fmt_time(start),
        "-i", src,
        "-t", fmt_time(end - start),
        "-map", "0:v:0",
        "-c:v", "libx264", "-preset", "medium",
        "-b:v", f"{plan.video_kbps}k",
        "-maxrate", f"{int(plan.video_kbps * 1.3)}k",
        "-bufsize", f"{int(plan.video_kbps * 2)}k",
        "-pix_fmt", "yuv420p",
        "-passlogfile", plan.passlog,
    ]
    if plan.scale_height:
        common += ["-vf", f"scale=-2:{plan.scale_height}"]
    null_out = "NUL" if sys.platform.startswith("win") else "/dev/null"
    pass1 = common + [
        "-pass", "1", "-an", "-f", "mp4",
        "-progress", "pipe:1", "-nostats",
        null_out,
    ]
    pass2 = common + [
        "-pass", "2",
        "-map", "0:a?", "-c:a", "aac", "-b:a", f"{plan.audio_kbps}k",
        "-movflags", "+faststart",
        "-progress", "pipe:1", "-nostats",
        dst,
    ]
    return [pass1, pass2]


def build_frame_cmd(ffmpeg: str, src: str, dst_png: str, t: float, max_width: int = 1920) -> list[str]:
    """指定時刻のフレームを PNG に書き出す。横幅が max_width を超える場合だけ縮小する。"""
    return [
        ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
        "-ss", fmt_time(t),
        "-i", src,
        "-frames:v", "1",
        "-vf", f"scale=min(iw\\,{max_width}):-2",
        dst_png,
    ]


def extract_frame(ffmpeg: str, src: str, dst_png: str, t: float, max_width: int = 1920) -> None:
    subprocess.run(
        build_frame_cmd(ffmpeg, src, dst_png, t, max_width),
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        creationflags=creation_flags(), check=True,
    )


def parse_progress_line(line: str) -> Optional[float]:
    """-progress の出力から処理済み秒数を取り出す。該当行でなければ None。"""
    line = line.strip()
    if line.startswith("out_time_us="):
        try:
            return int(line.split("=", 1)[1]) / 1_000_000
        except ValueError:
            return None
    if line.startswith("out_time_ms="):  # 古い ffmpeg は名前に反してマイクロ秒
        try:
            return int(line.split("=", 1)[1]) / 1_000_000
        except ValueError:
            return None
    if line.startswith("out_time="):
        try:
            return parse_time(line.split("=", 1)[1])
        except ValueError:
            return None
    return None


def default_output_path(src: str, suffix: str = "_clip") -> str:
    p = Path(src)
    base = p.with_name(p.stem + suffix + ".mp4")
    n = 2
    while base.exists():
        base = p.with_name(f"{p.stem}{suffix}{n}.mp4")
        n += 1
    return str(base)
