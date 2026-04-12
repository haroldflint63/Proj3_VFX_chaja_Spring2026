import argparse
import subprocess
import os
import re
import sys
import json
import glob
import struct
import zlib
from datetime import datetime

VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv", ".mxf", ".m4v", ".wmv", ".png", ".jpg", ".jpeg"}

HAS_DRAWTEXT = False


def check_ffmpeg():
    global HAS_DRAWTEXT
    for tool in ("ffmpeg", "ffprobe"):
        try:
            result = subprocess.run([tool, "-version"], capture_output=True, text=True)
            if result.returncode != 0:
                print(f"[ERROR] '{tool}' not working. Run: brew install ffmpeg")
                sys.exit(1)
        except FileNotFoundError:
            print(f"[ERROR] '{tool}' not found. Run: brew install ffmpeg")
            sys.exit(1)

    result = subprocess.run(["ffmpeg", "-filters"], capture_output=True, text=True)
    HAS_DRAWTEXT = "drawtext" in result.stdout
    if not HAS_DRAWTEXT:
        print("[WARN] drawtext filter not available. Using drawbox fallback.")
        print("[WARN] To fix: brew tap homebrew-ffmpeg/ffmpeg && brew install homebrew-ffmpeg/ffmpeg/ffmpeg --with-freetype")


# ─────────────────────────────────────────────
# NAMING / VERSIONING
# ─────────────────────────────────────────────
def otag(owner):
    return owner.replace(" ", "_")


def clean_base_name(path_or_name, owner):
    name = os.path.splitext(os.path.basename(path_or_name))[0]
    return re.sub(
        rf'_VFX_{re.escape(otag(owner))}_v\d+.*$',
        '',
        name,
        flags=re.IGNORECASE
    )


def extract_version_number(path_or_name):
    match = re.search(r'_v(\d+)', os.path.basename(path_or_name), re.IGNORECASE)
    return int(match.group(1)) if match else 0


def iter_versioned_files(input_path, owner, same_ext_only=False):
    dir_name = os.path.dirname(os.path.abspath(input_path))
    base = clean_base_name(input_path, owner)
    tag = otag(owner)
    src_ext = os.path.splitext(input_path)[1].lower()

    pattern = os.path.join(dir_name, f"{base}_VFX_{tag}_v*")
    for path in glob.glob(pattern):
        if not os.path.isfile(path):
            continue
        name = os.path.basename(path)
        if not re.match(rf"^{re.escape(base)}_VFX_{re.escape(tag)}_v\d+", name, re.IGNORECASE):
            continue
        if same_ext_only and os.path.splitext(path)[1].lower() != src_ext:
            continue
        yield path


def get_next_version(input_path, owner, suffix="", ext=None):
    max_ver = 0
    for existing in iter_versioned_files(input_path, owner, same_ext_only=False):
        max_ver = max(max_ver, extract_version_number(existing))
    return f"v{max_ver + 1:02d}"


def build_output_name(input_path, owner, suffix="", ext=None):
    src_ext = os.path.splitext(input_path)[1]
    output_ext = ext if ext else src_ext
    version = get_next_version(input_path, owner, suffix=suffix, ext=output_ext)
    base = clean_base_name(input_path, owner)
    tag = otag(owner)
    output_dir = os.path.dirname(os.path.abspath(input_path))
    return os.path.join(output_dir, f"{base}_VFX_{tag}_{version}{suffix}{output_ext}")


def resolve_latest_any(input_path, owner):
    matches = list(iter_versioned_files(input_path, owner, same_ext_only=True))
    if matches:
        return max(matches, key=lambda p: (extract_version_number(p), os.path.getmtime(p)))
    return None


def resolve_latest_version(input_path, owner, suffix="_wm"):
    matches = []
    for path in iter_versioned_files(input_path, owner, same_ext_only=True):
        if suffix in os.path.basename(path):
            matches.append(path)
    if matches:
        return max(matches, key=lambda p: (extract_version_number(p), os.path.getmtime(p)))
    return None


