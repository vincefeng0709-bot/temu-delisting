from temu_delisting_satellite.widgets.main_window import _format_summary


def test_format_summary_scan_result():
    result = {"status": "completed", "total_from_page": 10, "raw_row_count": 12, "unique_spu_count": 8}
    summary = _format_summary(result)
    assert "抓取 12 条" in summary
    assert "8 个不同 SPU" in summary


def test_format_summary_apply_result():
    result = {"status": "completed", "skc_success": 5, "skc_needs_follow_up": 2}
    summary = _format_summary(result)
    assert "下架成功 5" in summary
    assert "需人工跟进 2" in summary


def test_format_summary_failed_result():
    result = {"status": "failed", "message": "账号未找到"}
    assert _format_summary(result) == "失败：账号未找到"


def test_format_summary_empty_scan_note():
    result = {"status": "completed", "confirmed_count": 0, "note": "扫描结果为空，未执行下架"}
    assert _format_summary(result) == "扫描结果为空，未执行下架"
