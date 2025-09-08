#!/usr/bin/env bash
set -euo pipefail
IFS=$'\n\t'

# -------------------------
# CONFIG (environment-driven)
# -------------------------
: "${R2_ACCOUNT_ID:?missing R2_ACCOUNT_ID}"
: "${R2_BUCKET:?missing R2_BUCKET}"
: "${R2_ACCESS_KEY_ID:?missing R2_ACCESS_KEY_ID}"
: "${R2_SECRET_ACCESS_KEY:?missing R2_SECRET_ACCESS_KEY}"
: "${PLAYLIST_URLS:?missing PLAYLIST_URLS}"   # newline separated
: "${RSS_BASE_URL:=""}"  # optional override: if you host RSS on GitHub Pages, set to that base URL, otherwise leave blank to use R2 endpoint

R2_ENDPOINT="https://${R2_ACCOUNT_ID}.r2.cloudflarestorage.com"

WORKDIR="$(pwd)/downloads"
mkdir -p "$WORKDIR"
cd "$WORKDIR"

# setup aws profile for R2 (will be used by aws cli)
export AWS_ACCESS_KEY_ID="$R2_ACCESS_KEY_ID"
export AWS_SECRET_ACCESS_KEY="$R2_SECRET_ACCESS_KEY"
export AWS_DEFAULT_REGION="auto"

log(){ echo "[$(date --iso-8601=seconds)] $*"; }

# yt-dlp options (single command to download and write metadata)
YT_ARGS=(
  --no-overwrites
  --ignore-errors
  --continue
  --download-archive downloaded.txt
  --extract-audio
  --audio-format mp3
  --audio-quality 0
  --embed-thumbnail
  --add-metadata
  --write-info-json
  -o "%(playlist_title)s/%(playlist_index)03d - %(title).200B.%(ext)s"
)

# loop playlists
log "Starting download loop..."
echo "$PLAYLIST_URLS" | while IFS= read -r PLAYLIST_URL; do
  PLAYLIST_URL="${PLAYLIST_URL//[$'\r']}"   # strip CR
  [ -z "$PLAYLIST_URL" ] && continue

  log "Processing playlist: $PLAYLIST_URL"
  # run yt-dlp (it will skip already-downloaded items via downloaded.txt)
  yt-dlp "${YT_ARGS[@]}" "$PLAYLIST_URL" || log "yt-dlp returned nonzero (continuing)"

done

# After downloads - upload any new mp3 (and optionally thumbnails/info.json)
log "Uploading .mp3 and thumbnails to R2..."
find . -type f -name "*.mp3" -print0 | while IFS= read -r -d '' f; do
  # remote key: remove leading ./ or downloads/ if present
  key="${f#./}"
  # Ensure consistent path: no leading slash
  key="${key#downloads/}"
  log "Uploading $f => s3://$R2_BUCKET/$key"
  aws s3 cp "$f" "s3://$R2_BUCKET/$key" \
    --endpoint-url "$R2_ENDPOINT" --profile r2 --no-progress \
    --content-type "audio/mpeg"
done

# upload thumbnails (jpg/png) and info.json for reference
find . -type f \( -name "*.jpg" -o -name "*.png" -o -name "*.info.json" \) -print0 | while IFS= read -r -d '' f; do
  key="${f#./}"
  key="${key#downloads/}"
  log "Uploading meta $f => s3://$R2_BUCKET/$key"
  # set content-type appropriately
  if [[ "$f" == *.info.json ]]; then
    ct="application/json"
  elif [[ "$f" == *.png ]]; then
    ct="image/png"
  else
    ct="image/jpeg"
  fi
  aws s3 cp "$f" "s3://$R2_BUCKET/$key" --endpoint-url "$R2_ENDPOINT" --no-progress --content-type "$ct"
done

# generate RSS feeds (one per playlist folder)
log "Generating RSS feeds..."
# pass RSS_BASE_URL if you want feed to use GitHub Pages-hosted base URL instead of R2
python3 ../generate-rss.py --downloads-dir . --r2-account "$R2_ACCOUNT_ID" --r2-bucket "$R2_BUCKET" --rss-base "${RSS_BASE_URL:-}"

# Option A: commit the generated feeds back to gh-pages branch so GitHub Pages serves them
# Note: in Actions we have GITHUB_TOKEN by default; ensure checkout persisted credentials.
OUTDIR="../feeds"
mkdir -p "$OUTDIR"
mv feed-*.xml "$OUTDIR/" || true

# if this script is run in GitHub Actions, push feed files to gh-pages
if [ -n "${GITHUB_ACTIONS:-}" ]; then
  log "Pushing feeds to gh-pages branch..."
  # copy feeds into repo root ../ (repo checked out at $GITHUB_WORKSPACE)
  cp -f "$OUTDIR"/* "${GITHUB_WORKSPACE:-.}/" || true
  cd "${GITHUB_WORKSPACE:-.}"
  git checkout -B gh-pages
  git add -f feed-*.xml || true
  git commit -m "Update feeds $(date --iso-8601=seconds)" || true
  git push --force origin gh-pages || log "git push failed"
fi

log "Done."