def get_latest_outputs(files, owner, suffix="", ext=None):
    latest = []
    for fp in files:
        matches = []
        for path in iter_versioned_files(fp, owner, same_ext_only=False):
            if suffix and suffix not in os.path.basename(path):
                continue
            if ext and os.path.splitext(path)[1].lower() != ext.lower():
                continue
            matches.append(path)
        if matches:
            latest.append(max(matches, key=lambda p: (extract_version_number(p), os.path.getmtime(p))))
    return latest


# ─────────────────────────────────────────────
# FILTER BUILDERS
# ─────────────────────────────────────────────
def build_watermark_filter(owner):
    wm_text = owner.replace("'", "").replace(":", "").replace(",", "")
    if HAS_DRAWTEXT:
        return (
            f"drawtext=text='{wm_text}':"
            "fontcolor=white:fontsize=36:"
            "box=1:boxcolor=black@0.5:boxborderw=5:"
            "x=w-tw-10:y=10"
        )
    else:
        return (
            "drawbox=x=iw-220:y=5:w=215:h=45:color=black@0.6:t=fill,"
            "drawbox=x=iw-220:y=5:w=215:h=45:color=white@0.9:t=3"
        )


def build_confidential_filter(owner):
    wm_text = owner.replace("'", "").replace(":", "").replace(",", "")
    if HAS_DRAWTEXT:
        return (
            f"drawtext=text='{wm_text}':"
            "fontcolor=white:fontsize=36:"
            "box=1:boxcolor=black@0.5:boxborderw=5:"
            "x=w-tw-10:y=10,"
            "drawbox=x=0:y=0:w=iw:h=ih:color=red@0.3:t=20,"
            "drawtext=text='CONFIDENTIAL':"
            "fontcolor=red@0.7:fontsize=80:"
            "x=(w-text_w)/2:y=(h-text_h)/2-60,"
            "drawtext=text='CONFIDENTIAL':"
            "fontcolor=red@0.7:fontsize=80:"
            "x=(w-text_w)/2:y=(h-text_h)/2+60,"
            "drawtext=text='CONFIDENTIAL':"
            "fontcolor=white:fontsize=100:"
            "box=1:boxcolor=red@0.6:boxborderw=25:"
            "x=(w-text_w)/2:y=(h-text_h)/2"
        )
    else:
        return (
            "drawbox=x=0:y=0:w=iw:h=ih:color=red@0.5:t=25,"
            "drawbox=x=iw-220:y=5:w=215:h=45:color=black@0.6:t=fill,"
            "drawbox=x=iw-220:y=5:w=215:h=45:color=white@0.9:t=3,"
            "drawbox=x=iw/2-250:y=ih/2-50:w=500:h=100:color=red@0.7:t=fill,"
            "drawbox=x=iw/2-250:y=ih/2-50:w=500:h=100:color=white@0.9:t=4,"
            "drawbox=x=0:y=ih/2-120:w=iw:h=20:color=red@0.5:t=fill,"
            "drawbox=x=0:y=ih/2+100:w=iw:h=20:color=red@0.5:t=fill,"
            "drawbox=x=20:y=20:w=80:h=80:color=red@0.6:t=fill,"
            "drawbox=x=iw-100:y=20:w=80:h=80:color=red@0.6:t=fill,"
            "drawbox=x=20:y=ih-100:w=80:h=80:color=red@0.6:t=fill,"
            "drawbox=x=iw-100:y=ih-100:w=80:h=80:color=red@0.6:t=fill"
        )


