#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p out/reference-cases/derived
docker exec minimax-h3 ffmpeg -v error -n \
  -i /out/reference-cases/assets/camera-motion.mp4 \
  -map 0:v:0 -c:v copy -an \
  /out/reference-cases/derived/camera-motion-silent.mp4
docker exec minimax-h3 ffmpeg -v error -n \
  -i /out/reference-cases/assets/greenscreen.mp4 \
  -t 9.8 -an -c:v libx264 -crf 18 -preset fast \
  /out/reference-cases/derived/greenscreen-9.8s.mp4
