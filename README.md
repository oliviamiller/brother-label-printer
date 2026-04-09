# Module brother-label-printer

A Viam module for printing text labels on Brother QL series label printers over USB.

## Models

- [`viam:brother-label-printer:printer`](viam_brother-label-printer_printer.md) - Generic component for printing text labels on a Brother QL printer via USB.

## Requirements

The module requires `libusb` to communicate with the printer over USB. On Linux:

```bash
sudo apt install libusb-1.0-0
```

USB access permissions must allow the user running `viam-server` to access the printer. Either run with `sudo`, or add a udev rule:

```bash
echo 'SUBSYSTEM=="usb", ATTR{idVendor}=="04f9", MODE="0666"' | sudo tee /etc/udev/rules.d/99-brother.rules
sudo udevadm control --reload-rules && sudo udevadm trigger
```

## Finding your printer identifier

With the printer connected via USB, run:

```bash
brother_ql discover
```

Or use `lsusb` to find the vendor and product IDs:

```bash
lsusb | grep -i brother
# Example output: Bus 003 Device 012: ID 04f9:20a8 Brother Industries, Ltd QL-820NWB
# Identifier: usb://0x04f9:0x20a8
```

## Finding your label size

Run the following to list supported label sizes:

```bash
brother_ql info labels
```

Use the value from the `Name` column (e.g. `29x90`, `62`, `62x100`).

