import sys
from typing import Any, ClassVar, Dict, List, Mapping, Optional, Sequence, Tuple

from typing_extensions import Self
from google.protobuf.struct_pb2 import Struct
from viam.services.discovery import Discovery
from viam.resource.easy_resource import EasyResource
from viam.resource.types import Model, ModelFamily
from viam.proto.app.robot import ComponentConfig
from viam.proto.common import ResourceName
from viam.resource.base import ResourceBase
from viam.utils import ValueTypes
from viam import logging

LOGGER = logging.getLogger(__name__)

BROTHER_USB_VENDOR_ID = 0x04F9


class PrinterDiscovery(Discovery, EasyResource):
    MODEL: ClassVar[Model] = Model(
        ModelFamily("viam", "brother-label-printer"), "discovery"
    )

    @classmethod
    def new(
        cls, config: ComponentConfig, dependencies: Mapping[ResourceName, ResourceBase]
    ) -> Self:
        return super().new(config, dependencies)

    @classmethod
    def validate_config(
        cls, config: ComponentConfig
    ) -> Tuple[Sequence[str], Sequence[str]]:
        return [], []

    def reconfigure(
        self, config: ComponentConfig, dependencies: Mapping[ResourceName, ResourceBase]
    ) -> None:
        pass

    async def discover_resources(
        self,
        *,
        extra: Optional[Mapping[str, Any]] = None,
        timeout: Optional[float] = None,
    ) -> List[ComponentConfig]:
        if sys.platform == "darwin":
            return self._discover_macos()
        return self._discover_pyusb()

    # ------------------------------------------------------------------
    # macOS path — system_profiler, no pyusb / libusb needed
    # ------------------------------------------------------------------

    def _discover_macos(self) -> List[ComponentConfig]:
        try:
            from macos.discovery import discover_devices
        except ImportError:
            from ..macos.discovery import discover_devices

        try:
            devices = discover_devices()
        except Exception as e:
            LOGGER.warning("macOS USB discovery failed: %s", e)
            return []

        from brother_ql.models import ModelsManager
        known_models = {m.identifier for m in ModelsManager().iter_elements()}

        configs: List[ComponentConfig] = []
        for i, dev in enumerate(devices):
            identifier = f"usb://0x{dev['vendor_id']:04x}:0x{dev['product_id']:04x}"
            if dev.get("serial"):
                identifier += f"/{dev['serial']}"

            printer_model = self._detect_model_from_name(dev.get("name", ""), known_models)
            LOGGER.info(
                "Discovered Brother printer: identifier=%s name=%s model=%s",
                identifier,
                dev.get("name"),
                printer_model or "<unknown>",
            )

            attrs = Struct()
            attr_dict: Dict[str, Any] = {"printer_identifier": identifier}
            if printer_model:
                attr_dict["printer_model"] = printer_model
            else:
                attr_dict["printer_model"] = "<SET_YOUR_MODEL e.g. QL-820NWB>"
            attr_dict["label_size"] = "<SET_YOUR_LABEL e.g. 62 or 29x90>"
            attrs.update(attr_dict)

            configs.append(
                ComponentConfig(
                    name=f"brother-printer-{i}",
                    api="rdk:component:generic",
                    model="viam:brother-label-printer:printer",
                    attributes=attrs,
                )
            )
        return configs

    @staticmethod
    def _detect_model_from_name(device_name: str, known_models: set) -> str:
        """Match a system_profiler device name against known brother_ql models."""
        if not device_name:
            return ""
        for model_id in known_models:
            if model_id in device_name:
                return model_id
        LOGGER.debug(
            "Device name '%s' did not match any known brother_ql model", device_name
        )
        return ""

    # ------------------------------------------------------------------
    # Linux / non-macOS path — original pyusb backend
    # ------------------------------------------------------------------

    def _discover_pyusb(self) -> List[ComponentConfig]:
        try:
            from brother_ql.backends.pyusb import list_available_devices
        except ImportError:
            LOGGER.error("brother_ql pyusb backend not available; cannot discover printers")
            return []

        try:
            devices = list_available_devices()
        except Exception as e:
            LOGGER.warning("USB discovery failed: %s", e)
            return []

        from brother_ql.models import ModelsManager
        known_models = {m.identifier for m in ModelsManager().iter_elements()}

        configs: List[ComponentConfig] = []
        for i, device_info in enumerate(devices):
            identifier = device_info["identifier"]
            dev = device_info["instance"]

            printer_model = self._detect_model_pyusb(dev, known_models)
            LOGGER.info(
                "Discovered Brother printer: identifier=%s model=%s",
                identifier,
                printer_model or "<unknown>",
            )

            attrs = Struct()
            attr_dict: Dict[str, Any] = {"printer_identifier": identifier}
            if printer_model:
                attr_dict["printer_model"] = printer_model
            else:
                attr_dict["printer_model"] = "<SET_YOUR_MODEL e.g. QL-820NWB>"
            attr_dict["label_size"] = "<SET_YOUR_LABEL e.g. 62 or 29x90>"
            attrs.update(attr_dict)

            configs.append(
                ComponentConfig(
                    name=f"brother-printer-{i}",
                    api="rdk:component:generic",
                    model="viam:brother-label-printer:printer",
                    attributes=attrs,
                )
            )

        return configs

    @staticmethod
    def _detect_model_pyusb(dev, known_models: set) -> str:
        """Try to read the USB product string and match it to a known brother_ql model."""
        try:
            import usb.util
            product_str = usb.util.get_string(dev, dev.iProduct)
            if not product_str:
                return ""
            for model_id in known_models:
                if model_id in product_str:
                    return model_id
            LOGGER.debug(
                "USB product string '%s' did not match any known brother_ql model", product_str
            )
        except Exception as e:
            LOGGER.debug("Could not read USB product string: %s", e)
        return ""

    async def do_command(
        self,
        command: Mapping[str, ValueTypes],
        *,
        timeout: Optional[float] = None,
        **kwargs,
    ) -> Mapping[str, ValueTypes]:
        return {}

    async def close(self) -> None:
        pass
