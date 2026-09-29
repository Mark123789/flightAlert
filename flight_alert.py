"""命令行机票含税日历价格监控。"""

import argparse
import logging
from pathlib import Path
import sys
from threading import Event

from app_logging import configure_logging
from locations import get_readable_location
from monitoring import MonitorService, run_monitor
from settings import CABINS, display_date, load_config

config_path = Path(__file__).resolve().with_name("config.json")
logger = logging.getLogger(__name__)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="携程含税日历价格监控")
    parser.add_argument("--config", type=Path, default=config_path, help="配置文件路径")
    parser.add_argument("--once", action="store_true", help="只查询一轮后退出")
    parser.add_argument("--no-notify", action="store_true", help="本次运行不发送通知")
    args = parser.parse_args(argv)
    stop_event = Event()
    try:
        log_path = configure_logging(args.config.resolve().parent, console=True)
        config = load_config(args.config)
        if args.no_notify:
            config["SCKEY"] = ""
        origin = get_readable_location(config["placeFrom"])
        destination = get_readable_location(config["placeTo"])
        logger.info("日志文件: %s", log_path)
        logger.info("监控路线: %s → %s；%s；%s；CNY 含税日历价", origin, destination,
                    "国内" if config["searchType"] == 1 else "国际", CABINS[config["grade"]])
        if config["flightWay"] == "Roundtrip":
            logger.info("固定返程日期: %s", display_date(config["returnDate"]))

        def handle_event(event):
            if event.kind == "finished":
                logger.info(event.data)

        return run_monitor(MonitorService(config), stop_event, handle_event, once=args.once)
    except KeyboardInterrupt:
        stop_event.set()
        logger.info("监控已停止")
        return 0
    except (OSError, ValueError) as exc:
        logger.error("配置或运行失败: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
