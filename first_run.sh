#!/bin/sh
echo "Running brother-label-printer/first_run.sh"

# macOS: the native IOKit USB helper is bundled inside the PyInstaller
# executable — no libusb or runtime compilation needed.
if [ "$(uname)" = "Darwin" ]; then
    echo "macOS detected — using bundled native USB backend."
    exit 0
fi

# Linux: install libusb for the pyusb backend.
if command -v apt-get >/dev/null; then
    SUDO=""
    if command -v sudo >/dev/null; then SUDO="sudo"; fi
    $SUDO apt-get install -qqy libusb-1.0-0 >/dev/null 2>&1
elif command -v dnf >/dev/null; then
    sudo dnf install -qy libusb1 >/dev/null 2>&1
else
    echo "Warning: could not install libusb automatically. Please install it manually."
fi
