import sys
from typing import Any, ClassVar, Dict, Mapping, Optional, Sequence, Tuple

from typing_extensions import Self
from PIL import Image, ImageDraw, ImageFont

# brother_ql uses PIL.Image.ANTIALIAS which was removed in Pillow 10+
if not hasattr(Image, "ANTIALIAS"):
    Image.ANTIALIAS = Image.LANCZOS
from brother_ql.raster import BrotherQLRaster
from brother_ql.conversion import convert
from viam.components.generic import *
from viam.proto.app.robot import ComponentConfig
from viam.proto.common import Geometry, ResourceName
from viam.resource.base import ResourceBase
from viam.resource.easy_resource import EasyResource
from viam.resource.types import Model, ModelFamily
from viam.utils import ValueTypes
from brother_ql.labels import LabelsManager


class Printer(Generic, EasyResource):
    MODEL: ClassVar[Model] = Model(
        ModelFamily("viam", "brother-label-printer"), "printer"
    )

    printer_model: str
    label_size: str
    printer_identifier: str
    cups_printer_name: Optional[str]

    @classmethod
    def new(
        cls, config: ComponentConfig, dependencies: Mapping[ResourceName, ResourceBase]
    ) -> Self:
        self = super().new(config, dependencies)
        self.reconfigure(config, dependencies)
        return self

    @classmethod
    def validate_config(
        cls, config: ComponentConfig
    ) -> Tuple[Sequence[str], Sequence[str]]:
        attrs = config.attributes.fields
        for field in ("printer_identifier", "printer_model", "label_size"):
            if field not in attrs:
                raise ValueError(f"{field} is required")
        return [], []

    def reconfigure(
        self, config: ComponentConfig, dependencies: Mapping[ResourceName, ResourceBase]
    ) -> None:
        attrs = config.attributes.fields
        self.printer_identifier = attrs["printer_identifier"].string_value
        self.printer_model = attrs["printer_model"].string_value
        self.label_size = attrs["label_size"].string_value
        self.cups_printer_name = (
            attrs["cups_printer_name"].string_value
            if "cups_printer_name" in attrs
            else None
        )

    def _create_image(self, text: str) -> Image.Image:
        label = next(e for e in LabelsManager().iter_elements() if e.identifier == self.label_size)
        w, h = label.dots_printable
        img = Image.new("RGB", (h, w), color="white")  # rotated 90 degrees
        draw = ImageDraw.Draw(img)
        font_size = max(20, w // 2)
        font = ImageFont.load_default()
        while font_size >= 10:
            try:
                f = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", font_size)
            except OSError:
                try:
                    f = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", font_size)
                except OSError:
                    break
            bbox = draw.textbbox((0, 0), text, font=f)
            if (bbox[2] - bbox[0]) <= h and (bbox[3] - bbox[1]) <= w:
                font = f
                break
            font_size -= 2
        bbox = draw.textbbox((0, 0), text, font=font)
        x = (h - (bbox[2] - bbox[0])) // 2
        y = (w - (bbox[3] - bbox[1])) // 2
        draw.text((x, y), text, fill="black", font=font)
        return img

    async def do_command(
        self,
        command: Mapping[str, ValueTypes],
        *,
        timeout: Optional[float] = None,
        **kwargs
    ) -> Mapping[str, ValueTypes]:
        text = command.get("text")
        if not text:
            raise ValueError("command must include a 'text' field")

        self.logger.info(
            "do_command called: text=%r, printer_model=%r, label_size=%r, printer_identifier=%r",
            text, self.printer_model, self.label_size, self.printer_identifier,
        )

        self.logger.debug("Creating label image for text=%r", text)
        img = self._create_image(str(text))
        self.logger.debug("Image created: size=%s, mode=%s", img.size, img.mode)

        self.logger.debug("Initializing BrotherQLRaster with model=%r", self.printer_model)
        qlr = BrotherQLRaster(self.printer_model)

        self.logger.debug(
            "Running convert: label_size=%r, rotate='90', cut=True", self.label_size
        )
        convert(qlr, [img], self.label_size, rotate="90", cut=True)
        self.logger.debug("Convert complete, instruction data length=%d bytes", len(qlr.data))

        if sys.platform == "darwin":
            result = self._send_macos(qlr.data)
        else:
            result = self._send_pyusb(qlr.data)

        self.logger.info("Print result: %s", result)
        return {"outcome": result["outcome"], "did_print": result["did_print"]}

    def _send_macos(self, instructions: bytes) -> dict:
        """Send via macOS native backend (IOKit → CUPS fallback)."""
        try:
            from macos.send import send as macos_send
        except ImportError:
            from ..macos.send import send as macos_send

        self.logger.info(
            "Sending to printer via macOS native backend: printer_identifier=%r",
            self.printer_identifier,
        )
        return macos_send(
            instructions=instructions,
            printer_identifier=self.printer_identifier,
            blocking=True,
            cups_printer_name=self.cups_printer_name,
        )

    def _send_pyusb(self, instructions: bytes) -> dict:
        """Send via the original brother_ql pyusb backend."""
        from brother_ql.backends.helpers import send

        backend_identifier = "pyusb"
        self.logger.info(
            "Sending to printer via pyusb: printer_identifier=%r, backend_identifier=%r",
            self.printer_identifier, backend_identifier,
        )
        return send(
            instructions=instructions,
            printer_identifier=self.printer_identifier,
            backend_identifier=backend_identifier,
            blocking=True,
        )

    async def get_geometries(
        self, *, extra: Optional[Dict[str, Any]] = None, timeout: Optional[float] = None
    ) -> Sequence[Geometry]:
        return []
