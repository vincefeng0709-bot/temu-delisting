from pathlib import Path

import pytest

from temu_delisting.account_import import IMPORT_FORMAT_HELP, parse_account_excel


def _write_workbook(path: Path, rows: list[list]) -> None:
    from openpyxl import Workbook

    workbook = Workbook()
    sheet = workbook.active
    for row in rows:
        sheet.append(row)
    workbook.save(path)


def test_parses_real_world_example(tmp_path):
    path = tmp_path / "accounts.xlsx"
    _write_workbook(
        path,
        [
            ["账号", "店铺数量", "全托管", "半托管", "店铺编号", "店铺名称"],
            ["19101569761", 2, 1, 1, "店铺01-01~02", "SaveNset、Shopping"],
            ["13207278392", 8, 8, 0, "店铺02-01~08", "Vsasd、LLA、asda、djien、MLBB、XCNM、Bash、ASD"],
            ["15673424356", 3, 0, 3, "店铺03-01~03", "hdua、Hsuc、JJM"],
        ],
    )

    result = parse_account_excel(path)

    assert not result.issues
    assert len(result.shops) == 13
    assert result.shops[0].display_name == "SaveNset"
    assert result.shops[0].mall_name == "SaveNset"
    assert "19101569761" in result.shops[0].notes
    assert "该手机号下共 2 个店铺" in result.shops[0].notes
    assert result.shops[1].display_name == "Shopping"
    assert {s.display_name for s in result.shops[-3:]} == {"hdua", "Hsuc", "JJM"}


def test_flags_mismatched_shop_count(tmp_path):
    path = tmp_path / "accounts.xlsx"
    _write_workbook(
        path,
        [
            ["账号", "店铺数量", "全托管", "半托管", "店铺编号", "店铺名称"],
            ["19101569761", 3, 1, 1, "店铺01-01~03", "SaveNset、Shopping"],
        ],
    )

    result = parse_account_excel(path)

    assert len(result.shops) == 2
    assert len(result.issues) == 1
    assert "3" in result.issues[0].message and "2" in result.issues[0].message


def test_skips_blank_rows(tmp_path):
    path = tmp_path / "accounts.xlsx"
    _write_workbook(
        path,
        [
            ["账号", "店铺数量", "全托管", "半托管", "店铺编号", "店铺名称"],
            ["19101569761", 1, 1, 0, "店铺01-01", "SaveNset"],
            [None, None, None, None, None, None],
            ["13207278392", 1, 0, 1, "店铺02-01", "Vsasd"],
        ],
    )

    result = parse_account_excel(path)

    assert not result.issues
    assert len(result.shops) == 2


def test_raises_when_required_columns_missing(tmp_path):
    path = tmp_path / "accounts.xlsx"
    _write_workbook(path, [["账号", "店铺数量"], ["19101569761", 1]])

    with pytest.raises(ValueError, match="店铺名称"):
        parse_account_excel(path)


def test_custom_notes_column_preserved_ahead_of_auto_notes(tmp_path):
    path = tmp_path / "accounts.xlsx"
    _write_workbook(
        path,
        [
            ["账号", "店铺数量", "全托管", "半托管", "店铺编号", "店铺名称", "备注"],
            ["19101569761", 1, 1, 0, "店铺01-01", "SaveNset", "小王负责，2026年交接"],
        ],
    )

    result = parse_account_excel(path)

    assert result.shops[0].notes.startswith("小王负责，2026年交接")
    assert "该手机号下共 1 个店铺" in result.shops[0].notes


def test_missing_custom_notes_column_still_works(tmp_path):
    path = tmp_path / "accounts.xlsx"
    _write_workbook(
        path,
        [
            ["账号", "店铺数量", "店铺名称"],
            ["19101569761", 1, "SaveNset"],
        ],
    )

    result = parse_account_excel(path)

    assert not result.issues
    assert result.shops[0].notes  # 没有自定义备注列时，自动生成的备注照常存在


def test_import_format_help_mentions_no_passwords():
    assert "密码" in IMPORT_FORMAT_HELP


def test_handles_comma_and_slash_separators(tmp_path):
    path = tmp_path / "accounts.xlsx"
    _write_workbook(
        path,
        [
            ["账号", "店铺数量", "全托管", "半托管", "店铺编号", "店铺名称"],
            ["19101569761", 3, 3, 0, "店铺01-01~03", "SaveA, SaveB/SaveC"],
        ],
    )

    result = parse_account_excel(path)

    assert not result.issues
    assert [s.display_name for s in result.shops] == ["SaveA", "SaveB", "SaveC"]
