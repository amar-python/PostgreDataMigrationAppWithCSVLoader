"""What the upload screen does with a file and what it sends (streamlit_app/upload_model.py).

The edge cases the screen must get right before anything is sent: the size limit (a file exactly at it, one byte over,
a byte-order mark), a file that is not UTF-8 (refused, not silently changed), an empty file, a name that is not .csv;
and the request bodies: a new table sends the confirmed types and only the renames, a Test and Evaluation load
sends neither (the API answers 422 to either there).
"""
import base64
import tomllib

import pytest

from tests.unit.streamlit_harness import APP_DIR

import upload_model as u  # noqa: E402

pytestmark = [pytest.mark.unit, pytest.mark.regression]

LIMIT = 100


def _prep(name="a.csv", raw=b"id,name\n1,x\n", limit=LIMIT):
    return u.prepare(name, raw, limit)


# ── prepare ───────────────────────────────────────────────────────────────────────────────

def test_a_good_file_is_decoded_and_keeps_its_original_bytes():
    p = _prep(raw="id,name\n1,café\n".encode("utf-8"))

    assert p.text == "id,name\n1,café\n" and p.raw == "id,name\n1,café\n".encode("utf-8") and p.name == "a.csv"
    assert len(p.digest) == 12


def test_a_byte_order_mark_is_dropped_from_the_text_but_kept_in_the_original():
    raw = b"\xef\xbb\xbfid,name\n1,x\n"

    p = _prep(raw=raw)

    assert p.text.startswith("id,name") and p.raw == raw, "else the first header would be '\\ufeffid'"


def test_a_file_exactly_at_the_limit_is_accepted_and_one_byte_over_is_refused_with_the_limit_in_the_message():
    assert _prep(raw=b"a" * 100, limit=100).text == "a" * 100

    with pytest.raises(u.Refused) as e:
        _prep("big.csv", b"a" * 101, limit=100)

    assert e.value.name == "big.csv" and "101 B" in e.value.reason and "100 B limit" in e.value.reason


def test_the_limit_counts_the_text_not_a_byte_order_mark():
    assert _prep(raw=b"\xef\xbb\xbf" + b"a" * 100, limit=100).text == "a" * 100


def test_the_limit_is_the_apis_own_variable_read_when_used(monkeypatch):
    monkeypatch.setenv("MAX_UPLOAD_BYTES", "10")

    assert u.max_bytes() == 10
    with pytest.raises(u.Refused):
        u.prepare("a.csv", b"a" * 11)
    monkeypatch.delenv("MAX_UPLOAD_BYTES")
    assert u.max_bytes() == 50 * 1024 * 1024


def test_a_file_that_is_not_utf8_is_refused_not_quietly_changed():
    with pytest.raises(u.Refused) as e:
        _prep("latin.csv", "name\n\xe9t\xe9\n".encode("latin-1"))

    assert "not UTF-8" in e.value.reason and "position 5" in e.value.reason and "Save the file as UTF-8" in e.value.reason


def test_an_empty_file_and_a_wrong_extension_are_refused():
    with pytest.raises(u.Refused, match="is empty"):
        _prep("a.csv", b"")
    with pytest.raises(u.Refused, match="not a .csv file"):
        _prep("notes.txt", b"a,b\n")


def test_the_extension_check_ignores_case():
    assert _prep("DATA.CSV").name == "DATA.CSV"


def test_a_refusal_keeps_the_name_apart_from_the_reason_so_the_name_can_be_quoted():
    with pytest.raises(u.Refused) as e:
        _prep("[x](http://y.test).txt", b"a")

    assert e.value.name == "[x](http://y.test).txt" and not e.value.reason.startswith("[x]")


@pytest.mark.parametrize("n, text", [(0, "0 B"), (1023, "1023 B"), (1024, "1.0 KB"), (1536, "1.5 KB"),
                                     (1_048_576, "1.00 MB"), (52_428_800, "50.00 MB")])
def test_sizes_are_worded_as_the_react_app_words_them(n, text):
    assert u.format_bytes(n) == text


# ── the preview reads only the start of a big file ────────────────────────────────────────

def test_a_small_file_is_previewed_whole():
    p = _prep()

    assert u.preview_text(p, limit=1000) == (p.text, False)


