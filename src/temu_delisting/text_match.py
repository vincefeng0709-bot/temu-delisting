"""这个站点的按钮文案经常在两个字中间插一个空格（比如"确 定"），用精确文字
匹配容易踩坑。这里提供一个"忽略空格"的正则，每个字符之间允许 0 个或多个
空白字符。
"""
from __future__ import annotations

import re


def loose_text(text: str) -> re.Pattern:
    """整串精确匹配（允许各字符间穿插空白），等价于原来的 exact=True 但能
    容忍"确 定"这种被插了空格的文案。"""
    escaped_chars = [re.escape(ch) for ch in text]
    pattern = r"^\s*" + r"\s*".join(escaped_chars) + r"\s*$"
    return re.compile(pattern)
