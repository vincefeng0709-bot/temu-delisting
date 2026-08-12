"""时间戳存的时候（accounts.py / remote_jobs.py 这些）统一用 UTC ISO 字符串，
这是对的——不同时区的机器（比如分机跟主机不在同一个地方）互相比较、排序
才不会乱。但界面上给人看的地方（创建时间、提交时间这些）如果直接把这个
UTC 字符串截一截拿去显示，会比同事自己电脑上的时钟慢了一个时区的偏移量，
看起来像是"这个时间不对"。这里统一转成本地时区再显示，存储那边不用改。
"""
from __future__ import annotations

from datetime import datetime


def format_local_time(iso_string: str) -> str:
    if not iso_string:
        return ""
    try:
        dt = datetime.fromisoformat(iso_string)
    except ValueError:
        return iso_string
    if dt.tzinfo is not None:
        dt = dt.astimezone()
    return dt.strftime("%Y-%m-%d %H:%M:%S")
