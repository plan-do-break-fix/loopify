# Loopify

Loopify provides a small command line utility for rotating an audio file around a
cut point so the track can loop seamlessly. The script relies on `ffmpeg` and
`ffprobe` to split the file, swap the halves, and (if necessary) re-encode the
resulting audio stream.

## Quick start

1. Install [FFmpeg](https://ffmpeg.org/) so that the `ffmpeg` and `ffprobe`
   commands are available on your `PATH`.
2. Clone this repository and change into it:
   ```bash
   git clone https://github.com/<your-account>/loopify.git
   cd loopify
   ```
3. (Optional) Create and activate a virtual environment if you prefer to keep
   dependencies isolated:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```
4. Run the helper script with Python:
   ```bash
   python loopify_audio.py <input-file> <cut-seconds>
   ```
   The script writes the loopified audio file alongside the original input with
   `.loopified` inserted before the file extension.

## Usage

```
python loopify_audio.py INPUT_PATH CUT_SECONDS [-o OUTPUT] [--force]
```

- `INPUT_PATH`: path to the source audio file.
- `CUT_SECONDS`: timestamp that marks the rotation point. Provide a positive
  value to measure seconds from the beginning, or a negative value to measure
  from the end of the track.
- `-o, --output`: optional output path. Defaults to `<stem>.loopified<suffix>`
  next to the source file.
- `--force`: overwrite the destination if it already exists.

Example:

```bash
python loopify_audio.py song.mp3 12.5 -o intro-loop.mp3
```

If the supplied cut is exactly at the start (0 seconds) the tool simply copies
the input to the destination without modification. When concatenation via
stream copy is not possible, `ffmpeg` falls back to transcoding the audio using a
codec inferred from the destination file extension.
