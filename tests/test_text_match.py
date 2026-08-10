from temu_delisting.text_match import loose_text


def test_matches_plain_text():
    assert loose_text("查询").fullmatch("查询")


def test_matches_text_with_inserted_space():
    assert loose_text("确定").fullmatch("确 定")


def test_matches_text_with_surrounding_whitespace():
    assert loose_text("查询").fullmatch("  查询  ")


def test_does_not_match_different_text():
    assert loose_text("查询").fullmatch("重置") is None


def test_does_not_match_substring_of_longer_text():
    assert loose_text("客服").fullmatch("客服中心") is None
