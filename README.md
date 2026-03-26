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


# Model viam:brother-label-printer:printer

A generic component that prints text labels on a Brother QL series label printer connected via USB.

## Configuration

```json
{
  "printer_identifier": "usb://0x04f9:0x209d",
  "printer_model": "QL-820NWB",
  "label_size": "29x90"
}
```

### Attributes

| Name                 | Type   | Inclusion | Description                                                                 |
|----------------------|--------|-----------|-----------------------------------------------------------------------------|
| `printer_identifier` | string | Required  | USB identifier of the printer (e.g. `usb://0x04f9:0x209d`)                 |
| `printer_model`      | string | Required  | Brother QL model name (e.g. `QL-820NWB`, `QL-700`). Run `brother_ql info models` for the full list. |
| `label_size`         | string | Required  | Label size identifier (e.g. `29x90`, `62`, `62x100`). Run `brother_ql info labels` for the full list. |

## DoCommand

### print

Prints a text label.

```json
{ "text": "Hello World" }
```

**Response:**

```json
{
  "outcome": "printed",
  "did_print": true
}
```