# ─────────────────────────────────────────────
# WATERMARK (WM)
# ─────────────────────────────────────────────
def watermark(input_path, owner):
    if not os.path.isfile(input_path):
        print(f"[ERROR] File not found: {input_path}")
        return None

    output_path = build_output_name(input_path, owner, suffix="_wm")
    cmd = [
        "ffmpeg", "-y", "-i", input_path,
        "-vf", build_watermark_filter(owner),
        output_path
    ]

    print(f"[WM]  {os.path.basename(input_path)} -> {os.path.basename(output_path)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"[ERROR] Watermark failed:\n{result.stderr}")
        return None

    print(f"[WM]  Done: {os.path.basename(output_path)}")
    return output_path


# ─────────────────────────────────────────────
# GIF CREATION (GC) — 1 second = 24 repeated frames
# ─────────────────────────────────────────────
def create_gif(input_path, owner, fps=24):
    if not os.path.isfile(input_path):
        print(f"[ERROR] File not found: {input_path}")
        return None

    output_path = build_output_name(input_path, owner, suffix="_gif", ext=".gif")
    palette_path = output_path.replace(".gif", "_palette.png")

    palette_cmd = [
        "ffmpeg", "-y",
        "-loop", "1", "-t", "1", "-i", input_path,
        "-vf", f"fps={fps},scale=320:-1:flags=lanczos,palettegen",
        palette_path
    ]
    gif_cmd = [
        "ffmpeg", "-y",
        "-loop", "1", "-t", "1", "-i", input_path,
        "-i", palette_path,
        "-filter_complex", f"fps={fps},scale=320:-1:flags=lanczos[x];[x][1:v]paletteuse",
        output_path
    ]

    print(f"[GC]  Creating GIF (1 sec / {fps} fps / {fps} repeated frames)")
    print(f"      {os.path.basename(input_path)} -> {os.path.basename(output_path)}")
    for cmd in (palette_cmd, gif_cmd):
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"[ERROR] GIF failed:\n{result.stderr}")
            if os.path.exists(palette_path):
                os.remove(palette_path)
            return None

    if os.path.exists(palette_path):
        os.remove(palette_path)

    print(f"[GC]  Done: {os.path.basename(output_path)}")
    return output_path


