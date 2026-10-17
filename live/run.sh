#!/bin/zsh
# Start the live demo from any terminal. It launches the small wrapper app
# (live/CropSCOUT Live.app) so macOS shows a camera permission prompt for
# "CropSCOUT Live", and streams the demo's output back here. Ctrl-C stops both.
#   live/run.sh                      # default camera
#   live/run.sh --camera 1           # any live_detect.py option works
cd "$(dirname "$0")/.." || exit 1
# The ad-hoc signature is not in git; macOS wants one for a stable camera-permission identity.
codesign --verify "live/CropSCOUT Live.app" 2>/dev/null || codesign --force --sign - "live/CropSCOUT Live.app"
: > live/demo.log
cleanup() { pkill -f "live/live_detect.py" 2>/dev/null; kill $TAIL_PID 2>/dev/null; }
trap cleanup INT TERM
open -W -n "live/CropSCOUT Live.app" --args "$@" &
OPEN_PID=$!
tail -n +1 -f live/demo.log &
TAIL_PID=$!
wait $OPEN_PID
kill $TAIL_PID 2>/dev/null