def test_a_big_file_is_cut_at_a_line_end_so_no_row_is_half_read():
    p = _prep(raw=b"id,name\n" + b"1,abcdefgh\n" * 50, limit=10_000)

    text, truncated = u.preview_text(p, limit=100)

    assert truncated and text.endswith("\n") and len(text.encode()) <= 100
    assert all(line.count(",") == 1 for line in text.splitlines())


def test_a_cut_through_a_multibyte_character_without_a_line_end_does_not_raise():
    p = _prep(raw=("é" * 100).encode("utf-8"), limit=1000)

    text, truncated = u.preview_text(p, limit=51)  # 51 bytes: the last character is cut in half

    assert truncated and set(text) == {"é"}


def test_a_byte_order_mark_is_not_in_the_preview():
    p = _prep(raw=b"\xef\xbb\xbfid\n1\n", limit=1000)

    assert u.preview_text(p, limit=1000)[0].startswith("id")


def test_rows_are_estimated_from_the_part_that_was_read_only_when_it_was_cut():
    assert u.approx_rows(40, 1000, 1000, False) == 40
    assert u.approx_rows(40, 1000, 10_000, True) == 400
    assert u.approx_rows(40, 0, 10_000, True) == 40


# ── mode and mapping ──────────────────────────────────────────────────────────────────────

def test_a_file_that_matches_a_te_table_that_exists_starts_as_one():
    assert u.default_mode({"teTableMatch": "orgs"}, ["orgs", "people"]) == u.TE
    assert u.default_mode({"teTableMatch": "gone"}, ["orgs"]) == u.DYNAMIC
    assert u.default_mode({"teTableMatch": None}, ["orgs"]) == u.DYNAMIC
    assert u.default_mode({}, []) == u.DYNAMIC


def test_only_the_renames_the_person_typed_are_sent_against_the_files_own_headers():
    assert u.header_mapping(["First Name", "age", "city"], ["given", "  ", ""]) == [
        {"original": "First Name", "renamed": "given"}]
    assert u.header_mapping(["a"], [" x "]) == [{"original": "a", "renamed": "x"}]
    assert u.header_mapping(["a", "b"], []) == []


def test_a_new_table_waits_for_the_confirmation_and_a_te_load_for_a_target():
    assert not u.ready(u.DYNAMIC, False, None) and u.ready(u.DYNAMIC, True, None)
    assert not u.ready(u.TE, True, None) and u.ready(u.TE, False, "orgs")


# ── what is sent ──────────────────────────────────────────────────────────────────────────

def test_a_new_table_sends_the_text_the_original_bytes_the_types_and_that_they_were_confirmed():
    p = _prep(raw=b"id,name\n1,x\n")

    body = u.build_payload(p, u.DYNAMIC, types=["int8", "text"], confirmed=True, headers=["id", "name"],
                           renames=["", "who"])

    assert body == {"fileName": "a.csv", "content": "id,name\n1,x\n", "mode": "dynamic",
                    "contentBase64": base64.b64encode(b"id,name\n1,x\n").decode(), "types": ["int8", "text"],
                    "typesConfirmed": True, "headerMapping": [{"original": "name", "renamed": "who"}]}


def test_no_renames_means_no_header_mapping_key_at_all():
    body = u.build_payload(_prep(), u.DYNAMIC, types=["int8"], confirmed=True, headers=["id"], renames=[""])

    assert "headerMapping" not in body


def test_the_original_bytes_not_the_decoded_text_are_what_is_base64d():
    raw = b"\xef\xbb\xbfid\n1\n"

    body = u.build_payload(_prep(raw=raw), u.DYNAMIC, types=["int8"], confirmed=True)

    assert base64.b64decode(body["contentBase64"]) == raw and body["content"] == "id\n1\n"


def test_a_te_load_sends_the_target_and_no_types_no_renames_and_no_confirmation():
    body = u.build_payload(_prep(), u.TE, types=["int8"], confirmed=True, headers=["id"], renames=["x"], target="orgs")

    assert body["mode"] == "te" and body["targetTable"] == "orgs"
    assert not {"types", "typesConfirmed", "headerMapping"} & set(body), "the API answers 422 to a mapping in T&E mode"


def test_an_unconfirmed_new_table_says_so_rather_than_claiming_it_was_checked():
    assert u.build_payload(_prep(), u.DYNAMIC, types=["text"])["typesConfirmed"] is False


