"""把仍在 iOS 的手機的監看程式重置倒數改成 N 分鐘後（預設 1），讓它自行重開回 Android。

用法：python reset-soon.py [分鐘 1-60]
用的是 fuxi-xnu-monitor.py 同一個 USB 請求（0x54，PSCI reset deadline = now + N min），只送這一個請求，不讀寫其他東西。
"""
import sys
from pathlib import Path

import usb.backend.libusb1
import usb.core

minutes = int(sys.argv[1]) if len(sys.argv) > 1 else 1
assert 1 <= minutes <= 60
backend = None
try:
    import libusb_package
    backend = libusb_package.get_libusb1_backend()
except Exception:
    pass
if backend is None:
    dll = Path(r'D:\xiaomi13\fuxi_ios\libusb-1.0.dll')
    if dll.exists():
        backend = usb.backend.libusb1.get_backend(find_library=lambda x: str(dll))
devices = list(usb.core.find(find_all=True, idVendor=0x1209, idProduct=0x0001, backend=backend))
if len(devices) != 1:
    sys.exit(f'expected one Fuxi monitor device, found {len(devices)}')
dev = devices[0]
data = bytes(dev.ctrl_transfer(0xc0, 0x46, 0, 0, 88, timeout=3000))
if data[:8] != b'FXIMON01':
    sys.exit('not the Fuxi native monitor protocol')
dev.ctrl_transfer(0xc0, 0x54, minutes, 0, 8, timeout=3000)
print(f'reset deadline set to +{minutes} min')
