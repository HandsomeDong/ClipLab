from __future__ import annotations

from cliplab_backend.services.download_utils import build_output_path, extract_urls, sanitize_title
from cliplab_backend.services.resolver import extract_share_url


def test_extract_share_url_from_douyin_share_text():
    text = (
        "8.28 复制打开抖音，看看【七里翔的作品】三幻神 # 燃 # 帅 # 萌 # 剪映  "
        "https://v.douyin.com/LiTfOh80l2A/ Kjc:/ 01/04 h@b.AG"
    )

    assert extract_share_url(text) == "https://v.douyin.com/LiTfOh80l2A/"


def test_extract_share_url_from_kuaishou_share_text():
    text = (
        'https://v.kuaishou.com/KvGL1atJ 神降 "圆头耄耋 "整活 "抽象 "壁纸 '
        "该作品在快手被播放过4.8万次，点击链接，打开【快手】直接观看！"
    )

    assert extract_share_url(text) == "https://v.kuaishou.com/KvGL1atJ"


def test_extract_urls_trims_trailing_punctuation():
    text = "看这个链接：https://v.kuaishou.com/KvGL1atJ！！！"

    assert extract_urls(text) == ["https://v.kuaishou.com/KvGL1atJ"]


def test_sanitize_title_keeps_short_chinese_title():
    assert sanitize_title("禅者行脚") == "禅者行脚"


def test_sanitize_title_truncates_after_tenth_chinese_character():
    assert sanitize_title("神降圆头耄耋整活抽象壁纸后面还有内容") == "神降圆头耄耋整活抽象"


def test_sanitize_title_truncates_without_trailing_symbols_after_tenth_chinese_character():
    assert sanitize_title("神降 #圆头耄耋 #整活 #抽象 #壁纸") == "神降 #圆头耄耋 #整活 #抽象"


def test_sanitize_title_falls_back_after_cleaning_special_chars():
    assert sanitize_title('  <>:"/\\\\?*  ') == ""


def test_build_output_path_avoids_overwriting_existing_files(tmp_path):
    first = build_output_path(str(tmp_path), "三幻神", "douyin_123")
    first.write_bytes(b"demo")

    second = build_output_path(str(tmp_path), "三幻神", "douyin_123")

    assert first.name == "三幻神.mp4"
    assert second.name == "三幻神 (2).mp4"
