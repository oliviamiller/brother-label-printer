# Model viam:brother-label-printer:discovery

A discovery service that automatically detects Brother QL series label printers connected via USB.

When configured, this service scans the USB bus for Brother printers (vendor ID `0x04f9`) and returns suggested component configurations for each one found. The `printer_identifier` is auto-filled; the `printer_model` is auto-detected from the USB product string when possible.

## Configuration

```json
{}
```

No attributes are required.

## Usage

1. Add this discovery service to your machine configuration.
2. Open the **Test** panel for the discovery service to see all connected Brother QL printers.
3. Each discovered printer is returned as a suggested `viam:brother-label-printer:printer` component config with the USB identifier pre-filled.
4. Copy the configuration snippet and update `printer_model` and `label_size` if they were not auto-detected.

## Example discovered resource

```json
{
  "name": "brother-printer-0",
  "api": "rdk:component:generic",
  "model": "viam:brother-label-printer:printer",
  "attributes": {
    "printer_identifier": "usb://0x04f9:0x209d/C5Z315686",
    "printer_model": "QL-820NWB",
    "label_size": "<SET_YOUR_LABEL e.g. 62 or 29x90>"
  }
}
```

## Requirements

- `libusb` must be installed (see module README).
- The user running `viam-server` must have USB access permissions for the printer.
