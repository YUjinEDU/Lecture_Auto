#!/bin/sh
# First start on an empty volume: seed the config and the built-in reference voices.
set -e
mkdir -p "$LECTURE_WEB_ROOT/data" "$LECTURE_WEB_ROOT/output"
[ -d "$LECTURE_WEB_ROOT/config" ] || cp -r /app/config "$LECTURE_WEB_ROOT/config"
[ -d "$LECTURE_WEB_ROOT/data/audio_ref" ] || cp -r /app/data/audio_ref "$LECTURE_WEB_ROOT/data/audio_ref"
cd "$LECTURE_WEB_ROOT"
exec "$@"
