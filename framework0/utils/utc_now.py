from datetime import datetime
from zoneinfo import ZoneInfo


BEIJING_TZ = ZoneInfo("Asia/Shanghai")


def utc_now() -> datetime:  # 定义函数：获取当前北京时间
    return datetime.now(BEIJING_TZ)  # 返回带北京时间时区信息的当前时间
