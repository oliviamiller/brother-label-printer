"""
CUPS-based fallback backend for macOS.

Sends raw raster data to the printer via ``lpr -l`` (literal/binary mode)
which bypasses CUPS filter processing.  This avoids IOKit entirely and works
through Apple's own print stack.

The trade-off is that status readback is not available — the ``read()``
method always returns an empty bytes object.
"""

from __future__ import annotations

import logging
import os
import subprocess
import tempfile
from typing import List, Optional

logger = logging.getLogger(__name__)


def list_cups_printers() -> List[str]:
    """Return CUPS printer queue names that look like Brother QL devices."""
    try:
        result = subprocess.run(
            ["lpstat", "-p"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        logger.debug("lpstat -p stdout:\n%s", result.stdout)
    except Exception as e:
        logger.warning("lpstat failed: %s", e)
        return []

    printers: List[str] = []
    for line in result.stdout.strip().splitlines():
        upper = line.upper()
        if "QL" in upper or "BROTHER" in upper:
            parts = line.split()
            if len(parts) >= 2:
                printers.append(parts[1])
    logger.debug("Discovered CUPS Brother printers: %s", printers)
    return printers


class CUPSPrinterBackend:
    """Minimal backend that sends raw bytes to a CUPS printer queue.

    Uses ``lpr -l`` (literal mode) to bypass CUPS filtering so that raw
    Brother QL raster instructions reach the printer unmodified.
    """

    def __init__(self, printer_name: Optional[str] = None) -> None:
        if printer_name:
            self._printer_name = printer_name
        else:
            printers = list_cups_printers()
            if not printers:
                raise RuntimeError(
                    "No Brother QL printer found in CUPS queues. "
                    "Set 'cups_printer_name' in the component config to specify one manually."
                )
            self._printer_name = printers[0]
            logger.info("Auto-selected CUPS printer: %s", self._printer_name)

    def write(self, data: bytes) -> int:
        logger.info(
            "Sending %d bytes to CUPS printer %s via lpr -l",
            len(data), self._printer_name,
        )

        # Write to a temp file — some CUPS backends handle files more
        # reliably than stdin for raw/binary data.
        fd, path = tempfile.mkstemp(prefix="brother_ql_", suffix=".bin")
        try:
            os.write(fd, data)
            os.close(fd)

            # -l = literal (binary passthrough, no filter processing)
            # -o raw = additional hint to skip filters
            cmd = [
                "lpr",
                "-P", self._printer_name,
                "-l",
                "-o", "raw",
                path,
            ]
            logger.debug("Running: %s", " ".join(cmd))
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode != 0:
                logger.error("lpr failed (rc=%d): %s", result.returncode, result.stderr)
                raise RuntimeError(f"lpr failed: {result.stderr}")
            logger.info("lpr completed successfully")
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass

        return len(data)

    def read(self, length: int = 32) -> bytes:
        return b""

    def close(self) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
