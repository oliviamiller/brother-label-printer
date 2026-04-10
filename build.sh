#!/bin/sh
cd `dirname $0`

VENV_NAME="venv"
PYTHON="$VENV_NAME/bin/python"

if ! $PYTHON -m pip install pyinstaller -Uqq; then
    exit 1
fi

EXTRA_ARGS=""

# On macOS, compile the native IOKit USB helper and bundle it into the
# PyInstaller executable.  On Linux this is a no-op — the pyusb backend
# is used instead.
if [ "$(uname)" = "Darwin" ]; then
    USB_SRC="src/macos/usb_printer.c"
    USB_BIN="src/macos/usb_printer"
    if [ -f "$USB_SRC" ]; then
        echo "Compiling macOS USB helper..."
        if clang -O2 -o "$USB_BIN" "$USB_SRC" \
                -framework IOKit -framework CoreFoundation; then
            echo "USB helper compiled successfully."
            EXTRA_ARGS="--add-binary ${USB_BIN}:macos"
        else
            echo "ERROR: USB helper compilation failed." >&2
            exit 1
        fi
    else
        echo "ERROR: USB helper source not found at $USB_SRC" >&2
        exit 1
    fi
fi

$PYTHON -m PyInstaller --onefile --hidden-import="googleapiclient" $EXTRA_ARGS src/main.py
tar -czvf dist/archive.tar.gz meta.json ./dist/main first_run.sh
