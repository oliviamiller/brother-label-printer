"""
macOS-native send helper.

Mirrors the contract of ``brother_ql.backends.helpers.send()`` but uses a
compiled IOKit C helper for USB bulk I/O instead of pyusb / libusb.
Falls back to CUPS ``lpr -l`` if the helper is unavailable or the device is
exclusively claimed by another driver.
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
import sys
import tempfile
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_USB_ID_RE = re.compile(
    r"usb://0x([0-9a-fA-F]{4}):0x([0-9a-fA-F]{4})(?:[/_](.+))?", re.I
)

_HERE = os.path.dirname(os.path.abspath(__file__))


def _parse_usb_identifier(identifier: str):
    """Parse ``usb://0x04f9:0x2015/SERIAL`` into (vid, pid, serial|None)."""
    m = _USB_ID_RE.match(identifier)
    if not m:
        raise ValueError(f"Cannot parse USB identifier: {identifier}")
    return int(m.group(1), 16), int(m.group(2), 16), m.group(3)


def _try_interpret_response(data: bytes) -> Optional[Dict[str, Any]]:
    """Wrapper around brother_ql's status interpreter."""
    try:
        from brother_ql.reader import interpret_response
        return interpret_response(data)
    except Exception:
        return None


def _find_helper_binary() -> Optional[str]:
    """Search for the compiled usb_printer binary in known locations."""
    candidates = []

    # 1. PyInstaller bundle extraction directory
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(os.path.join(meipass, "macos", "usb_printer"))

    # 2. Next to this Python source file (source-tree development)
    candidates.append(os.path.join(_HERE, "usb_printer"))

    for path in candidates:
        if os.path.isfile(path) and os.access(path, os.X_OK):
            logger.debug("Found USB helper at %s", path)
            return path

    return None


def _ensure_helper() -> Optional[str]:
    """Return path to the usb_printer helper, compiling on-the-fly if needed."""
    found = _find_helper_binary()
    if found:
        return found

    # Try to compile from source next to this file
    src = os.path.join(_HERE, "usb_printer.c")
    out = os.path.join(_HERE, "usb_printer")
    if not os.path.isfile(src):
        logger.warning(
            "USB helper binary not found and source not available "
            "(searched: next to __file__, sys._MEIPASS)"
        )
        return None

    logger.info("Compiling USB helper from %s ...", src)
    try:
        subprocess.run(
            [
                "clang", "-O2", "-o", out, src,
                "-framework", "IOKit", "-framework", "CoreFoundation",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        os.chmod(out, 0o755)
        logger.info("USB helper compiled successfully")
        return out
    except Exception as e:
        logger.warning("Failed to compile USB helper: %s", e)
        return None


def send(
    instructions: bytes,
    printer_identifier: str,
    *,
    blocking: bool = True,
    cups_printer_name: Optional[str] = None,
) -> Dict[str, Any]:
    """Send raster instructions to a Brother QL printer on macOS.

    Tries the native IOKit C helper first.  If that fails falls back to CUPS.

    Returns a status dict compatible with ``brother_ql.backends.helpers.send()``.
    """
    status: Dict[str, Any] = {
        "instructions_sent": False,
        "outcome": "unknown",
        "printer_state": None,
        "did_print": False,
        "ready_for_next_job": False,
        "backend": "none",
    }

    vid, pid, serial = _parse_usb_identifier(printer_identifier)

    # --- attempt 1: compiled IOKit C helper ---
    helper = _ensure_helper()
    if helper:
        try:
            _send_via_helper(helper, vid, pid, serial, instructions, status, blocking)
            return status
        except Exception as e:
            logger.warning(
                "USB helper failed (%s: %s), trying CUPS fallback",
                type(e).__name__, e,
            )

    # --- attempt 2: CUPS lpr ---
    try:
        from .cups_backend import CUPSPrinterBackend

        logger.info("Sending %d bytes via CUPS", len(instructions))
        backend = CUPSPrinterBackend(cups_printer_name)
        backend.write(instructions)
        status["instructions_sent"] = True
        status["outcome"] = "printed"
        status["backend"] = "cups"
        status["did_print"] = True
        status["ready_for_next_job"] = True
        return status

    except Exception as e:
        logger.error("CUPS backend also failed: %s: %s", type(e).__name__, e)
        status["outcome"] = "error"
        raise RuntimeError(
            f"All macOS backends failed for {printer_identifier}"
        ) from e


def _send_via_helper(
    helper: str,
    vid: int,
    pid: int,
    serial: Optional[str],
    instructions: bytes,
    status: Dict[str, Any],
    blocking: bool,
) -> None:
    """Write instructions to a temp file, invoke the C helper, parse status."""
    fd, data_path = tempfile.mkstemp(prefix="brother_ql_", suffix=".bin")
    try:
        os.write(fd, instructions)
        os.close(fd)

        cmd = [
            helper, "send",
            f"0x{vid:04x}", f"0x{pid:04x}",
            data_path,
        ]
        if serial:
            cmd.append(serial)

        logger.info("Running: %s", " ".join(cmd))
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
        )

        logger.debug("helper stdout:\n%s", result.stdout)
        logger.debug("helper stderr:\n%s", result.stderr)

        if result.returncode != 0:
            stderr = result.stderr.strip()
            raise RuntimeError(f"usb_printer exited {result.returncode}: {stderr}")

        status["instructions_sent"] = True
        status["outcome"] = "sent"
        status["backend"] = "iokit_native"

        if blocking:
            _parse_status_output(result.stdout, status)

    finally:
        try:
            os.unlink(data_path)
        except OSError:
            pass


def _parse_status_output(stdout: str, status: Dict[str, Any]) -> None:
    """Parse hex-encoded status lines from the C helper's stdout."""
    for line in stdout.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            data = bytes.fromhex(line)
        except ValueError:
            continue

        result = _try_interpret_response(data)
        if result is None:
            logger.debug("Could not interpret status: %s", line)
            continue

        status["printer_state"] = result
        logger.debug("Printer status: %s", result)

        if result.get("errors"):
            logger.error("Printer errors: %s", result["errors"])
            status["outcome"] = "error"
            return

        if result.get("status_type") == "Printing completed":
            status["did_print"] = True
            status["outcome"] = "printed"

        if (
            result.get("status_type") == "Phase change"
            and result.get("phase_type") == "Waiting to receive"
        ):
            status["ready_for_next_job"] = True

    if status["did_print"] and status["ready_for_next_job"]:
        return

    if not status["did_print"]:
        logger.warning("'printing completed' status not received.")
    if not status["ready_for_next_job"]:
        logger.warning("'waiting to receive' status not received.")
