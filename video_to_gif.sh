#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
remove_bg=false

usage() {
  echo "Usage: $0 [-r] /path/video.mp4 [output.gif]" >&2
  echo "  -r  Remove background using Apple Vision (macOS 14+)" >&2
  exit 1
}

while getopts ":r" opt; do
  case $opt in
    r) remove_bg=true ;;
    *) usage ;;
  esac
done
shift $((OPTIND - 1))

if [[ $# -lt 1 || $# -gt 2 ]]; then
  usage
fi

if ! command -v ffmpeg >/dev/null 2>&1 || ! command -v ffprobe >/dev/null 2>&1; then
  echo "Error: ffmpeg and ffprobe must be installed and available in PATH." >&2
  exit 1
fi

if $remove_bg; then
  REMOVE_BG="$SCRIPT_DIR/scripts/remove_bg"
  if [[ ! -x "$REMOVE_BG" ]]; then
    echo "Compiling background removal tool..."
    swiftc -O -o "$REMOVE_BG" "$SCRIPT_DIR/scripts/remove_background.swift" \
      -framework Vision -framework CoreImage -framework AppKit
  fi
fi

input="$1"
output="${2:-${input%.*}.gif}"

if [[ ! -f "$input" ]]; then
  echo "Error: input file '$input' not found." >&2
  exit 1
fi

# Extract the exact frame rate in rational form (e.g. 30000/1001) to keep motion smooth.
fps=$(ffprobe -v 0 -of csv=p=0 -select_streams v:0 -show_entries stream=r_frame_rate "$input")
fps=${fps:-30}

if $remove_bg; then
  # Create a temp directory for frames and clean up on exit.
  frames_dir=$(mktemp -d "/tmp/ffmpeg_frames_XXXXXX")
  trap 'rm -rf "$frames_dir"' EXIT

  echo "Extracting frames..."
  ffmpeg -y -i "$input" -vf "fps=${fps}" "$frames_dir/frame_%05d.png"

  echo "Removing backgrounds (Apple Vision)..."
  total=$(ls "$frames_dir"/frame_*.png | wc -l | tr -d ' ')
  i=0
  for frame in "$frames_dir"/frame_*.png; do
    i=$((i + 1))
    "$REMOVE_BG" "$frame" "$frame" 2>/dev/null
    printf "\r  Processing frame %d/%d" "$i" "$total"
  done
  echo

  echo "Reassembling GIF..."
  palette_file="$frames_dir/palette.png"
  filter="scale=iw:-1:flags=lanczos"
  ffmpeg -y -framerate "$fps" -i "$frames_dir/frame_%05d.png" \
    -vf "${filter},palettegen=stats_mode=full:reserve_transparent=1" "$palette_file"
  ffmpeg -y -framerate "$fps" -i "$frames_dir/frame_%05d.png" -i "$palette_file" \
    -lavfi "${filter}[x];[x][1:v]paletteuse=dither=bayer:bayer_scale=5:diff_mode=rectangle" "$output"
else
  filter="fps=${fps},scale=iw:-1:flags=lanczos"
  palette_file=$(mktemp "/tmp/ffmpeg_palette_XXXXXX.png")
  trap 'rm -f "$palette_file"' EXIT

  ffmpeg -y -i "$input" -vf "${filter},palettegen=stats_mode=full" "$palette_file"
  ffmpeg -y -i "$input" -i "$palette_file" -lavfi "${filter}[x];[x][1:v]paletteuse=dither=bayer:bayer_scale=5:diff_mode=rectangle" "$output"
fi

echo "Created: $output"
