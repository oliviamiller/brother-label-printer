/*
 * usb_printer — minimal IOKit USB printer I/O tool for Brother QL printers.
 *
 * Sends raw raster data to a Brother USB printer and reads the 32-byte
 * status response.  Uses IOKit natively — no libusb required.
 *
 * Build:
 *   clang -O2 -o usb_printer usb_printer.c -framework IOKit -framework CoreFoundation
 *
 * Usage:
 *   usb_printer send <vid> <pid> <input_file> [serial]
 *
 * Exit codes:
 *   0 = success (status hex printed to stdout)
 *   1 = bad arguments
 *   2 = device not found or cannot open
 *   3 = I/O error
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#include <CoreFoundation/CoreFoundation.h>
#include <IOKit/IOKitLib.h>
#include <IOKit/IOCFPlugIn.h>
#include <IOKit/usb/IOUSBLib.h>

#define USB_PRINTER_CLASS 7

static IOUSBDeviceInterface **gDevice = NULL;
static IOUSBInterfaceInterface **gInterface = NULL;
static UInt8 gBulkOut = 0;
static UInt8 gBulkIn  = 0;

/* ------------------------------------------------------------------ */
/* Cleanup                                                             */
/* ------------------------------------------------------------------ */

static void cleanup(void) {
    if (gInterface) {
        (*gInterface)->USBInterfaceClose(gInterface);
        (*gInterface)->Release(gInterface);
        gInterface = NULL;
    }
    if (gDevice) {
        (*gDevice)->USBDeviceClose(gDevice);
        (*gDevice)->Release(gDevice);
        gDevice = NULL;
    }
}

/* ------------------------------------------------------------------ */
/* Find and open the USB device                                        */
/* ------------------------------------------------------------------ */

static int open_device(UInt16 vid, UInt16 pid, const char *serial) {
    kern_return_t       kr;
    io_iterator_t       iter;
    io_service_t        svc;
    IOCFPlugInInterface **plug = NULL;
    SInt32              score;
    HRESULT             hr;

    const char *classes[] = {"IOUSBHostDevice", "IOUSBDevice", NULL};

    for (int ci = 0; classes[ci]; ci++) {
        CFMutableDictionaryRef match = IOServiceMatching(classes[ci]);
        if (!match) continue;

        CFNumberRef vidRef = CFNumberCreate(NULL, kCFNumberSInt32Type, &(SInt32){vid});
        CFNumberRef pidRef = CFNumberCreate(NULL, kCFNumberSInt32Type, &(SInt32){pid});
        CFDictionarySetValue(match, CFSTR("idVendor"),  vidRef);
        CFDictionarySetValue(match, CFSTR("idProduct"), pidRef);
        CFRelease(vidRef);
        CFRelease(pidRef);

        kr = IOServiceGetMatchingServices(kIOMasterPortDefault, match, &iter);
        if (kr != KERN_SUCCESS) continue;

        while ((svc = IOIteratorNext(iter))) {
            /* Optional serial filter */
            if (serial && serial[0]) {
                CFStringRef prop = IORegistryEntryCreateCFProperty(
                    svc, CFSTR("USB Serial Number"), NULL, 0);
                if (prop) {
                    char buf[256] = {0};
                    CFStringGetCString(prop, buf, sizeof(buf),
                                       kCFStringEncodingUTF8);
                    CFRelease(prop);
                    if (strcmp(buf, serial) != 0) {
                        IOObjectRelease(svc);
                        continue;
                    }
                }
            }
            IOObjectRelease(iter);

            kr = IOCreatePlugInInterfaceForService(
                svc, kIOUSBDeviceUserClientTypeID,
                kIOCFPlugInInterfaceID, &plug, &score);
            IOObjectRelease(svc);

            if (kr != KERN_SUCCESS || !plug) {
                fprintf(stderr, "ERR IOCreatePlugIn(device) 0x%08x\n", kr);
                return 2;
            }

            hr = (*plug)->QueryInterface(plug,
                CFUUIDGetUUIDBytes(kIOUSBDeviceInterfaceID),
                (LPVOID *)&gDevice);
            (*plug)->Release(plug);

            if (hr || !gDevice) {
                fprintf(stderr, "ERR QueryInterface(device) 0x%08x\n",(int)hr);
                return 2;
            }

            kr = (*gDevice)->USBDeviceOpen(gDevice);
            if (kr == kIOReturnExclusiveAccess) {
                fprintf(stderr, "ERR exclusive_access\n");
                return 2;
            }
            if (kr != kIOReturnSuccess) {
                fprintf(stderr, "ERR USBDeviceOpen 0x%08x\n", kr);
                return 2;
            }

            (*gDevice)->SetConfiguration(gDevice, 1);
            return 0;
        }
        IOObjectRelease(iter);
    }

    fprintf(stderr, "ERR device_not_found vid=0x%04x pid=0x%04x\n", vid, pid);
    return 2;
}

/* ------------------------------------------------------------------ */
/* Find the printer interface and locate bulk endpoints                 */
/* ------------------------------------------------------------------ */

