#!/bin/sh
# Kept so older instructions still work; setup.sh now handles the Jetson and the Pi.
BOARD="${BOARD:-jetson}" exec "$(dirname "$0")/setup.sh" "$@"
