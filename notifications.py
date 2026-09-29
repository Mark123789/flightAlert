"""PushPlus 通知传输，返回可供界面展示的发送结果。"""

from dataclasses import dataclass
import logging

import requests

PUSHPLUS_URL = "https://www.pushplus.plus/send"
REQUEST_TIMEOUT = 25
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class NotificationResult:
    success: bool
    error: str = ""


def send_notification(message: str, token: str, *, post=None) -> NotificationResult:
    if not token:
        return NotificationResult(False, "未配置推送令牌")
    post = post or requests.post
    try:
        response = post(PUSHPLUS_URL,
                        json={"token": token, "title": "航班含税价格提醒", "content": message},
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
