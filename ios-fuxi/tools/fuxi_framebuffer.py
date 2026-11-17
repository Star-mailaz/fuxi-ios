import time

import usb.core


def read_framebuffer_bytes(request, height, reconnect):
    if not 150 <= height <= 2400:
        raise ValueError('framebuffer height outside the validated window')
    size = 1080 * height * 4
    raw = bytearray()
    retries = 0
    began = time.monotonic()
    while len(raw) < size:
        offset = len(raw)
        length = min(512, size - offset)
        try:
            chunk = request(0x4e, length, offset & 0xffff, offset >> 16)
        except usb.core.USBError:
            if retries == 2:
                raise
            retries += 1
            print(f'[FRAMEBUFFER] USB drop at {offset}/{size} bytes after '
                  f'{time.monotonic() - began:.1f}s; reconnect {retries}/2', flush=True)
            reconnect()
            continue
        if len(chunk) != length:
            raise ValueError(f'short framebuffer response at {offset}/{size} bytes')
        raw.extend(chunk)
    print(f'[FRAMEBUFFER] read {size} bytes in {time.monotonic() - began:.1f}s; '
          f'reconnects={retries}', flush=True)
    return raw
