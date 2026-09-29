"""CLI 和 GUI 共用的日志配置。"""

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import sys


def configure_logging(directory, *, console=False) -> Path:
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "flight_alert.log"
    handlers = [RotatingFileHandler(path, maxBytes=2_000_000, backupCount=3,
                                   encoding="utf-8")]
    if console and sys.stdout is not None:
        handlers.append(logging.StreamHandler(sys.stdout))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    # 重复初始化时只替换本程序的处理器，不干扰测试或宿主的日志配置。
    for handler in root.handlers[:]:
        if getattr(handler, "_flight_alert", False):
            root.removeHandler(handler)
            handler.close()
    for handler in handlers:
        handler._flight_alert = True
        handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
        root.addHandler(handler)
    return path
