from typing import (Any, ClassVar, Dict, Mapping, Optional, Sequence, Tuple)

from typing_extensions import Self
from PIL import Image, ImageDraw, ImageFont
from brother_ql.raster import BrotherQLRaster
from brother_ql.conversion import convert
from brother_ql.backends.helpers import send
from viam.components.generic import *
from viam.proto.app.robot import ComponentConfig
from viam.proto.common import Geometry, ResourceName
from viam.resource.base import ResourceBase
from viam.resource.easy_resource import EasyResource
from viam.resource.types import Model, ModelFamily
from viam.utils import ValueTypes


class Printer(Generic, EasyResource):
    MODEL: ClassVar[Model] = Model(
        ModelFamily("viam", "brother-label-printer"), "printer"
    )

    printer_model: str
    label_size: str
    printer_identifier: str

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

    def _create_image(self, text: str) -> Image.Image:
        from brother_ql.labels import LabelsManager
        label = LabelsManager().get_element_by_identifier(self.label_size)
        w, h = label.dots_printable
        img = Image.new("RGB", (h, w), color="white")  # rotated 90 degrees
        draw = ImageDraw.Draw(img)
        font_size = max(20, w // 2)
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", font_size)
        except OSError:
            font = ImageFont.load_default()
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

        img = self._create_image(str(text))
        qlr = BrotherQLRaster(self.printer_model)
        convert(qlr, [img], self.label_size, rotate="90", cut=True)
        result = send(
            instructions=qlr.data,
            printer_identifier=self.printer_identifier,
            backend_identifier="pyusb",
            blocking=True,
        )
        self.logger.info("Print result: %s", result)
        return {"outcome": result["outcome"], "did_print": result["did_print"]}

    async def get_geometries(
        self, *, extra: Optional[Dict[str, Any]] = None, timeout: Optional[float] = None
    ) -> Sequence[Geometry]:
        return []

