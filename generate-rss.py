#!/usr/bin/env python3
"""
generate-rss.py
Scans a downloads directory created by yt-dlp:
  downloads/<playlist_title>/
    001 - Title.mp3
    001 - Title.info.json
    thumbnail.jpg

Generates feed-<slug>.xml for each playlist folder.
"""

import argparse, glob, json, os, subprocess, html, urllib.parse
from datetime import datetime
from email.utils import format_datetime

def ffprobe_duration(path):
    """Return duration in seconds (float) using ffprobe"""
    try:
        out = subprocess.check_output([
            "ffprobe","-v","error","-show_entries","format=duration",
            "-of","default=noprint_wrappers=1:nokey=1", path
        ], stderr=subprocess.DEVNULL)
        return float(out.decode().strip())
    except Exception:
        return None

def sec_to_itunes(d):
    if d is None:
        return ""
    d = int(round(d))
    h = d // 3600
    m = (d % 3600) // 60
    s = d % 60
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    else:
        return f"{m}:{s:02d}"

def slugify(text):
    s = text.lower()
    allowed = "abcdefghijklmnopqrstuvwxyz0123456789-"
    s = "".join(c if c.isalnum() else "-" for c in s)
    s = "-".join(filter(None, s.split("-")))
    return s[:50]

parser = argparse.ArgumentParser()
parser.add_argument("--downloads-dir", default="downloads")
parser.add_argument("--r2-account", required=True)
parser.add_argument("--r2-bucket", required=True)
parser.add_argument("--rss-base", default="")  # optional custom base url for enclosures (e.g., github pages)
args = parser.parse_args()

R2_BASE = args.rss_base or f"https://{args.r2_account}.r2.cloudflarestorage.com/{args.r2_bucket}"

if not os.path.isdir(args.downloads_dir):
    print("No downloads folder, exiting.")
    exit(0)

for playlist_dir in sorted(os.listdir(args.downloads_dir)):
    ppath = os.path.join(args.downloads_dir, playlist_dir)
    if not os.path.isdir(ppath):
        continue
    # collect episodes - use info.json ordering; fallback to file name sort
    info_files = sorted(glob.glob(os.path.join(ppath, "*.info.json")))
    items_xml = []
    for info in info_files:
        with open(info, "r", encoding="utf-8") as fh:
            j = json.load(fh)
        title = html.escape(j.get("title", "Untitled"))
        desc = html.escape(j.get("description", ""))
        upload_date = j.get("upload_date")  # YYYYMMDD
        if upload_date:
            try:
                pubdate = datetime.strptime(upload_date, "%Y%m%d")
            except Exception:
                pubdate = None
        else:
            mtime = os.path.getmtime(info)
            pubdate = datetime.utcfromtimestamp(mtime)
        pubdate_rfc = format_datetime(pubdate) if pubdate else ""
        mp3_path = info[:-9] + ".mp3"
        if not os.path.exists(mp3_path):
            # skip if audio missing
            continue
        filesize = os.path.getsize(mp3_path)
        duration_s = ffprobe_duration(mp3_path)
        itunes_duration = sec_to_itunes(duration_s)
        # build URL path relative to bucket root
        # example key: playlist_title/001 - Title.mp3 -> url encoded
        rel_key = os.path.relpath(mp3_path, args.downloads_dir)
        url = f"{R2_BASE}/{urllib.parse.quote(rel_key)}"
        # optional artwork
        # prefer thumbnail.jpg or thumbnail.png in same dir, else use j.get('thumbnail')
        artwork = None
        for ext in ("jpg","png","jpeg"):
            cand = os.path.join(ppath, f"thumbnail.{ext}")
            if os.path.exists(cand):
                artwork = f"{R2_BASE}/{urllib.parse.quote(os.path.relpath(cand,args.downloads_dir))}"
                break
        if not artwork and j.get("thumbnail"):
            artwork = j.get("thumbnail")
        # item xml
        items_xml.append(f"""
  <item>
    <title>{title}</title>
    <description>{desc}</description>
    <pubDate>{pubdate_rfc}</pubDate>
    <enclosure url="{url}" length="{filesize}" type="audio/mpeg" />
    <guid>{url}</guid>
    <itunes:duration>{itunes_duration}</itunes:duration>
  </item>
""")
    # channel metadata
    chan_title = html.escape(playlist_dir)
    chan_desc = f"Auto-generated podcast from YouTube playlist {playlist_dir}"
    slug = slugify(playlist_dir)
    rss = f'''<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd">
  <channel>
    <title>{chan_title}</title>
    <link>{R2_BASE}/{urllib.parse.quote(playlist_dir)}/</link>
    <description>{html.escape(chan_desc)}</description>
    <language>en-US</language>
    {''.join(items_xml)}
  </channel>
</rss>'''
    outname = f"feed-{slug}.xml"
    with open(outname, "w", encoding="utf-8") as f:
        f.write(rss)
    print(f"Wrote {outname} ({len(items_xml)} items)")
