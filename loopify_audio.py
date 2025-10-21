"""Loopify audio by rotating audio content around a cut point.

The tool splits an audio file at the requested timestamp, swaps the parts,
and writes a seamless loop where the end connects back to the original start.
It relies on ffmpeg/ffprobe on the PATH, performs minimal validation, and
falls back to re-encoding only if stream-copy concatenation fails.
"""

from __future__ import annotations

import argparse
import json
import math
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Iterable, Sequence


def _run(cmd: Sequence[str]) -> None:
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip() or "command failed"
        raise RuntimeError(f"{cmd[0]} failed: {message}")


def _probe_duration(path: Path) -> float:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-show_streams",
        "-of",
        "json",
        str(path),
    ]
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip() or "unable to probe input"
        raise RuntimeError(f"ffprobe failed: {message}")
    data = json.loads(result.stdout or "{}")
    streams = data.get("streams") or []
    if not any(stream.get("codec_type") == "audio" for stream in streams):
        raise RuntimeError("Input file does not contain an audio stream.")
    duration_value = data.get("format", {}).get("duration")
    if duration_value is None:
        raise RuntimeError("Unable to determine input duration.")
    try:
        duration = float(duration_value)
    except (TypeError, ValueError):
        raise RuntimeError("Invalid duration value reported by ffprobe.") from None
    if math.isnan(duration):
        return 0.0
    return duration


def _format_time(value: float) -> str:
    text = f"{value:.6f}"
    text = text.rstrip("0").rstrip(".")
    return text or "0"


def _concat_line(path: Path) -> str:
    escaped = str(path).replace("'", "'\\''")
    return f"file '{escaped}'"


def _infer_codec_args(suffix: str) -> list[str]:
    ext = suffix.lower()
    if ext == ".mp3":
        return ["-c:a", "libmp3lame", "-q:a", "2"]
    if ext == ".wav":
        return ["-c:a", "pcm_s16le"]
    return ["-c:a", "aac", "-b:a", "192k"]


def _copy_file(src: Path, dest: Path, same_path: bool) -> None:
    if same_path:
        with tempfile.NamedTemporaryFile(dir=str(dest.parent), suffix=dest.suffix, delete=False) as tmp:
            temp_path = Path(tmp.name)
        try:
            shutil.copy2(src, temp_path)
            temp_path.replace(dest)
        finally:
            if temp_path.exists():
                temp_path.unlink()
    else:
        shutil.copy2(src, dest)


def loopify_audio(
    input_path: str | Path,
    cut_seconds: float,
    output_path: str | Path | None = None,
    force: bool = False,
) -> Path:
    """Create a loop-friendly audio file by rotating around ``cut_seconds``."""

    src = Path(input_path).expanduser()
    if not src.exists() or not src.is_file():
        raise RuntimeError(f"Input file not found: {src}")

    if not math.isfinite(cut_seconds):
        raise RuntimeError("cut_seconds must be a finite number.")

    duration = _probe_duration(src)

    if output_path is None:
        suffix = src.suffix
        output_name = f"{src.stem}.loopified{suffix}"
        dest = src.with_name(output_name)
    else:
        dest = Path(output_path).expanduser()

    if not dest.parent.exists():
        raise RuntimeError(f"Output directory does not exist: {dest.parent}")

    src_resolved = src.resolve()
    dest_resolved = dest.resolve()
    same_path = src_resolved == dest_resolved

    if dest.exists():
        if not force:
            raise RuntimeError(f"Refusing to overwrite existing file: {dest}")
        if not same_path:
            dest.unlink()
    elif same_path and not force:
        raise RuntimeError("Refusing to overwrite input file without force.")

    if duration <= 0:
        _copy_file(src, dest, same_path)
        return dest_resolved

    cut = cut_seconds % duration
    if math.isclose(cut, 0.0, abs_tol=1e-6):
        _copy_file(src, dest, same_path)
        return dest_resolved

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp = Path(tmp_dir)
        suffix = src.suffix or dest.suffix
        part_b = tmp / f"part_b{suffix}"
        part_a = tmp / f"part_a{suffix}"
        list_file = tmp / "concat.txt"
        work_output = dest if not same_path else tmp / f"output{suffix}"

        cut_text = _format_time(cut)

        _run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-y",
                "-i",
                str(src),
                "-ss",
                cut_text,
                "-c",
                "copy",
                str(part_b),
            ]
        )
        _run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-y",
                "-i",
                str(src),
                "-t",
                cut_text,
                "-c",
                "copy",
                str(part_a),
            ]
        )

        list_file.write_text(
            "\n".join(_concat_line(path.resolve()) for path in (part_b, part_a)) + "\n",
            encoding="utf-8",
        )

        concat_cmd = [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(list_file),
            "-c",
            "copy",
            str(work_output),
        ]

        try:
            _run(concat_cmd)
        except RuntimeError:
            codec_args = _infer_codec_args(dest.suffix or src.suffix)
            transcode_cmd: list[str] = [
                "ffmpeg",
                "-v",
                "error",
                "-y",
                "-i",
                str(part_b),
                "-i",
                str(part_a),
                "-filter_complex",
                "[0:a][1:a]concat=n=2:v=0:a=1[out]",
                "-map",
                "[out]",
                *codec_args,
                str(work_output),
            ]
            _run(transcode_cmd)

        if same_path:
            Path(work_output).replace(dest)

    return dest_resolved


def _parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Rotate an audio file so it loops seamlessly.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "examples:\n"
            "  python loopify_audio.py song.mp3 12.5\n"
            "  python loopify_audio.py in.wav 3.0 -o rotated.wav\n"
            "  python loopify_audio.py track.flac -2.0 --force"
        ),
    )
    parser.add_argument("input_path", help="path to source audio file")
    parser.add_argument("cut_seconds", type=float, help="seconds; negative = from end")
    parser.add_argument("-o", "--output", help="optional output path")
    parser.add_argument("--force", action="store_true", help="allow overwrite")
    return parser.parse_args(argv)


def main(argv: Iterable[str] | None = None) -> None:
    args = _parse_args(argv)
    result = loopify_audio(args.input_path, args.cut_seconds, args.output, args.force)
    print(result)


if __name__ == "__main__":
    main()