# ── the sample the person checks ──────────────────────────────────────────────────────────

def test_the_sample_is_a_table_of_code_spans_numbered_from_one():
    pv = {"columns": ["id", "name"], "sampleRows": [["1", "[x](http://y.test)"], ["2", ""]]}

    frame = u.sample_frame(pv)

    assert list(frame.columns) == ["` id `", "` name `"] and list(frame.index) == [1, 2]
    assert frame.iloc[0, 1] == "` [x](http://y.test) `" and frame.iloc[1, 1] == ""


# ── agreement with the API and Streamlit ─────────────────────────────────────────────────

def test_the_column_types_are_the_ones_the_api_allows():
    from api.services.csv_parse import ALLOWED_TYPES
    assert set(u.ALLOWED_TYPES) == set(ALLOWED_TYPES) and set(u.TYPE_LABELS) == set(ALLOWED_TYPES)


def test_the_default_limit_is_the_apis_default():
    from api.config import settings
    import os
    if "MAX_UPLOAD_BYTES" not in os.environ:
        assert u.DEFAULT_MAX_UPLOAD_BYTES == settings.MAX_UPLOAD_BYTES


def test_streamlits_own_upload_limit_is_just_above_the_apis_so_it_never_refuses_what_the_api_would_take():
    """Streamlit counts a megabyte as 1,000,000 bytes and takes whole megabytes only (the #254 spike)."""
    config = tomllib.loads((APP_DIR / ".streamlit" / "config.toml").read_text(encoding="utf-8"))

    limit = config["server"]["maxUploadSize"]
    assert limit * 1_000_000 >= u.DEFAULT_MAX_UPLOAD_BYTES, "Streamlit would refuse a file the API accepts"
    assert (limit - 1) * 1_000_000 < u.DEFAULT_MAX_UPLOAD_BYTES, "and it is no more than one megabyte above"
    assert config["browser"]["gatherUsageStats"] is False


def test_widget_keys_tell_two_names_for_the_same_bytes_apart_and_are_stable():
    a, b = _prep("a.csv"), _prep("b.csv")

    assert u.key_for(a) != u.key_for(b) and u.key_for(a) == u.key_for(_prep("a.csv")) and len(u.key_for(a)) == 12


def test_the_same_name_and_bytes_twice_is_dropped_once_and_different_bytes_are_kept():
    kept, dropped = u.chosen_once([("a.csv", b"x\n1\n"), ("a.csv", b"x\n1\n"), ("a.csv", b"x\n2\n"), ("b.csv", b"x\n1\n")])

    assert [n for n, _ in kept] == ["a.csv", "a.csv", "b.csv"] and dropped == ["a.csv"]


@pytest.mark.parametrize("header, i, label", [
    ("amount", 2, "column 3 (amount)"),
    ("Full Name", 0, "column 1 (Full Name)"),
    ("first_name-2", 1, "column 2 (first_name-2)"),
    ("[click](https://evil.example/x)", 0, "column 1 (click https evil example x)"),
    ("**bold** :warning: <b>", 4, "column 5 (bold warning b)"),
    ("www.evil.example a@evil.example", 0, "column 1 (www evil example a evil example)"),
    ("", 3, "column 4"),
    ("   ", 3, "column 4"),
    ("!!!", 0, "column 1"),
    ("é Ünïcode", 0, "column 1 (é Ünïcode)"),
    ("a" * 100, 0, "column 1 (" + "a" * 40 + ")"),
])
def test_a_columns_box_label_keeps_what_helps_and_nothing_that_markdown_could_use(header, i, label):
    assert u.column_label(header, i) == label


def test_a_long_header_is_cut_so_that_a_label_stays_one_readable_line():
    label = u.column_label("x" * 100, 0)

    assert label == f"column 1 ({'x' * 40})"


@pytest.mark.parametrize("header", ["[x](https://e.test)", "https://e.test", "www.e.test", "a@e.test", "<a href=x>", "`code`", "$x$", ":zap:"])
def test_no_label_contains_anything_that_forms_a_link_or_formatting(header):
    label = u.column_label(header, 0)

    assert not any(token in label for token in ("://", "www.", "@", "[", "]", "`", "*", "<", ">", "$", ":"))
