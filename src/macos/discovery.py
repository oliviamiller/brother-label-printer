"""
Discover Brother QL printers on macOS using system_profiler.

Parses the JSON output of ``system_profiler SPUSBDataType -json`` to find
USB devices with the Brother vendor ID (0x04f9). This avoids any dependency
on pyusb / libusb.
"""

import json
import logging
import subprocess
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

BROTHER_VENDOR_ID = 0x04F9


def _parse_usb_tree(items: List[Any], results: List[Dict[str, Any]]) -> None:
    """Recursively walk the system_profiler USB tree to find Brother devices."""
    for item in items:
        if not isinstance(item, dict):
            continue
        vendor_id_raw = item.get("vendor_id")
        if vendor_id_raw:
            try:
                vid = int(str(vendor_id_raw).split()[0], 16)
            except (ValueError, IndexError):
                vid = 0

            if vid == BROTHER_VENDOR_ID:
                product_id_raw = item.get("product_id", "0x0000")
                try:
                    pid = int(str(product_id_raw).split()[0], 16)
                except (ValueError, IndexError):
                    pid = 0

                serial = item.get("serial_num", "")
                name = item.get("_name", "Unknown Brother Device")
                results.append(
                    {
                        "vendor_id": vid,
                        "product_id": pid,
                        "serial": serial,
                        "name": name,
                    }
                )

        for value in item.values():
            if isinstance(value, list):
                _parse_usb_tree(value, results)


def discover_devices() -> List[Dict[str, Any]]:
    """Return a list of discovered Brother USB printers.

    Each entry is a dict with keys:
        vendor_id  (int), product_id (int), serial (str), name (str)
    """
    try:
        result = subprocess.run(
            ["system_profiler", "SPUSBDataType", "-json"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        data = json.loads(result.stdout)
        devices: List[Dict[str, Any]] = []
        usb_items = data.get("SPUSBDataType", [])
        _parse_usb_tree(usb_items, devices)
        return devices
    except Exception as e:
        logger.warning("system_profiler discovery failed: %s", e)
        return []
