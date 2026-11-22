"""A folder-change signal: "something in this folder changed", without listing it.

The mirror watcher used to wake on a timer, list the whole folder and stat every
file whether or not anything had happened. On Windows the kernel can say so
instead: ``FindFirstChangeNotificationW`` hands back a handle that becomes
signalled when a file in the folder is created, removed, renamed, resized or
written. A thread parked on that handle uses no CPU until then.

The signal carries no detail (which file, what happened) and may fire for the
caller's own writes; the caller re-reads the folder when it fires. Where the
kernel call is unavailable (another OS, an unopenable folder) ``available`` is
False and the caller keeps its timer: no signal is never read as "no change".
"""

from __future__ import annotations

import logging
import sys
import threading
from collections.abc import Callable
from pathlib import Path

logger = logging.getLogger(__name__)

# winnt.h: file created / removed / renamed, a size change, a last-write change.
_FILTER = 0x1 | 0x8 | 0x10
_INFINITE = 0xFFFFFFFF
_WAIT_OBJECT_0 = 0


class DirChangeSignal:
    """Calls ``on_change()`` from a background thread each time the folder changes."""

    def __init__(self, directory: Path, on_change: Callable[[], None]) -> None:
        self._on_change = on_change
        self._thread: threading.Thread | None = None
        self._k32 = None
        self._handle = None
        self._stop_event = None
        self.available = False
        if sys.platform != "win32":
            return
        try:
            self._open(directory)
        except Exception as exc:  # noqa: BLE001 — any failure means "no signal", never a crash
            logger.warning("⚠️ change signal unavailable for %s (%s: %s) — falling back to polling",
                           directory, type(exc).__name__, exc)
            self._release()

    def _open(self, directory: Path) -> None:
        import ctypes
        from ctypes import wintypes

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.FindFirstChangeNotificationW.restype = wintypes.HANDLE
        k32.FindFirstChangeNotificationW.argtypes = [wintypes.LPCWSTR, wintypes.BOOL, wintypes.DWORD]
        k32.FindNextChangeNotification.argtypes = [wintypes.HANDLE]
        k32.FindNextChangeNotification.restype = wintypes.BOOL
        k32.FindCloseChangeNotification.argtypes = [wintypes.HANDLE]
        k32.CreateEventW.restype = wintypes.HANDLE
        k32.CreateEventW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
        k32.SetEvent.argtypes = [wintypes.HANDLE]
        k32.CloseHandle.argtypes = [wintypes.HANDLE]
        k32.WaitForMultipleObjects.argtypes = [
            wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE), wintypes.BOOL, wintypes.DWORD,
        ]
        k32.WaitForMultipleObjects.restype = wintypes.DWORD
        handle = k32.FindFirstChangeNotificationW(str(directory), False, _FILTER)
        if handle is None or handle == ctypes.c_void_p(-1).value:
            raise OSError(f"FindFirstChangeNotificationW failed (error {ctypes.get_last_error()})")
        self._k32 = k32
        self._handle = handle
        self._stop_event = k32.CreateEventW(None, True, False, None)
        self.available = True

    def start(self) -> None:
        if not self.available or self._thread is not None:
            return
        self._thread = threading.Thread(target=self._loop, name="task-os-dir-change", daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        from ctypes import wintypes

        k32 = self._k32
        handles = (wintypes.HANDLE * 2)(self._handle, self._stop_event)
        while True:
            # Parked in the kernel until the folder changes or stop() sets the event.
            which = k32.WaitForMultipleObjects(2, handles, False, _INFINITE)
            if which != _WAIT_OBJECT_0:
                return
            k32.FindNextChangeNotification(self._handle)  # re-arm before telling anyone
            try:
                self._on_change()
            except Exception:  # noqa: BLE001
                logger.exception("❌ change signal callback failed")

    def stop(self) -> None:
        if self._thread is not None and self._stop_event is not None:
            self._k32.SetEvent(self._stop_event)
            self._thread.join(timeout=5)
            self._thread = None
        self._release()

    def _release(self) -> None:
        if self._k32 is not None:
            if self._handle is not None:
                self._k32.FindCloseChangeNotification(self._handle)
            if self._stop_event is not None:
                self._k32.CloseHandle(self._stop_event)
        self._handle = self._stop_event = None
        self.available = False
