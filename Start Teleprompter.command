#!/bin/sh
# Double-click to start the teleprompter. Leave this window open while you film; close it to stop.
cd "$(dirname "$0")" || exit 1
PORT="${TELEPROMPTER_PORT:-8791}"
STUDIO="http://localhost:$((PORT + 1))"

if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 isn't installed. Run: xcode-select --install   then double-click this again."
  read -r _; exit 1
fi
if lsof -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "The teleprompter is already running. Opening the studio."
  open "$STUDIO"; exit 0
fi
if [ ! -f certs/server.crt ]; then
  echo "First run: making the certificate your iPhone needs for the camera..."
  ./make-cert.sh || { echo "Couldn't make the certificate."; read -r _; exit 1; }
fi
command -v ffprobe >/dev/null 2>&1 || echo "Tip: install ffmpeg to have every take checked (length, picture, sound)."

(sleep 1.5; open "$STUDIO") &
echo "Teleprompter running. Studio: $STUDIO"
echo "Leave this window open while you film. Close it to stop."
exec python3 serve.py