# ─────────────────────────────────────────────
# THUMBNAIL (TC) — 320x180
# ─────────────────────────────────────────────
def create_thumbnail(input_path, owner):
    if not os.path.isfile(input_path):
        print(f"[ERROR] File not found: {input_path}")
        return None

    output_path = build_output_name(input_path, owner, suffix="_thumb", ext=".jpg")
    cmd = [
        "ffmpeg", "-y", "-i", input_path,
        "-vf", "scale=320:180",
        output_path
    ]

    print(f"[TC]  {os.path.basename(input_path)} -> {os.path.basename(output_path)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"[ERROR] Thumbnail failed:\n{result.stderr}")
        return None

    print(f"[TC]  Done: {os.path.basename(output_path)}")
    return output_path


# ─────────────────────────────────────────────
# FLYIN / CONFIDENTIAL
# ─────────────────────────────────────────────
def apply_confidential(input_path, owner):
    if not os.path.isfile(input_path):
        print(f"[ERROR] File not found: {input_path}")
        return None

    output_path = build_output_name(input_path, owner, suffix="_confidential")
    cmd = [
        "ffmpeg", "-y", "-i", input_path,
        "-vf", build_confidential_filter(owner),
        output_path
    ]

    print(f"[FLYIN] {os.path.basename(input_path)} -> {os.path.basename(output_path)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"[ERROR] Confidential overlay failed:\n{result.stderr}")
        return None

    print(f"[FLYIN] Done: {os.path.basename(output_path)}")
    return output_path


# ─────────────────────────────────────────────
# METADATA EXPORT (ME)
# ─────────────────────────────────────────────
def probe_file(filepath):
    cmd = [
        "ffprobe", "-v", "quiet",
        "-print_format", "json",
        "-show_format", "-show_streams",
        filepath
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        return {"error": result.stderr.strip()}
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return {"error": "Could not parse ffprobe output"}


def export_metadata(files, owner, output_txt=None, gif_paths=None, gif_files=None):
    if not output_txt:
        output_txt = f"metadata_VFX_{otag(owner)}_{datetime.now():%Y%m%d_%H%M%S}.txt"

    gif_paths = gif_paths or []
    gif_files = gif_files or []

    lines = []
    lines.append("=" * 60)
    lines.append("METADATA EXPORT")
    lines.append(f"Owner  : {owner}")
    lines.append(f"Created: {datetime.now():%Y-%m-%d %H:%M:%S}")
    lines.append("=" * 60)

    for fp in files:
        lines.append(f"\n{'-' * 60}")
        lines.append(f"FILE: {os.path.basename(fp)}")
        lines.append(f"PATH: {fp}")
        lines.append(f"{'-' * 60}")

        if not os.path.isfile(fp):
            lines.append("  [WARNING] File not found - skipping.")
            continue

        info = probe_file(fp)
        if "error" in info:
            lines.append(f"  [ERROR] {info['error']}")
            continue

        fmt = info.get("format", {})
        lines.append(f"  Format     : {fmt.get('format_long_name', 'N/A')}")
        lines.append(f"  Duration   : {fmt.get('duration', 'N/A')} s")
        lines.append(f"  File size  : {fmt.get('size', 'N/A')} bytes")
        lines.append(f"  Bit rate   : {fmt.get('bit_rate', 'N/A')} bps")

        for i, stream in enumerate(info.get("streams", [])):
            lines.append(f"\n  Stream #{i}")
            lines.append(f"    Type     : {stream.get('codec_type', 'N/A')}")
            lines.append(f"    Codec    : {stream.get('codec_long_name', 'N/A')}")
            if stream.get("codec_type") == "video":
                lines.append(f"    Size     : {stream.get('width')}x{stream.get('height')}")
                lines.append(f"    FPS      : {stream.get('r_frame_rate', 'N/A')}")
                lines.append(f"    Pix fmt  : {stream.get('pix_fmt', 'N/A')}")
            if stream.get("codec_type") == "audio":
                lines.append(f"    Sample   : {stream.get('sample_rate', 'N/A')} Hz")
                lines.append(f"    Channels : {stream.get('channels', 'N/A')}")

        tags = fmt.get("tags", {})
        if tags:
            lines.append("\n  Tags:")
            for k, v in tags.items():
                lines.append(f"    {k}: {v}")

    if gif_paths:
        lines.append(f"\n{'=' * 60}")
        lines.append("GIF METADATA")
        lines.append(f"{'=' * 60}")

        for gif_path in gif_paths:
            lines.append(f"\nGIF File : {os.path.basename(gif_path)}")
            lines.append("Duration : 1 second")
            lines.append("FPS      : 24")
            lines.append("Frames   : 24 handles (repeated frames)")

            if os.path.isfile(gif_path):
                info = probe_file(gif_path)
                if "error" not in info:
                    fmt = info.get("format", {})
                    lines.append(f"File size: {fmt.get('size', 'N/A')} bytes")
                    for i, stream in enumerate(info.get("streams", [])):
                        lines.append(
                            f"Stream #{i} — codec: {stream.get('codec_name', 'N/A')} "
                            f"res: {stream.get('width')}x{stream.get('height')}"
                        )
                else:
                    lines.append(f"  [ERROR] {info['error']}")
            else:
                lines.append("  [WARNING] GIF file not found.")

        if gif_files:
            lines.append(f"\n{'-' * 60}")
            lines.append("FILES INCLUDED IN GIF RUN (processed names):")
            lines.append(f"{'-' * 60}")
            for fp in gif_files:
                lines.append(f"  * {os.path.basename(fp)}")

    lines.append("\n" + "=" * 60)
    lines.append("END OF REPORT")
    lines.append("=" * 60)

    with open(output_txt, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))

    print(f"[ME]  Metadata saved to: {output_txt}")
    return output_txt


# ─────────────────────────────────────────────
# EC: RAW PIXEL MANIPULATION (NO FFMPEG)
# 4 tools: grayscale, brightness, invert, sepia
# ─────────────────────────────────────────────
def read_png_raw(filepath):
    with open(filepath, "rb") as f:
        sig = f.read(8)
        if sig != b'\x89PNG\r\n\x1a\n':
            raise ValueError("Not a valid PNG file")

        chunks = []
        while True:
            raw = f.read(8)
            if len(raw) < 8:
                break
            length, ctype = struct.unpack(">I4s", raw)
            data = f.read(length)
            f.read(4)
            chunks.append((ctype, data))

        ihdr_data = None
        idat_parts = []
        for ctype, data in chunks:
            if ctype == b'IHDR':
                ihdr_data = data
            elif ctype == b'IDAT':
                idat_parts.append(data)

        if ihdr_data is None:
            raise ValueError("No IHDR chunk found")

        width, height, bit_depth, color_type = struct.unpack(">IIBB", ihdr_data[:10])

        if bit_depth != 8:
            raise ValueError(f"Only 8-bit PNG supported, got {bit_depth}")

        if color_type == 2:
            channels = 3
        elif color_type == 6:
            channels = 4
        else:
            raise ValueError(f"Color type {color_type} not supported")

        raw_data = zlib.decompress(b''.join(idat_parts))

        stride = 1 + width * channels
        rows = []
        for y in range(height):
            row_start = y * stride
            filter_byte = raw_data[row_start]
            row_bytes = bytearray(raw_data[row_start + 1: row_start + stride])

            if filter_byte == 1:
                for i in range(channels, len(row_bytes)):
                    row_bytes[i] = (row_bytes[i] + row_bytes[i - channels]) & 0xFF
            elif filter_byte == 2 and y > 0:
                prev = rows[y - 1]
                for i in range(len(row_bytes)):
                    row_bytes[i] = (row_bytes[i] + prev[i]) & 0xFF
            elif filter_byte == 3:
                prev = rows[y - 1] if y > 0 else bytearray(len(row_bytes))
                for i in range(len(row_bytes)):
                    a = row_bytes[i - channels] if i >= channels else 0
                    b = prev[i]
                    row_bytes[i] = (row_bytes[i] + (a + b) // 2) & 0xFF
            elif filter_byte == 4:
                prev = rows[y - 1] if y > 0 else bytearray(len(row_bytes))
                for i in range(len(row_bytes)):
                    a = row_bytes[i - channels] if i >= channels else 0
                    b = prev[i]
                    c = prev[i - channels] if (y > 0 and i >= channels) else 0
                    p = a + b - c
                    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                    if pa <= pb and pa <= pc:
                        pr = a
                    elif pb <= pc:
                        pr = b
                    else:
                        pr = c
                    row_bytes[i] = (row_bytes[i] + pr) & 0xFF

            rows.append(row_bytes)

        return width, height, channels, rows


def write_png_raw(filepath, width, height, channels, rows):
    color_type = 6 if channels == 4 else 2

    def make_chunk(ctype, data):
        crc = zlib.crc32(ctype + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + ctype + data + struct.pack(">I", crc)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, color_type, 0, 0, 0)

    raw_rows = bytearray()
    for row in rows:
        raw_rows.append(0)
        raw_rows.extend(row)

    compressed = zlib.compress(bytes(raw_rows), 9)

    with open(filepath, "wb") as f:
        f.write(b'\x89PNG\r\n\x1a\n')
        f.write(make_chunk(b'IHDR', ihdr))
        f.write(make_chunk(b'IDAT', compressed))
        f.write(make_chunk(b'IEND', b''))


def ec_grayscale(input_path, owner):
    if not os.path.isfile(input_path):
        return None
    output_path = build_output_name(input_path, owner, suffix="_grayscale")
    try:
        width, height, channels, rows = read_png_raw(input_path)
    except Exception as e:
        print(f"[ERROR] Could not read PNG: {e}")
        return None

    new_rows = []
    for row in rows:
        new_row = bytearray(len(row))
        for x in range(width):
            idx = x * channels
            r, g, b = row[idx], row[idx + 1], row[idx + 2]
            gray = min(255, max(0, int(0.299 * r + 0.587 * g + 0.114 * b)))
            new_row[idx] = gray
            new_row[idx + 1] = gray
            new_row[idx + 2] = gray
            if channels == 4:
                new_row[idx + 3] = row[idx + 3]
        new_rows.append(new_row)

    write_png_raw(output_path, width, height, channels, new_rows)
    print(f"[EC]  Grayscale (no ffmpeg): {os.path.basename(output_path)}")
    return output_path


def ec_bright(input_path, owner, factor=1.8):
    if not os.path.isfile(input_path):
        return None
    output_path = build_output_name(input_path, owner, suffix="_bright")
    try:
        width, height, channels, rows = read_png_raw(input_path)
    except Exception as e:
        print(f"[ERROR] Could not read PNG: {e}")
        return None

    new_rows = []
    for row in rows:
        new_row = bytearray(len(row))
        for x in range(width):
            idx = x * channels
            for c in range(3):
                new_row[idx + c] = min(255, int(row[idx + c] * factor))
            if channels == 4:
                new_row[idx + 3] = row[idx + 3]
        new_rows.append(new_row)

    write_png_raw(output_path, width, height, channels, new_rows)
    print(f"[EC]  Brightness x{factor} (no ffmpeg): {os.path.basename(output_path)}")
    return output_path


def ec_invert(input_path, owner):
    if not os.path.isfile(input_path):
        return None
    output_path = build_output_name(input_path, owner, suffix="_invert")
    try:
        width, height, channels, rows = read_png_raw(input_path)
    except Exception as e:
        print(f"[ERROR] Could not read PNG: {e}")
        return None

    new_rows = []
    for row in rows:
        new_row = bytearray(len(row))
        for x in range(width):
            idx = x * channels
            for c in range(3):
                new_row[idx + c] = 255 - row[idx + c]
            if channels == 4:
                new_row[idx + 3] = row[idx + 3]
        new_rows.append(new_row)

    write_png_raw(output_path, width, height, channels, new_rows)
    print(f"[EC]  Invert (no ffmpeg): {os.path.basename(output_path)}")
    return output_path


def ec_sepia(input_path, owner):
    if not os.path.isfile(input_path):
        return None
    output_path = build_output_name(input_path, owner, suffix="_sepia")
    try:
        width, height, channels, rows = read_png_raw(input_path)
    except Exception as e:
        print(f"[ERROR] Could not read PNG: {e}")
        return None

    new_rows = []
    for row in rows:
        new_row = bytearray(len(row))
        for x in range(width):
            idx = x * channels
            r, g, b = row[idx], row[idx + 1], row[idx + 2]
            new_row[idx] = min(255, int(0.393 * r + 0.769 * g + 0.189 * b))
            new_row[idx + 1] = min(255, int(0.349 * r + 0.686 * g + 0.168 * b))
            new_row[idx + 2] = min(255, int(0.272 * r + 0.534 * g + 0.131 * b))
            if channels == 4:
                new_row[idx + 3] = row[idx + 3]
        new_rows.append(new_row)

    write_png_raw(output_path, width, height, channels, new_rows)
    print(f"[EC]  Sepia (no ffmpeg): {os.path.basename(output_path)}")
    return output_path


# ─────────────────────────────────────────────
# FILE COLLECTOR
# ─────────────────────────────────────────────
def collect_video_files(paths, matches=None):
    collected = []
    match_list = [m.lower() for m in (matches or [])]

    def name_matches(fname):
        if not match_list:
            return True
        low = fname.lower()
        return any(token in low for token in match_list)

    for p in paths:
        if os.path.isdir(p):
            for fname in sorted(os.listdir(p)):
                full = os.path.join(p, fname)
                ext = os.path.splitext(fname)[1].lower()
                if not os.path.isfile(full):
                    continue
                if ext not in VIDEO_EXTS:
                    continue
                if "_VFX_" in fname:
                    continue
                if not name_matches(fname):
                    continue
                collected.append(full)
        elif os.path.isfile(p):
            fname = os.path.basename(p)
            if os.path.splitext(p)[1].lower() not in VIDEO_EXTS:
                continue
            if not name_matches(fname):
                continue
            collected.append(p)
        else:
            print(f"[WARN] Path not found, skipping: {p}")

    return collected


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        prog="media_processor",
        description="FFmpeg media processing pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
COMMANDS

  (1) python3 media_processor.py -d . --match avengers -n "Owner Name" -wm
  (2) python3 media_processor.py -d . --match infinity -n "Owner Name" -wm -tc
  (3) python3 media_processor.py -d . --match drdoom infinity avengers -n "Owner Name" -wm -gc
  (4) python3 media_processor.py -d . --match drdoom infinity avengers -n "Owner Name" -me -o metadata_report.txt
  (5) python3 media_processor.py -d . -n "Owner Name" -confidential
  (EC) python3 media_processor.py -d . -n "Owner Name" -ec
        """
    )

    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument("-i", "--input", nargs="+", metavar="FILE", help="Input file(s)")
    input_group.add_argument("-d", "--directory", metavar="DIR", help="Input directory")

    parser.add_argument("-n", "--name", required=True, help="Owner name")
    parser.add_argument("--match", nargs="+", metavar="TEXT", help="Filter filenames")
    parser.add_argument("-wm", "--wm", action="store_true", help="Watermark")
    parser.add_argument("-gc", "--gc", action="store_true", help="GIF 1sec 24fps")
    parser.add_argument("-tc", "--tc", action="store_true", help="Thumbnail 320x180")
    parser.add_argument("-me", "--me", action="store_true", help="Metadata export")
    parser.add_argument("-confidential", "--confidential", action="store_true", help="Confidential flyin")
    parser.add_argument("-ec", "--ec", action="store_true", help="EC color tools (no ffmpeg)")
    parser.add_argument("-all", "--all", action="store_true", help="Run all")
    parser.add_argument("-o", "--output-txt", metavar="TXT", default=None, help="Metadata output path")

    if len(sys.argv) == 1:
        parser.print_help()
        sys.exit(0)

    args = parser.parse_args()

    do_wm   = args.wm or args.all
    do_gc   = args.gc or args.all
    do_tc   = args.tc or args.all
    do_me   = args.me or args.all
    do_conf = args.confidential or args.all
    do_ec   = args.ec

    if not any([do_wm, do_gc, do_tc, do_me, do_conf, do_ec]):
        parser.error("Specify at least one operation")

    check_ffmpeg()

    raw_paths = args.input if args.input else [args.directory]
    files = collect_video_files(raw_paths, matches=args.match)

    if not files:
        print("[ERROR] No valid files found.")
        sys.exit(1)

    print(f"\nProcessing {len(files)} file(s) for: {args.name}")
    if not HAS_DRAWTEXT:
        print("[INFO] Using drawbox fallback (no drawtext).")
    print()

    processed_files = []
    gif_inputs  = []
    gif_outputs = []

    for fp in files:
        current = fp
        print(f"\n{'-' * 50}")
        print(f"Input: {os.path.basename(fp)}")

        if do_wm:
            result = watermark(current, args.name)
            if result:
                current = result
                processed_files.append(result)

        if do_tc:
            result = create_thumbnail(current, args.name)
            if result:
                processed_files.append(result)

        if do_gc:
            gif_inputs.append(current)
            result = create_gif(current, args.name)
            if result:
                gif_outputs.append(result)
                processed_files.append(result)

        if do_conf:
            latest = current
            if not do_wm:
                prev = resolve_latest_any(fp, args.name)
                if prev:
                    latest = prev
                    print(f"[FLYIN] Using latest version: {os.path.basename(latest)}")
                else:
                    result = watermark(current, args.name)
                    if result:
                        latest = result
                        processed_files.append(result)

            result = apply_confidential(latest, args.name)
            if result:
                processed_files.append(result)

        if do_ec and os.path.splitext(fp)[1].lower() == ".png":
            for ec_func in (ec_grayscale, ec_bright, ec_invert, ec_sepia):
                result = ec_func(fp, args.name)
                if result:
                    processed_files.append(result)

    if do_me:
        if not gif_outputs:
            gif_outputs = get_latest_outputs(files, args.name, suffix="_gif", ext=".gif")
        if not gif_inputs:
            gif_inputs = get_latest_outputs(files, args.name, suffix="_wm")
            if not gif_inputs:
                gif_inputs = files

        all_for_report = list(dict.fromkeys(files + processed_files + gif_outputs))
        export_metadata(
            files=all_for_report,
            owner=args.name,
            output_txt=args.output_txt,
            gif_paths=gif_outputs,
            gif_files=gif_inputs
        )

    print("\n" + "=" * 50)
    print("All tasks complete.")
    print("=" * 50)


if __name__ == "__main__":
    main()

