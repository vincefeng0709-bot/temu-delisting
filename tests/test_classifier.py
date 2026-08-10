from temu_delisting.classifier import DELIST_SUGGESTED, NEEDS_HUMAN_REVIEW, classify

KNOWN = ["知识产权违规", "内容信息违规", "违反禁售政策", "重复铺货"]


def test_known_type_is_delist_suggested():
    assert classify("知识产权违规", KNOWN) == DELIST_SUGGESTED


def test_unknown_type_needs_human_review():
    assert classify("某种从没见过的新违规类型", KNOWN) == NEEDS_HUMAN_REVIEW


def test_whitespace_is_trimmed():
    assert classify("  重复铺货  ", KNOWN) == DELIST_SUGGESTED


def test_empty_known_list_always_needs_review():
    assert classify("知识产权违规", []) == NEEDS_HUMAN_REVIEW
