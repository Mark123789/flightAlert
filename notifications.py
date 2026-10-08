"""PushPlus 通知传输，返回可供界面展示的发送结果。"""

from dataclasses import dataclass
import logging
from typing import Optional

import requests

PUSHPLUS_URL = "https://www.pushplus.plus/send"
REQUEST_TIMEOUT = 25
DEFAULT_TITLE = "航班含税价格提醒"
PRICE_INCREASE_TITLE = "航班含税价格涨价"
PRICE_DECREASE_TITLE = "航班含税价格降价"
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class NotificationResult:
    success: bool
    error: str = ""


def _title_for_message(message: str) -> str:
    if "含税日历价上涨" in message:
        return PRICE_INCREASE_TITLE
    if "含税日历价下降" in message:
        return PRICE_DECREASE_TITLE
    return DEFAULT_TITLE


def send_notification(message: str, token: str, *, title: Optional[str] = None,
                      post=None) -> NotificationResult:
    if not token:
        return NotificationResult(False, "未配置推送令牌")
    notification_title = title if title is not None else _title_for_message(message)
    post = post or requests.post
    try:
        response = post(PUSHPLUS_URL,
                        json={"token": token, "title": notification_title,
                              "content": message},
                        timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("PushPlus 返回格式无效")
        if data.get("code") != 200:
            # 仅显示业务码；不记录可能含敏感信息的完整响应。
            return NotificationResult(False, f"PushPlus 拒绝请求（业务码 {data.get('code')}）")
        return NotificationResult(True)
    except (requests.RequestException, ValueError) as exc:
        logger.warning("PushPlus 请求失败: %s", exc)
        return NotificationResult(False, str(exc))
