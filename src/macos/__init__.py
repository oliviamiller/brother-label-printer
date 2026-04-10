"""
macOS-native USB backend for Brother QL printers.
Replaces pyusb/libusb with IOKit (ctypes) for USB I/O and
system_profiler for device discovery. Zero external dependencies
beyond Python's standard library.
"""

import sys

IS_MACOS = sys.platform == "darwin"
