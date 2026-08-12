from temu_delisting_gui.time_format import format_local_time


def test_empty_string_returns_empty():
    assert format_local_time("") == ""


def test_malformed_string_returned_as_is():
    assert format_local_time("not a timestamp") == "not a timestamp"


def test_utc_iso_string_converts_to_local_time():
    # UTC 零点转成本地时间，日期/小时应该跟着时区偏移量变化（不再是原样
    # 截断显示 UTC 时间），格式统一成 "YYYY-MM-DD HH:MM:SS"。
    result = format_local_time("2026-08-13T00:00:00+00:00")
    assert len(result) == 19
    assert result[4] == "-" and result[7] == "-" and result[10] == " "


def test_naive_iso_string_left_unconverted():
    # 没有时区信息的字符串没法判断要不要转换，原样格式化，不瞎猜。
    assert format_local_time("2026-08-13T09:30:00") == "2026-08-13 09:30:00"
