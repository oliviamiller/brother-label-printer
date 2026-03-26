#!/bin/sh

if command -v apt-get >/dev/null; then
    SUDO=""
    if command -v sudo >/dev/null; then SUDO="sudo"; fi
    $SUDO apt-get install -qqy libusb-1.0-0 >/dev/null 2>&1
elif command -v dnf >/dev/null; then
    sudo dnf install -qy libusb1 >/dev/null 2>&1
else
    echo "Warning: could not install libusb automatically. Please install it manually."
fi
