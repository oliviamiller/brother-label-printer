"""
IOKit USB I/O for macOS via ctypes.

Provides low-level USB bulk read/write for Brother QL printers without
requiring pyusb or libusb.  Uses the IOKit COM-style interface to open a USB
device, locate the printer-class interface (bInterfaceClass == 7), and
perform WritePipe / ReadPipe for bulk transfers.

Vtable offsets are derived from IOUSBLib.h in the IOUSBFamily open-source
headers.  The struct layout includes IUNKNOWN_C_GUTS (_reserved,
QueryInterface, AddRef, Release) followed by the IOKit-specific methods.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Framework loading
# ---------------------------------------------------------------------------

_iokit_path = ctypes.util.find_library("IOKit")
_cf_path = ctypes.util.find_library("CoreFoundation")

if not _iokit_path or not _cf_path:
    raise ImportError("IOKit or CoreFoundation frameworks not found (not macOS?)")

_iokit = ctypes.cdll.LoadLibrary(_iokit_path)
_cf = ctypes.cdll.LoadLibrary(_cf_path)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

kIOMasterPortDefault = ctypes.c_void_p(0)  # NULL since Big Sur
KERN_SUCCESS = 0
kIOReturnSuccess = 0
kIOReturnExclusiveAccess = 0xE00002C5  # iokit/IOReturn.h

# USB direction / transfer type constants
kUSBOut = 0
kUSBIn = 1
kUSBBulk = 2

# IOUSBFindInterfaceRequest "don't care" sentinel
kIOUSBFindInterfaceDontCare = 0xFFFF

# USB Printer class
USB_PRINTER_CLASS = 7

# ---------------------------------------------------------------------------
# CoreFoundation helpers
# ---------------------------------------------------------------------------

_cf.CFStringCreateWithCString.restype = ctypes.c_void_p
_cf.CFStringCreateWithCString.argtypes = [
    ctypes.c_void_p,
    ctypes.c_char_p,
    ctypes.c_uint32,
]

_cf.CFStringGetCString.restype = ctypes.c_bool
_cf.CFStringGetCString.argtypes = [
    ctypes.c_void_p,
    ctypes.c_char_p,
    ctypes.c_long,
    ctypes.c_uint32,
]

_cf.CFNumberCreate.restype = ctypes.c_void_p
_cf.CFNumberCreate.argtypes = [ctypes.c_void_p, ctypes.c_int32, ctypes.c_void_p]

_cf.CFDictionarySetValue.restype = None
_cf.CFDictionarySetValue.argtypes = [
    ctypes.c_void_p,
    ctypes.c_void_p,
    ctypes.c_void_p,
]

_cf.CFRelease.restype = None
_cf.CFRelease.argtypes = [ctypes.c_void_p]

kCFStringEncodingUTF8 = 0x08000100
kCFNumberSInt32Type = 3


def _cfstr(s: str) -> ctypes.c_void_p:
    return _cf.CFStringCreateWithCString(None, s.encode("utf-8"), kCFStringEncodingUTF8)


def _cfnum32(val: int) -> ctypes.c_void_p:
    n = ctypes.c_int32(val)
    return _cf.CFNumberCreate(None, kCFNumberSInt32Type, ctypes.byref(n))


# ---------------------------------------------------------------------------
# CFUUIDBytes — 16-byte struct used as COM IID on macOS (QueryInterface)
# CFUUIDRef  — opaque pointer used by IOCreatePlugInInterfaceForService
# ---------------------------------------------------------------------------

class CFUUIDBytes(ctypes.Structure):
    _fields_ = [(f"byte{i}", ctypes.c_uint8) for i in range(16)]


_cf.CFUUIDGetConstantUUIDWithBytes.restype = ctypes.c_void_p
_cf.CFUUIDGetConstantUUIDWithBytes.argtypes = [ctypes.c_void_p] + [ctypes.c_uint8] * 16

_cf.CFUUIDGetUUIDBytes.restype = CFUUIDBytes
_cf.CFUUIDGetUUIDBytes.argtypes = [ctypes.c_void_p]


def _make_uuid_ref(*byte_args: int) -> ctypes.c_void_p:
    """Create a CFUUIDRef (opaque pointer) from 16 raw bytes."""
    return _cf.CFUUIDGetConstantUUIDWithBytes(None, *byte_args)


def _make_uuid_bytes(*byte_args: int) -> CFUUIDBytes:
    """Create a CFUUIDBytes struct from 16 raw bytes (for QueryInterface)."""
    ref = _cf.CFUUIDGetConstantUUIDWithBytes(None, *byte_args)
    return _cf.CFUUIDGetUUIDBytes(ref)


# IOCreatePlugInInterfaceForService needs CFUUIDRef (pointer), not CFUUIDBytes
_kIOUSBDeviceUserClientTypeID_ref = _make_uuid_ref(
    0x9D, 0xC7, 0xB7, 0x80, 0x9E, 0xC0, 0x11, 0xD4,
    0xA5, 0x4F, 0x00, 0x0A, 0x27, 0x05, 0x28, 0x61,
)
_kIOCFPlugInInterfaceID_ref = _make_uuid_ref(
    0xC2, 0x44, 0xE8, 0x58, 0x10, 0x9C, 0x11, 0xD4,
    0x91, 0xD4, 0x00, 0x50, 0xE4, 0xC6, 0x42, 0x6F,
)
_kIOUSBInterfaceUserClientTypeID_ref = _make_uuid_ref(
    0x2D, 0x97, 0x86, 0xC6, 0x9E, 0xF3, 0x11, 0xD4,
    0xAD, 0x51, 0x00, 0x0A, 0x27, 0x05, 0x28, 0x61,
)

# QueryInterface needs CFUUIDBytes (struct by value)
_kIOUSBDeviceInterfaceID_bytes = _make_uuid_bytes(
    0x5C, 0x81, 0x87, 0xD0, 0x9E, 0xF3, 0x11, 0xD4,
    0x8B, 0x45, 0x00, 0x0A, 0x27, 0x05, 0x28, 0x61,
)
_kIOUSBInterfaceInterfaceID_bytes = _make_uuid_bytes(
    0x73, 0xC9, 0x7A, 0xE8, 0x9E, 0xF3, 0x11, 0xD4,
    0xB1, 0xD0, 0x00, 0x0A, 0x27, 0x05, 0x28, 0x61,
)

# ---------------------------------------------------------------------------
# IOKit C function signatures
# ---------------------------------------------------------------------------

_iokit.IOServiceMatching.restype = ctypes.c_void_p
_iokit.IOServiceMatching.argtypes = [ctypes.c_char_p]

_iokit.IOServiceGetMatchingServices.restype = ctypes.c_int32
_iokit.IOServiceGetMatchingServices.argtypes = [
    ctypes.c_void_p,
    ctypes.c_void_p,
    ctypes.POINTER(ctypes.c_uint32),
]

_iokit.IOIteratorNext.restype = ctypes.c_uint32
_iokit.IOIteratorNext.argtypes = [ctypes.c_uint32]

_iokit.IOObjectRelease.restype = ctypes.c_int32
_iokit.IOObjectRelease.argtypes = [ctypes.c_uint32]

# pluginType and interfaceType are CFUUIDRef (c_void_p), NOT CFUUIDBytes
_iokit.IOCreatePlugInInterfaceForService.restype = ctypes.c_int32
_iokit.IOCreatePlugInInterfaceForService.argtypes = [
    ctypes.c_uint32,    # service (io_service_t)
    ctypes.c_void_p,    # pluginType (CFUUIDRef)
    ctypes.c_void_p,    # interfaceType (CFUUIDRef)
    ctypes.POINTER(ctypes.c_void_p),  # theInterface (IOCFPlugInInterface ***)
    ctypes.POINTER(ctypes.c_int32),   # theScore*
]

_iokit.IORegistryEntryCreateCFProperty.restype = ctypes.c_void_p
_iokit.IORegistryEntryCreateCFProperty.argtypes = [
    ctypes.c_uint32,   # entry
    ctypes.c_void_p,   # key (CFStringRef)
    ctypes.c_void_p,   # allocator
    ctypes.c_uint32,   # options
]

# ---------------------------------------------------------------------------
# IOUSBFindInterfaceRequest struct
# ---------------------------------------------------------------------------

class IOUSBFindInterfaceRequest(ctypes.Structure):
    _fields_ = [
        ("bInterfaceClass", ctypes.c_uint16),
        ("bInterfaceSubClass", ctypes.c_uint16),
        ("bInterfaceProtocol", ctypes.c_uint16),
        ("bAlternateSetting", ctypes.c_uint16),
    ]


# ---------------------------------------------------------------------------
# COM vtable helpers
#
# IOKit COM objects are double-pointer (T**). The vtable is an array of
# function pointers at *obj.  IUNKNOWN_C_GUTS prepends:
#   [0] _reserved   [1] QueryInterface   [2] AddRef   [3] Release
# Then the type-specific methods follow at index 4+.
# ---------------------------------------------------------------------------

def _vtable(dbl_ptr: ctypes.c_void_p) -> ctypes.Array:
    """Dereference a COM double-pointer to get the vtable as an array of void*."""
    inner = ctypes.cast(dbl_ptr, ctypes.POINTER(ctypes.c_void_p))[0]
    # 64 entries is plenty for any IOKit vtable
    return ctypes.cast(inner, ctypes.POINTER(ctypes.c_void_p * 64))[0]


def _call(dbl_ptr, vtable_index, argtypes, *args):
    """Call a COM vtable method.  The double-pointer is passed as 'self'."""
    vt = _vtable(dbl_ptr)
    func_ptr = vt[vtable_index]
    proto = ctypes.CFUNCTYPE(*argtypes)
    fn = proto(func_ptr)
    return fn(dbl_ptr, *args)


def _query_interface(plugin_ptr, iid: CFUUIDBytes):
    """QueryInterface (vtable index 1). Returns the requested interface double-pointer."""
    result = ctypes.c_void_p()
    hr = _call(
        plugin_ptr,
        1,  # QueryInterface
        [ctypes.c_int32, ctypes.c_void_p, CFUUIDBytes, ctypes.POINTER(ctypes.c_void_p)],
        iid,
        ctypes.byref(result),
    )
    if hr != 0:
        raise IOKitError(f"QueryInterface failed: HRESULT 0x{hr & 0xFFFFFFFF:08X}")
    return result


def _release(dbl_ptr):
    """Release (vtable index 3)."""
    _call(dbl_ptr, 3, [ctypes.c_uint32, ctypes.c_void_p])


# ---------------------------------------------------------------------------
# IOUSBDeviceInterface vtable indices (IOUSBDeviceInterface182)
#
# IUNKNOWN_C_GUTS:
#   [0] _reserved  [1] QueryInterface  [2] AddRef  [3] Release
# Then device methods:
#   [4]  CreateDeviceAsyncEventSource
#   [5]  GetDeviceAsyncEventSource
#   [6]  CreateDeviceAsyncPort
#   [7]  GetDeviceAsyncPort
#   [8]  USBDeviceOpen
#   [9]  USBDeviceClose
#   [10] GetDeviceClass         [11] GetDeviceSubClass
#   [12] GetDeviceProtocol      [13] GetDeviceVendor
#   [14] GetDeviceProduct       [15] GetDeviceReleaseNumber
#   [16] GetDeviceAddress       [17] GetDeviceBusPowerAvailable
#   [18] GetDeviceSpeed         [19] GetNumberOfConfigurations
#   [20] GetLocationID          [21] GetConfigurationDescriptorPtr
#   [22] GetConfiguration       [23] SetConfiguration
#   [24] GetBusFrameNumber      [25] ResetDevice
#   [26] DeviceRequest          [27] DeviceRequestAsync
#   [28] CreateInterfaceIterator
# ---------------------------------------------------------------------------

_DEV_USB_DEVICE_OPEN = 8
_DEV_USB_DEVICE_CLOSE = 9
_DEV_SET_CONFIGURATION = 23
_DEV_CREATE_INTERFACE_ITERATOR = 28

# ---------------------------------------------------------------------------
# IOUSBInterfaceInterface vtable indices (IOUSBInterfaceInterface182)
#
# IUNKNOWN_C_GUTS:
#   [0] _reserved  [1] QueryInterface  [2] AddRef  [3] Release
# Then interface methods:
#   [4]  CreateInterfaceAsyncEventSource
#   [5]  GetInterfaceAsyncEventSource
#   [6]  CreateInterfaceAsyncPort
#   [7]  GetInterfaceAsyncPort
#   [8]  USBInterfaceOpen       [9]  USBInterfaceClose
#   [10] GetInterfaceClass      [11] GetInterfaceSubClass
#   [12] GetInterfaceProtocol   [13] GetDeviceVendor
#   [14] GetDeviceProduct       [15] GetDeviceReleaseNumber
#   [16] GetConfigurationValue  [17] GetInterfaceNumber
#   [18] GetAlternateSetting    [19] GetNumEndpoints
#   [20] GetLocationID          [21] GetDevice
#   [22] SetAlternateInterface  [23] GetBusFrameNumber
#   [24] GetPipeProperties      [25] GetPipeStatus
#   [26] AbortPipe              [27] ResetPipe
#   [28] ClearPipeStall         [29] ReadPipe
#   [30] WritePipe
# ---------------------------------------------------------------------------

_INTF_USB_INTERFACE_OPEN = 8
_INTF_USB_INTERFACE_CLOSE = 9
_INTF_GET_INTERFACE_CLASS = 10
_INTF_GET_NUM_ENDPOINTS = 19
_INTF_SET_ALTERNATE_INTERFACE = 22
_INTF_GET_PIPE_PROPERTIES = 24
_INTF_READ_PIPE = 29
_INTF_WRITE_PIPE = 30


# ---------------------------------------------------------------------------
# Custom exception
# ---------------------------------------------------------------------------

class IOKitError(Exception):
    pass


# ---------------------------------------------------------------------------
# IOKitUSBDevice — wraps IOKit for USB bulk I/O
# ---------------------------------------------------------------------------

class IOKitUSBDevice:
    """Open a USB device by vendor/product ID and perform bulk I/O.

    Usage::

        dev = IOKitUSBDevice(0x04f9, 0x209b)
        dev.write(raster_data)
        status = dev.read(32)
        dev.close()
    """

    def __init__(
        self,
        vendor_id: int,
        product_id: int,
        serial: Optional[str] = None,
    ) -> None:
        self._device_iface: Optional[ctypes.c_void_p] = None
        self._interface_iface: Optional[ctypes.c_void_p] = None
        self._bulk_out_pipe: int = 0
        self._bulk_in_pipe: int = 0

        service = self._find_service(vendor_id, product_id, serial)
        try:
            self._open_device(service)
        except Exception:
            self.close()
            raise
        finally:
            _iokit.IOObjectRelease(service)

    # ----- discovery via IOKit registry (matches a single device) ----------

    @staticmethod
    def _find_service(
        vendor_id: int, product_id: int, serial: Optional[str]
    ) -> int:
        """Find the io_service_t for the matching USB device."""
        for class_name in (b"IOUSBHostDevice", b"IOUSBDevice"):
            matching = _iokit.IOServiceMatching(class_name)
            if not matching:
                continue

            vid_key = _cfstr("idVendor")
            pid_key = _cfstr("idProduct")
            vid_val = _cfnum32(vendor_id)
            pid_val = _cfnum32(product_id)
            _cf.CFDictionarySetValue(matching, vid_key, vid_val)
            _cf.CFDictionarySetValue(matching, pid_key, pid_val)
            _cf.CFRelease(vid_key)
            _cf.CFRelease(pid_key)
            _cf.CFRelease(vid_val)
            _cf.CFRelease(pid_val)

            iterator = ctypes.c_uint32(0)
            kr = _iokit.IOServiceGetMatchingServices(
                kIOMasterPortDefault, matching, ctypes.byref(iterator)
            )
            # IOServiceGetMatchingServices consumes the matching dict reference
            if kr != KERN_SUCCESS:
                logger.debug(
                    "IOServiceGetMatchingServices(%s) returned 0x%08X",
                    class_name, kr,
                )
                continue

            while True:
                service = _iokit.IOIteratorNext(iterator.value)
                if not service:
                    break

                if serial:
                    serial_key = _cfstr("USB Serial Number")
                    cf_serial = _iokit.IORegistryEntryCreateCFProperty(
                        service, serial_key, None, 0
                    )
                    _cf.CFRelease(serial_key)
                    if cf_serial:
                        buf = ctypes.create_string_buffer(256)
                        _cf.CFStringGetCString(cf_serial, buf, 256, kCFStringEncodingUTF8)
                        _cf.CFRelease(cf_serial)
                        if buf.value.decode("utf-8", errors="replace") != serial:
                            _iokit.IOObjectRelease(service)
                            continue

                logger.info(
                    "Found USB service via %s for vendor=0x%04x product=0x%04x",
                    class_name.decode(), vendor_id, product_id,
                )
                _iokit.IOObjectRelease(iterator.value)
                return service

            _iokit.IOObjectRelease(iterator.value)

        raise IOKitError(
            f"No USB device found with vendor=0x{vendor_id:04x} "
            f"product=0x{product_id:04x}"
            + (f" serial={serial}" if serial else "")
        )

    # ----- device open + interface setup -----------------------------------

    def _open_device(self, service: int) -> None:
        plugin = ctypes.c_void_p()
        score = ctypes.c_int32(0)

        kr = _iokit.IOCreatePlugInInterfaceForService(
            service,
            _kIOUSBDeviceUserClientTypeID_ref,
            _kIOCFPlugInInterfaceID_ref,
            ctypes.byref(plugin),
            ctypes.byref(score),
        )
        if kr != KERN_SUCCESS or not plugin:
            raise IOKitError(f"IOCreatePlugInInterfaceForService failed: 0x{kr:08X}")

        try:
            self._device_iface = _query_interface(plugin, _kIOUSBDeviceInterfaceID_bytes)
        finally:
            _release(plugin)

        logger.debug("QueryInterface for device succeeded, opening device...")

        kr = _call(
            self._device_iface,
            _DEV_USB_DEVICE_OPEN,
            [ctypes.c_int32, ctypes.c_void_p],
        )
        if kr == kIOReturnExclusiveAccess:
            raise IOKitError(
                "Device is claimed by another driver (kIOReturnExclusiveAccess). "
                "You may need to unload the macOS printer driver for this device."
            )
        if kr != kIOReturnSuccess:
            raise IOKitError(f"USBDeviceOpen failed: 0x{kr & 0xFFFFFFFF:08X}")

        logger.debug("USBDeviceOpen succeeded, setting configuration 1...")

        kr = _call(
            self._device_iface,
            _DEV_SET_CONFIGURATION,
            [ctypes.c_int32, ctypes.c_void_p, ctypes.c_uint8],
            ctypes.c_uint8(1),
        )
        logger.debug("SetConfiguration(1) returned 0x%08X", kr & 0xFFFFFFFF)

        self._open_printer_interface()

    def _open_printer_interface(self) -> None:
        """Find and open the USB printer-class interface, enumerate pipes."""
        # First try matching printer class specifically, then fall back to any
        for intf_class in (USB_PRINTER_CLASS, kIOUSBFindInterfaceDontCare):
            request = IOUSBFindInterfaceRequest(
                bInterfaceClass=intf_class,
                bInterfaceSubClass=kIOUSBFindInterfaceDontCare,
                bInterfaceProtocol=kIOUSBFindInterfaceDontCare,
                bAlternateSetting=kIOUSBFindInterfaceDontCare,
            )
            iterator = ctypes.c_uint32(0)
            kr = _call(
                self._device_iface,
                _DEV_CREATE_INTERFACE_ITERATOR,
                [
                    ctypes.c_int32,
                    ctypes.c_void_p,
                    ctypes.POINTER(IOUSBFindInterfaceRequest),
                    ctypes.POINTER(ctypes.c_uint32),
                ],
                ctypes.byref(request),
                ctypes.byref(iterator),
            )
            if kr != kIOReturnSuccess:
                logger.debug(
                    "CreateInterfaceIterator(class=%d) failed: 0x%08X",
                    intf_class, kr & 0xFFFFFFFF,
                )
                continue

            intf_index = 0
            while True:
                intf_service = _iokit.IOIteratorNext(iterator.value)
                if not intf_service:
                    break
                logger.debug(
                    "Found interface service #%d (class filter=%s)",
                    intf_index,
                    intf_class if intf_class != kIOUSBFindInterfaceDontCare else "any",
                )
                try:
                    self._open_interface_service(intf_service)
                    _iokit.IOObjectRelease(iterator.value)
                    return
                except IOKitError as e:
                    logger.debug("Interface #%d failed: %s", intf_index, e)
                    self._interface_iface = None
                finally:
                    _iokit.IOObjectRelease(intf_service)
                intf_index += 1

            _iokit.IOObjectRelease(iterator.value)

            if intf_class == USB_PRINTER_CLASS:
                logger.debug(
                    "No usable printer-class interface, retrying with any class..."
                )

        raise IOKitError("No USB interface with bulk endpoints found on this device")

    def _open_interface_service(self, intf_service: int) -> None:
        plugin = ctypes.c_void_p()
        score = ctypes.c_int32(0)

        kr = _iokit.IOCreatePlugInInterfaceForService(
            intf_service,
            _kIOUSBInterfaceUserClientTypeID_ref,
            _kIOCFPlugInInterfaceID_ref,
            ctypes.byref(plugin),
            ctypes.byref(score),
        )
        if kr != KERN_SUCCESS or not plugin:
            raise IOKitError(
                f"IOCreatePlugInInterfaceForService (interface) failed: 0x{kr:08X}"
            )

        try:
            self._interface_iface = _query_interface(
                plugin, _kIOUSBInterfaceInterfaceID_bytes
            )
        finally:
            _release(plugin)

        kr = _call(
            self._interface_iface,
            _INTF_USB_INTERFACE_OPEN,
            [ctypes.c_int32, ctypes.c_void_p],
        )
        if kr != kIOReturnSuccess:
            raise IOKitError(f"USBInterfaceOpen failed: 0x{kr & 0xFFFFFFFF:08X}")

        logger.debug("USBInterfaceOpen succeeded")

        # Some USB devices need an explicit alternate-interface setting before
        # endpoints become visible to GetNumEndpoints / GetPipeProperties.
        kr = _call(
            self._interface_iface,
            _INTF_SET_ALTERNATE_INTERFACE,
            [ctypes.c_int32, ctypes.c_void_p, ctypes.c_uint8],
            ctypes.c_uint8(0),
        )
        logger.debug("SetAlternateInterface(0) returned 0x%08X", kr & 0xFFFFFFFF)

        self._enumerate_pipes()

    def _enumerate_pipes(self) -> None:
        """Find Bulk OUT and Bulk IN pipe references."""
        num_ep = ctypes.c_uint8(0)
        kr = _call(
            self._interface_iface,
            _INTF_GET_NUM_ENDPOINTS,
            [ctypes.c_int32, ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint8)],
            ctypes.byref(num_ep),
        )
        logger.info(
            "GetNumEndpoints returned 0x%08X, num_endpoints=%d",
            kr & 0xFFFFFFFF, num_ep.value,
        )

        for pipe_ref in range(1, num_ep.value + 1):
            direction = ctypes.c_uint8()
            number = ctypes.c_uint8()
            transfer_type = ctypes.c_uint8()
            max_packet = ctypes.c_uint16()
            interval = ctypes.c_uint8()

            kr = _call(
                self._interface_iface,
                _INTF_GET_PIPE_PROPERTIES,
                [
                    ctypes.c_int32,
                    ctypes.c_void_p,
                    ctypes.c_uint8,
                    ctypes.POINTER(ctypes.c_uint8),
                    ctypes.POINTER(ctypes.c_uint8),
                    ctypes.POINTER(ctypes.c_uint8),
                    ctypes.POINTER(ctypes.c_uint16),
                    ctypes.POINTER(ctypes.c_uint8),
                ],
                ctypes.c_uint8(pipe_ref),
                ctypes.byref(direction),
                ctypes.byref(number),
                ctypes.byref(transfer_type),
                ctypes.byref(max_packet),
                ctypes.byref(interval),
            )

            logger.info(
                "Pipe %d: direction=%d number=%d transfer_type=%d "
                "max_packet=%d interval=%d (IOReturn=0x%08X)",
                pipe_ref, direction.value, number.value, transfer_type.value,
                max_packet.value, interval.value, kr & 0xFFFFFFFF,
            )

            if transfer_type.value == kUSBBulk:
                if direction.value == kUSBOut and not self._bulk_out_pipe:
                    self._bulk_out_pipe = pipe_ref
                elif direction.value == kUSBIn and not self._bulk_in_pipe:
                    self._bulk_in_pipe = pipe_ref

        if not self._bulk_out_pipe:
            raise IOKitError(
                f"No Bulk OUT endpoint found on printer interface "
                f"(enumerated {num_ep.value} endpoint(s))"
            )
        if not self._bulk_in_pipe:
            logger.warning("No Bulk IN endpoint found — status reads will not work")

        logger.info(
            "Pipe setup complete: bulk_out=%d bulk_in=%d",
            self._bulk_out_pipe, self._bulk_in_pipe,
        )

    # ----- public I/O API --------------------------------------------------

    def write(self, data: bytes) -> int:
        """Send data via Bulk OUT. Returns number of bytes written."""
        if not self._interface_iface:
            raise IOKitError("Device not open")

        buf = ctypes.create_string_buffer(data)
        kr = _call(
            self._interface_iface,
            _INTF_WRITE_PIPE,
            [
                ctypes.c_int32,
                ctypes.c_void_p,
                ctypes.c_uint8,
                ctypes.c_void_p,
                ctypes.c_uint32,
            ],
            ctypes.c_uint8(self._bulk_out_pipe),
            ctypes.cast(buf, ctypes.c_void_p),
            ctypes.c_uint32(len(data)),
        )
        if kr != kIOReturnSuccess:
            raise IOKitError(f"WritePipe failed: 0x{kr & 0xFFFFFFFF:08X}")
        return len(data)

    def read(self, length: int = 32) -> bytes:
        """Read data via Bulk IN. Returns bytes read (may be shorter than *length*)."""
        if not self._interface_iface:
            raise IOKitError("Device not open")
        if not self._bulk_in_pipe:
            return b""

        buf = ctypes.create_string_buffer(length)
        size = ctypes.c_uint32(length)
        kr = _call(
            self._interface_iface,
            _INTF_READ_PIPE,
            [
                ctypes.c_int32,
                ctypes.c_void_p,
                ctypes.c_uint8,
                ctypes.c_void_p,
                ctypes.POINTER(ctypes.c_uint32),
            ],
            ctypes.c_uint8(self._bulk_in_pipe),
            ctypes.cast(buf, ctypes.c_void_p),
            ctypes.byref(size),
        )
        if kr != kIOReturnSuccess:
            logger.debug("ReadPipe returned 0x%08X", kr & 0xFFFFFFFF)
            return b""
        return buf.raw[: size.value]

    # ----- cleanup ---------------------------------------------------------

    def close(self) -> None:
        """Close USB interface and device handles."""
        if self._interface_iface:
            try:
                _call(
                    self._interface_iface,
                    _INTF_USB_INTERFACE_CLOSE,
                    [ctypes.c_int32, ctypes.c_void_p],
                )
            except Exception:
                pass
            try:
                _release(self._interface_iface)
            except Exception:
                pass
            self._interface_iface = None

        if self._device_iface:
            try:
                _call(
                    self._device_iface,
                    _DEV_USB_DEVICE_CLOSE,
                    [ctypes.c_int32, ctypes.c_void_p],
                )
            except Exception:
                pass
            try:
                _release(self._device_iface)
            except Exception:
                pass
            self._device_iface = None

    def __del__(self) -> None:
        self.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
