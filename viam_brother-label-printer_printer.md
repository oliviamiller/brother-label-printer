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
