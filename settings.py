"""监控配置的规范化、校验和原子存储。"""

from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Optional

CHINA = timezone(timedelta(hours=8))
CABINS = {1: "经济舱", 2: "超级经济舱", 4: "商务舱", 8: "头等舱",
          3: "经济舱+超级经济舱", 12: "商务舱+头等舱"}


def normalize_date(value: str) -> str:
    """配置接受 YYYYMMDD 或 YYYY-MM-DD，统一保存为 YYYYMMDD。"""
    if not isinstance(value, str):
        raise ValueError("日期必须为 YYYYMMDD 或 YYYY-MM-DD 字符串")
    value = value.strip()
    if re.fullmatch(r"\d{8}", value):
        fmt = "%Y%m%d"
    elif re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        fmt = "%Y-%m-%d"
    else:
        raise ValueError(f"日期格式错误: {value}，应为 YYYYMMDD 或 YYYY-MM-DD")
    try:
        return datetime.strptime(value, fmt).strftime("%Y%m%d")
    except ValueError as exc:
        raise ValueError(f"无效日期: {value}") from exc


def display_date(day: str) -> str:
    return f"{day[:4]}-{day[4:6]}-{day[6:]}"


def normalize_config(config: dict, today: Optional[date] = None, *,
                     allow_expired: bool = False) -> dict:
    """兼容旧单程配置；往返必须明确指定一个固定返程日期。"""
    if not isinstance(config, dict):
        raise ValueError("配置必须是 JSON 对象")
    result = deepcopy(config)
    today = today or datetime.now(CHINA).date()
    raw_dates = result.get("dateToGo")
    if not isinstance(raw_dates, list) or not raw_dates:
        raise ValueError("dateToGo 必须是非空日期列表")
    result["dateToGo"] = sorted(set(normalize_date(day) for day in raw_dates))
    if not allow_expired and any(day < today.strftime("%Y%m%d") for day in result["dateToGo"]):
        raise ValueError("监控日期不能早于今天，请更新过期日期")
    for field in ("placeFrom", "placeTo"):
        value = result.get(field, "")
        if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9]{3,4}", value.strip()):
            raise ValueError(f"{field} 必须是 3–4 位城市代码，如 KMG、SHA")
        result[field] = value.strip().upper()
    if result["placeFrom"] == result["placeTo"]:
        raise ValueError("出发城市和到达城市不能相同")
    ways = {"oneway": "Oneway", "roundtrip": "Roundtrip"}
    way = result.get("flightWay", "Oneway")
    if not isinstance(way, str) or way.strip().lower() not in ways:
        raise ValueError("flightWay 必须为 Oneway 或 Roundtrip")
    result["flightWay"] = ways[way.strip().lower()]
    for field, default in (("sleepTime", 600), ("priceStep", 50),
                           ("searchType", 1), ("grade", 1)):
        value = result.get(field, default)
        if type(value) is not int or value <= 0:
            raise ValueError(f"{field} 必须为正整数")
        result[field] = value
    if result["searchType"] not in (1, 2):
        raise ValueError("searchType 必须为 1（国内）或 2（国际）")
    if result["grade"] not in CABINS:
        raise ValueError("grade 必须为 1、2、3、4、8 或 12")
    if result["flightWay"] == "Roundtrip":
        if not result.get("returnDate"):
            raise ValueError("往返监控必须填写 returnDate（固定返程日期）")
        result["returnDate"] = normalize_date(result["returnDate"])
        if result["returnDate"] < max(result["dateToGo"]):
            raise ValueError("返程日期不能早于任何监控出发日期")
    else:
        result["returnDate"] = ""
    passengers = result.get("passengerList", [{"passengerType": "Adult", "passengerCount": 1}])
    if not isinstance(passengers, list) or not passengers:
        raise ValueError("passengerList 必须为非空列表")
    counts = {}
    for item in passengers:
        if not isinstance(item, dict):
            raise ValueError("乘客配置必须是对象")
        kind, count = item.get("passengerType"), item.get("passengerCount")
        if not isinstance(kind, str) or kind not in ("Adult", "Child", "Baby") or kind in counts:
            raise ValueError("乘客类型必须为不重复的 Adult、Child、Baby")
        if type(count) is not int or count < 0:
            raise ValueError("乘客人数必须是非负整数")
        counts[kind] = count
    if counts.get("Adult", 0) < 1:
        raise ValueError("至少需要 1 位成人")
    if result["searchType"] == 1 and (counts.get("Adult") != 1 or
                                      counts.get("Child", 0) or counts.get("Baby", 0)):
        raise ValueError("国内日历查询使用 1 成人；儿童和婴儿配置仅用于国际查询")
    result["passengerList"] = [{"passengerType": kind, "passengerCount": counts[kind]}
                               for kind in ("Adult", "Child", "Baby") if counts.get(kind)]
    token = result.get("SCKEY", "")
    if not isinstance(token, str):
        raise ValueError("SCKEY 必须为字符串")
    result["SCKEY"] = token.strip()
    return result


def load_config(path, *, allow_expired=False, today=None) -> dict:
    with open(path, encoding="utf-8") as file:
        return normalize_config(json.load(file), today=today, allow_expired=allow_expired)


def save_config(path, config: dict) -> dict:
    """先完整写入同目录临时文件，再替换原配置；失败时清理临时文件。"""
    config = normalize_config(config, allow_expired=True)
    path = Path(path)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=f".{path.name}.", suffix=".tmp",
                                         delete=False) as file:
            temporary = Path(file.name)
            json.dump(config, file, indent=4, ensure_ascii=False)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return config
