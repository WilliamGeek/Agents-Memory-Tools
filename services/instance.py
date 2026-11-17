"""单实例锁与本地服务复用。

Windows 优先使用命名 mutex（进程退出自动释放，不会残留锁文件）；其他平台
使用排他锁文件作为降级。这里不杀任何已有进程：同一客户端再次启动时直接
复用已有服务，端口被其他软件占用则明确失败。
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wintypes
import os
import time
from pathlib import Path
from typing import Any

ERROR_ALREADY_EXISTS = 183


class InstanceGuard:
    def __init__(self, handle: Any = None, lock_path: Path | None = None) -> None:
        self._handle = handle
        self._lock_path = lock_path

    def close(self) -> None:
        if self._handle is not None:
            try:
                ctypes.windll.kernel32.CloseHandle(self._handle)
            except Exception:
                pass
            self._handle = None
        if self._lock_path is not None:
            try:
                self._lock_path.unlink()
            except Exception:
                pass
            self._lock_path = None


def acquire_instance_lock(name: str, data_dir: Path) -> InstanceGuard | None:
    """尝试获取单实例锁；已有实例时返回 None。"""
    if os.name == "nt":
        kernel32 = ctypes.windll.kernel32
        kernel32.CreateMutexW.argtypes = [
            wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR
        ]
        kernel32.CreateMutexW.restype = wintypes.HANDLE
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        kernel32.GetLastError.restype = wintypes.DWORD

        handle = kernel32.CreateMutexW(None, False, f"Local\\{name}")
        if not handle:
            raise OSError("CreateMutexW failed")
        if kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
            kernel32.CloseHandle(handle)
            return None
        return InstanceGuard(handle=handle)

    lock_path = data_dir / f".{name}.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_RDWR)
    except FileExistsError:
        # 仅处理明显陈旧的锁；仍不删除活跃进程的锁。
        try:
            if time.time() - lock_path.stat().st_mtime > 6 * 3600:
                lock_path.unlink(missing_ok=True)
                fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_RDWR)
            else:
                return None
        except OSError:
            return None
    os.write(fd, str(os.getpid()).encode("ascii"))
    os.close(fd)
    return InstanceGuard(lock_path=lock_path)