static int open_interface(void) {
    kern_return_t       kr;
    io_iterator_t       iter;
    io_service_t        intfSvc;
    IOCFPlugInInterface **plug = NULL;
    SInt32              score;
    HRESULT             hr;

    /* Try printer-class first, then any class as fallback */
    UInt16 classFilter[] = {USB_PRINTER_CLASS, kIOUSBFindInterfaceDontCare};

    for (int fi = 0; fi < 2; fi++) {
        IOUSBFindInterfaceRequest req;
        req.bInterfaceClass    = classFilter[fi];
        req.bInterfaceSubClass = kIOUSBFindInterfaceDontCare;
        req.bInterfaceProtocol = kIOUSBFindInterfaceDontCare;
        req.bAlternateSetting  = kIOUSBFindInterfaceDontCare;

        kr = (*gDevice)->CreateInterfaceIterator(gDevice, &req, &iter);
        if (kr != kIOReturnSuccess) continue;

        while ((intfSvc = IOIteratorNext(iter))) {
            kr = IOCreatePlugInInterfaceForService(
                intfSvc, kIOUSBInterfaceUserClientTypeID,
                kIOCFPlugInInterfaceID, &plug, &score);
            IOObjectRelease(intfSvc);

            if (kr != KERN_SUCCESS || !plug) continue;

            hr = (*plug)->QueryInterface(plug,
                CFUUIDGetUUIDBytes(kIOUSBInterfaceInterfaceID),
                (LPVOID *)&gInterface);
            (*plug)->Release(plug);

            if (hr || !gInterface) continue;

            kr = (*gInterface)->USBInterfaceOpen(gInterface);
            if (kr != kIOReturnSuccess) {
                (*gInterface)->Release(gInterface);
                gInterface = NULL;
                continue;
            }

            /* Enumerate endpoints */
            UInt8 numEP = 0;
            (*gInterface)->GetNumEndpoints(gInterface, &numEP);
            fprintf(stderr, "INFO endpoints=%d\n", numEP);

            for (UInt8 p = 1; p <= numEP; p++) {
                UInt8  dir, num, xfer, intv;
                UInt16 maxpkt;
                (*gInterface)->GetPipeProperties(gInterface,
                    p, &dir, &num, &xfer, &maxpkt, &intv);
                fprintf(stderr, "INFO pipe=%d dir=%d type=%d maxpkt=%d\n",
                        p, dir, xfer, maxpkt);
                if (xfer == kUSBBulk) {
                    if (dir == kUSBOut && !gBulkOut) gBulkOut = p;
                    if (dir == kUSBIn  && !gBulkIn)  gBulkIn  = p;
                }
            }

            if (gBulkOut) {
                IOObjectRelease(iter);
                fprintf(stderr, "INFO bulk_out=%d bulk_in=%d\n",
                        gBulkOut, gBulkIn);
                return 0;
            }

            /* No bulk-out on this interface — try the next one */
            (*gInterface)->USBInterfaceClose(gInterface);
            (*gInterface)->Release(gInterface);
            gInterface = NULL;
            gBulkOut = gBulkIn = 0;
        }
        IOObjectRelease(iter);
    }

    fprintf(stderr, "ERR no_bulk_out_endpoint\n");
    return 3;
}

/* ------------------------------------------------------------------ */
/* Send data and optionally read status                                */
/* ------------------------------------------------------------------ */

static int send_data(const char *path) {
    FILE *f = fopen(path, "rb");
    if (!f) { fprintf(stderr, "ERR cannot_open %s\n", path); return 3; }

    fseek(f, 0, SEEK_END);
    long size = ftell(f);
    fseek(f, 0, SEEK_SET);

    unsigned char *buf = malloc(size);
    if (!buf) { fclose(f); return 3; }
    fread(buf, 1, size, f);
    fclose(f);

    kern_return_t kr = (*gInterface)->WritePipe(
        gInterface, gBulkOut, buf, (UInt32)size);
    free(buf);

    if (kr != kIOReturnSuccess) {
        fprintf(stderr, "ERR WritePipe 0x%08x\n", kr);
        return 3;
    }
    fprintf(stderr, "INFO wrote=%ld\n", size);

    /* Read status responses for up to ~2 seconds */
    if (gBulkIn) {
        for (int attempt = 0; attempt < 40; attempt++) {
            UInt8  sbuf[32];
            UInt32 slen = sizeof(sbuf);
            kr = (*gInterface)->ReadPipe(
                gInterface, gBulkIn, sbuf, &slen);
            if (kr == kIOReturnSuccess && slen > 0) {
                /* Hex-encode each status packet on its own line */
                for (UInt32 i = 0; i < slen; i++)
                    printf("%02x", sbuf[i]);
                printf("\n");
                fflush(stdout);
            }
            usleep(50000); /* 50 ms */
        }
    }

    return 0;
}

/* ------------------------------------------------------------------ */
/* main                                                                */
/* ------------------------------------------------------------------ */

int main(int argc, char *argv[]) {
    if (argc < 5 || strcmp(argv[1], "send") != 0) {
        fprintf(stderr,
            "Usage: usb_printer send <vid> <pid> <input_file> [serial]\n");
        return 1;
    }

    UInt16 vid = (UInt16)strtol(argv[2], NULL, 0);
    UInt16 pid = (UInt16)strtol(argv[3], NULL, 0);
    const char *input = argv[4];
    const char *serial = argc > 5 ? argv[5] : NULL;

    int rc = open_device(vid, pid, serial);
    if (rc) return rc;

    rc = open_interface();
    if (rc) { cleanup(); return rc; }

    rc = send_data(input);
    cleanup();
    return rc;
}
