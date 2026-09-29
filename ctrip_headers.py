"""携程微信小程序风格的匿名请求头，不包含会话或设备凭据。"""

# AppID 和 Referer 版本路径参考公开请求样本，不表示当前小程序版本：
# https://github.com/fy658/ctrip-Mini-program-scrawler/blob/main/wechat_ctrip_api.md
# User-Agent 模拟 Android 微信环境，不是从用户设备采集的实际标识。
HEADERS = {
    "Content-Type": "application/json",
    "Accept": "*/*",
    "Referer": "https://servicewechat.com/wx0e6ed4f51db9d078/1022/page-frame.html",
    "x-ctx-currency": "CNY",
    "x-ctx-locale": "zh-CN",
    "x-ctx-region": "CN",
    "x-ctx-group": "ctrip",
    "User-Agent": (
        "Mozilla/5.0 (Linux; Android 14; wv) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Version/4.0 Chrome/112.0.5615.136 "
        "Mobile Safari/537.36 MicroMessenger/8.0.49 NetType/WIFI "
        "Language/zh_CN miniProgram/wx0e6ed4f51db9d078"
    ),
}
