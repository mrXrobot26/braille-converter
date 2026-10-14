"""Find USB sticks (removable drives) on Windows, with their volume labels."""
from __future__ import annotations

import sys

DRIVE_REMOVABLE = 2
SEM_FAILCRITICALERRORS = 0x0001
SEM_NOOPENFILEERRORBOX = 0x8000


def removable_drives():
    """[(root, label)] such as [("E:\\", "KINGSTON")]. Empty drives are skipped."""
    if sys.platform != "win32":
        return []
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetLogicalDrives.restype = wintypes.DWORD
    kernel32.GetDriveTypeW.argtypes = [wintypes.LPCWSTR]
    kernel32.GetDriveTypeW.restype = wintypes.UINT
    kernel32.GetVolumeInformationW.argtypes = [
        wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
        ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.DWORD), wintypes.LPWSTR,
        wintypes.DWORD]
    kernel32.GetVolumeInformationW.restype = wintypes.BOOL

    # no "insert a disk" system pop-ups for empty card readers
    old_mode = wintypes.DWORD(0)
    has_thread_mode = hasattr(kernel32, "SetThreadErrorMode")
    if has_thread_mode:
        kernel32.SetThreadErrorMode(SEM_FAILCRITICALERRORS | SEM_NOOPENFILEERRORBOX,
                                    ctypes.byref(old_mode))
    drives = []
    try:
        mask = kernel32.GetLogicalDrives()
        for i in range(26):
            if not mask & (1 << i):
                continue
            root = f"{chr(ord('A') + i)}:\\"
            if kernel32.GetDriveTypeW(root) != DRIVE_REMOVABLE:
                continue
            label = ctypes.create_unicode_buffer(261)
            fs_name = ctypes.create_unicode_buffer(261)
            serial, max_len, flags = wintypes.DWORD(), wintypes.DWORD(), wintypes.DWORD()
            ok = kernel32.GetVolumeInformationW(root, label, 261, ctypes.byref(serial),
                                                ctypes.byref(max_len), ctypes.byref(flags),
                                                fs_name, 261)
            if not ok:  # card reader without a card, etc.
                continue
            drives.append((root, label.value.strip()))
    finally:
        if has_thread_mode:
            kernel32.SetThreadErrorMode(old_mode.value, None)
    return drives


def drive_title(root, label):
    """«فلاشة KINGSTON (E:)» for the save dialog."""
    letter = root.rstrip("\\")
    return f"فلاشة {label} ({letter})" if label else f"فلاشة ({letter})"
