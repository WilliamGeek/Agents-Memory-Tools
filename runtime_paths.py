"""运行路径与环境适配层。

目标：同一份代码既能从源码目录运行，也能在 PyInstaller / Tauri sidecar
冻结后运行；程序资源只读，用户数据写到独立可写目录。

优先级：
1. ``MEMORY_TOOLS_DATA_DIR`` 环境变量；
2. 冻结运行：``%LOCALAPPDATA%\\AgentsMemoryTools``；
3. 源码运行：仓库根目录（保持现有开发体验与历史缓存位置）。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "AgentsMemoryTools"


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def resource_dir() -> Path:
    """只读资源根目录：源码根目录或 PyInstaller 的 ``_MEIPASS``。"""
    if is_frozen():
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return Path(meipass).resolve()
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def user_home() -> Path:
    return Path(os.environ.get("USERPROFILE") or Path.home()).resolve()


def roaming_dir() -> Path:
    return Path(
        os.environ.get("APPDATA") or (user_home() / "AppData" / "Roaming")
    ).resolve()


def local_app_data_dir() -> Path:
    return Path(
        os.environ.get("LOCALAPPDATA") or (user_home() / "AppData" / "Local")
    ).resolve()


def data_dir() -> Path:
    override = (os.environ.get("MEMORY_TOOLS_DATA_DIR") or "").strip()
    if override:
        return Path(override).expanduser().resolve()
    if is_frozen():
        return local_app_data_dir() / APP_NAME
    return resource_dir()


RESOURCE_DIR = resource_dir()
DATA_DIR = data_dir()


def ensure_runtime_dirs() -> None:
    """创建所有可写目录；只创建目录，不触碰用户会话源文件。"""
    for path in (
        DATA_DIR,
        DATA_DIR / "cache",
        DATA_DIR / "exports",
        DATA_DIR / "logs",
        DATA_DIR / "tiktoken_cache",
        DATA_DIR / "tools" / "dbkey" / "out",
    ):
        path.mkdir(parents=True, exist_ok=True)


# 常用路径的显式命名，避免业务代码继续散落 resource/data 语义。
FRONTEND_OUT_DIR = RESOURCE_DIR / "frontend" / "out"
TOOLS_DIR = RESOURCE_DIR / "tools"
CACHE_DIR = DATA_DIR / "cache"
EXPORT_DIR = DATA_DIR / "exports"
LOG_DIR = DATA_DIR / "logs"
TIKTOKEN_CACHE_DIR = DATA_DIR / "tiktoken_cache"
TOKEN_CACHE_PATH = DATA_DIR / "token_cache.json"
TRAE_PLAIN_DB = DATA_DIR / "tools" / "dbkey" / "out" / "trae_database_plain.db"


def home_path(*parts: str) -> Path:
    return user_home().joinpath(*parts)


def roaming_path(*parts: str) -> Path:
    return roaming_dir().joinpath(*parts)


def local_path(*parts: str) -> Path:
    return local_app_data_dir().joinpath(*parts)


def resource_path(*parts: str) -> Path:
    return RESOURCE_DIR.joinpath(*parts)
