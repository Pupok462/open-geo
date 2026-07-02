from __future__ import annotations

import datetime as dt

import pytest
from pydantic import BaseModel, ValidationError

import pipeline.schema as schema_mod
from pipeline.schema import Link, QueryCapture, normalize_domain


def _min_capture() -> dict:
    return {
        "query": "best task tracking tools",
        "lens": "general",
        "engine": "google",
        "captured_at": "2026-06-18T20:15:30Z",
        "overview_present": True,
        "brand_in_answer_text": False,
    }


REQUIRED_FIELDS = [
    "query",
    "lens",
    "engine",
    "captured_at",
    "overview_present",
    "brand_in_answer_text",
]


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "   ",
        "\t\n ",
        ".",
        "....",
        "://",
        "https://",
        "//",
    ],
)
def test_normalize_domain_empty_like_returns_empty(raw):
    assert normalize_domain(raw) == ""


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("example.com", "example.com"),
        ("http://example.com", "example.com"),
        ("https://example.com", "example.com"),
        ("ftp://example.com/x", "example.com"),
        ("gopher://example.com", "example.com"),
        ("//example.com/path", "example.com"),
        ("HTTPS://EXAMPLE.COM", "example.com"),
    ],
)
def test_normalize_domain_scheme(raw, expected):
    assert normalize_domain(raw) == expected


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("user@example.com", "example.com"),
        ("user:pass@example.com", "example.com"),
        ("https://user:pass@example.com/x", "example.com"),
        ("mailto:foo@example.com", "example.com"),
        ("a@b@example.com", "example.com"),
        ("https://medium.com/@ravityuval/how-i-cut-costs", "medium.com"),
        ("https://medium.com/@meecrypt/the-comparison-of-depin", "medium.com"),
        ("https://example.com/?email=a@b.com", "example.com"),
        ("https://example.com/path#frag@thing", "example.com"),
        ("https://user@host.com:8080/x", "host.com"),
    ],
)
def test_normalize_domain_userinfo(raw, expected):
    assert normalize_domain(raw) == expected


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("example.com/path", "example.com"),
        ("h/x", "h"),
        ("example.com?q=1", "example.com"),
        ("h?q", "h"),
        ("example.com#frag", "example.com"),
        ("h#f", "h"),
        ("example.com?a=/b#c", "example.com"),
        ("example.com/p?q#f", "example.com"),
    ],
)
def test_normalize_domain_path_query_fragment(raw, expected):
    assert normalize_domain(raw) == expected


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("example.com.", "example.com"),
        (".example.com", "example.com"),
        ("example.com:8080", "example.com"),
        ("example.com:443", "example.com"),
        ("EXAMPLE.COM", "example.com"),
        ("ExAmPlE.CoM", "example.com"),
    ],
)
def test_normalize_domain_dot_port_case(raw, expected):
    assert normalize_domain(raw) == expected


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("www.example.com", "example.com"),
        ("www.www.example.com", "example.com"),
        ("www.www.www.example.com", "example.com"),
        ("WWW.Example.com", "example.com"),
        ("www.com", "com"),
    ],
)
def test_normalize_domain_www(raw, expected):
    assert normalize_domain(raw) == expected


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("localhost", "localhost"),
        ("example.com", "example.com"),
        ("a.b.example.com", "example.com"),
        ("w.x.y.z.example.com", "example.com"),
        ("sub.example.com", "example.com"),
    ],
)
def test_normalize_domain_label_count(raw, expected):
    assert normalize_domain(raw) == expected


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("shop.example.co.uk", "example.co.uk"),
        ("a.b.example.co.uk", "example.co.uk"),
        ("x.com.au", "x.com.au"),
        ("y.co.jp", "y.co.jp"),
        ("z.gov.uk", "z.gov.uk"),
        ("blog.example.org.uk", "example.org.uk"),
        ("news.site.govt.nz", "site.govt.nz"),
        ("a.b.c.example.com.br", "example.com.br"),
    ],
)
def test_normalize_domain_multipart_tld(raw, expected):
    assert normalize_domain(raw) == expected


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("a.b.example.gov.fr", "gov.fr"),
        ("ministry.example.gov.fr", "gov.fr"),
        ("shop.example.com.pl", "com.pl"),
        ("mail.google.com", "google.com"),
    ],
)
def test_normalize_domain_v1_limitation_unknown_multipart(raw, expected):
    assert normalize_domain(raw) == expected


def test_normalize_domain_combined_scheme_www_port_path_query():
    assert (
        normalize_domain("https://www.Example.COM:443/catalog/running?utm=1")
        == "example.com"
    )


def test_normalize_domain_combined_userinfo_subdomain_multipart():
    assert (
        normalize_domain("https://user:pw@shop.eu.example.co.uk/deals?ref=x")
        == "example.co.uk"
    )


def test_normalize_domain_surrounding_whitespace_trimmed():
    assert normalize_domain("   https://www.example.com/x   ") == "example.com"


def test_normalize_domain_unicode_host_lowercased_kept():
    assert normalize_domain("https://shop.café.com/path") == "café.com"


def test_normalize_domain_returns_str_type():
    out = normalize_domain("https://www.example.com")
    assert isinstance(out, str)


def test_link_valid_construction():
    link = Link(rank=2, url="https://example.com/x", domain="example.com")
    assert (link.rank, link.url, link.domain) == (2, "https://example.com/x", "example.com")


def test_link_rank_str_to_int_coercion():
    link = Link(rank="1", url="https://example.com/x", domain="example.com")
    assert link.rank == 1
    assert isinstance(link.rank, int)


def test_link_rank_non_integer_string_raises():
    with pytest.raises(ValidationError) as exc:
        Link(rank="1.5", url="u", domain="d")
    err = exc.value.errors()[0]
    assert err["loc"] == ("rank",)


def test_link_rank_negative_is_accepted():
    link = Link(rank=-3, url="u", domain="d")
    assert link.rank == -3


@pytest.mark.parametrize("missing", ["rank", "url", "domain"])
def test_link_missing_required_field_raises(missing):
    data = {"rank": 1, "url": "https://example.com/x", "domain": "example.com"}
    del data[missing]
    with pytest.raises(ValidationError) as exc:
        Link.model_validate(data)
    err = exc.value.errors()[0]
    assert err["loc"] == (missing,)
    assert err["type"] == "missing"


def test_link_extra_field_ignored():
    link = Link.model_validate(
        {"rank": 1, "url": "u", "domain": "d", "surprise": "x"}
    )
    assert not hasattr(link, "surprise")
    assert link.model_dump() == {"rank": 1, "url": "u", "domain": "d"}


def test_query_capture_full_valid_object():
    data = {
        "query": "best project management software",
        "lens": "comparative",
        "engine": "google",
        "captured_at": "2026-06-18T20:15:30Z",
        "answer_text_md": "**Example** offers several suitable options...",
        "screenshot_path": "data/screenshots/42/0003.png",
        "overview_present": True,
        "sources": [
            {"rank": 1, "url": "https://g2.com/x", "domain": "g2.com"},
            {"rank": 2, "url": "https://example.com/catalog", "domain": "example.com"},
        ],
        "citations": [
            {"rank": 1, "url": "https://example.com/catalog", "domain": "example.com"},
        ],
        "target_source_ranks": [2],
        "target_citation_ranks": [1],
        "brand_in_answer_text": True,
        "sentiment": "recommended among suitable options",
    }
    cap = QueryCapture.model_validate(data)
    assert cap.query == data["query"]
    assert cap.lens == "comparative"
    assert cap.engine == "google"
    assert cap.overview_present is True
    assert cap.brand_in_answer_text is True
    assert cap.answer_text_md == data["answer_text_md"]
    assert cap.screenshot_path == data["screenshot_path"]
    assert cap.target_source_ranks == [2]
    assert cap.target_citation_ranks == [1]
    assert cap.sentiment == "recommended among suitable options"
    assert isinstance(cap.captured_at, dt.datetime)


def test_query_capture_defaults_applied():
    cap = QueryCapture.model_validate(_min_capture())
    assert cap.sources == []
    assert cap.citations == []
    assert cap.target_source_ranks == []
    assert cap.target_citation_ranks == []
    assert cap.answer_text_md is None
    assert cap.screenshot_path is None
    assert cap.sentiment is None


def test_query_capture_default_lists_are_independent_per_instance():
    a = QueryCapture.model_validate(_min_capture())
    b = QueryCapture.model_validate(_min_capture())
    a.sources.append(Link(rank=1, url="u", domain="d"))
    a.target_source_ranks.append(1)
    assert b.sources == []
    assert b.target_source_ranks == []
    assert a.sources is not b.sources


def test_query_capture_explicit_none_optionals_allowed():
    cap = QueryCapture.model_validate(
        {**_min_capture(), "answer_text_md": None, "screenshot_path": None, "sentiment": None}
    )
    assert cap.answer_text_md is None
    assert cap.screenshot_path is None
    assert cap.sentiment is None


@pytest.mark.parametrize("missing", REQUIRED_FIELDS)
def test_query_capture_missing_required_field_raises(missing):
    data = _min_capture()
    del data[missing]
    with pytest.raises(ValidationError) as exc:
        QueryCapture.model_validate(data)
    err = exc.value.errors()[0]
    assert err["loc"] == (missing,)
    assert err["type"] == "missing"


@pytest.mark.parametrize("lens", ["general", "branded", "comparative"])
def test_query_capture_valid_lens_values(lens):
    cap = QueryCapture.model_validate({**_min_capture(), "lens": lens})
    assert cap.lens == lens


@pytest.mark.parametrize("bad_lens", ["promotional", "GENERAL", "", "branded ", "transactional"])
def test_query_capture_bad_lens_literal_raises(bad_lens):
    with pytest.raises(ValidationError) as exc:
        QueryCapture.model_validate({**_min_capture(), "lens": bad_lens})
    err = exc.value.errors()[0]
    assert err["loc"] == ("lens",)
    assert err["type"] == "literal_error"


def test_query_capture_captured_at_z_suffix_parses_utc():
    cap = QueryCapture.model_validate({**_min_capture(), "captured_at": "2026-06-18T20:15:30Z"})
    assert isinstance(cap.captured_at, dt.datetime)
    assert cap.captured_at.utcoffset() == dt.timedelta(0)
    assert (cap.captured_at.year, cap.captured_at.month, cap.captured_at.day) == (2026, 6, 18)
    assert (cap.captured_at.hour, cap.captured_at.minute, cap.captured_at.second) == (20, 15, 30)


def test_query_capture_captured_at_offset_parses_utc():
    cap = QueryCapture.model_validate({**_min_capture(), "captured_at": "2026-06-18T20:15:30+00:00"})
    assert isinstance(cap.captured_at, dt.datetime)
    assert cap.captured_at.utcoffset() == dt.timedelta(0)


def test_query_capture_captured_at_z_and_offset_are_equal():
    z = QueryCapture.model_validate({**_min_capture(), "captured_at": "2026-06-18T20:15:30Z"})
    off = QueryCapture.model_validate({**_min_capture(), "captured_at": "2026-06-18T20:15:30+00:00"})
    assert z.captured_at == off.captured_at


def test_query_capture_captured_at_nonzero_offset_preserved():
    plus2 = QueryCapture.model_validate({**_min_capture(), "captured_at": "2026-06-18T20:15:30+02:00"})
    utc = QueryCapture.model_validate({**_min_capture(), "captured_at": "2026-06-18T20:15:30Z"})
    assert plus2.captured_at.utcoffset() == dt.timedelta(hours=2)
    assert plus2.captured_at == utc.captured_at - dt.timedelta(hours=2)


def test_query_capture_captured_at_invalid_string_raises():
    with pytest.raises(ValidationError) as exc:
        QueryCapture.model_validate({**_min_capture(), "captured_at": "not-a-date"})
    assert exc.value.errors()[0]["loc"] == ("captured_at",)


def test_query_capture_nested_link_dicts_parse_to_link():
    cap = QueryCapture.model_validate(
        {
            **_min_capture(),
            "sources": [{"rank": 1, "url": "https://example.com/s", "domain": "example.com"}],
            "citations": [{"rank": 2, "url": "https://example.com/c", "domain": "example.com"}],
        }
    )
    assert isinstance(cap.sources[0], Link)
    assert isinstance(cap.citations[0], Link)
    assert cap.sources[0].rank == 1
    assert cap.citations[0].domain == "example.com"


def test_query_capture_nested_link_invalid_reports_indexed_loc():
    with pytest.raises(ValidationError) as exc:
        QueryCapture.model_validate(
            {
                **_min_capture(),
                "sources": [{"rank": 1, "url": "https://example.com/s"}],
            }
        )
    err = exc.value.errors()[0]
    assert err["loc"] == ("sources", 0, "domain")
    assert err["type"] == "missing"


@pytest.mark.parametrize("value, expected", [(1, True), (0, False), (True, True), (False, False)])
def test_query_capture_overview_present_bool_coercion(value, expected):
    cap = QueryCapture.model_validate({**_min_capture(), "overview_present": value})
    assert cap.overview_present is expected


def test_query_capture_model_validate_dump_round_trip():
    data = {
        "query": "round trip",
        "lens": "branded",
        "engine": "google",
        "captured_at": "2026-06-18T20:15:30Z",
        "answer_text_md": "text",
        "screenshot_path": "data/s/0.png",
        "overview_present": True,
        "sources": [{"rank": 1, "url": "https://example.com/s", "domain": "example.com"}],
        "citations": [{"rank": 1, "url": "https://example.com/c", "domain": "example.com"}],
        "target_source_ranks": [1],
        "target_citation_ranks": [1],
        "brand_in_answer_text": True,
        "sentiment": "neutral",
    }
    cap = QueryCapture.model_validate(data)
    dumped = cap.model_dump()
    assert isinstance(dumped["captured_at"], dt.datetime)
    again = QueryCapture.model_validate(dumped)
    assert again == cap
    assert again.model_dump() == dumped


def test_query_capture_json_round_trip():
    cap = QueryCapture.model_validate(_min_capture())
    again = QueryCapture.model_validate_json(cap.model_dump_json())
    assert again == cap


def test_dunder_all_contents():
    assert schema_mod.__all__ == ["Lens", "Link", "QueryCapture", "normalize_domain"]


def test_models_are_pydantic_base_models():
    assert issubclass(Link, BaseModel)
    assert issubclass(QueryCapture, BaseModel)


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("www.", "www"),
        ("www", "www"),
        ("www.www.", "www"),
        ("wwwx.com", "wwwx.com"),
        ("xwww.example.com", "example.com"),
        (".www.example.com", "example.com"),
    ],
)
def test_normalize_domain_www_prefix_edge_cases(raw, expected):
    assert normalize_domain(raw) == expected


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("://x", "x"),
        ("a://b", "b"),
        ("http://a://b", "a"),
        ("scheme://www.example.com", "example.com"),
    ],
)
def test_normalize_domain_scheme_split_first_only(raw, expected):
    assert normalize_domain(raw) == expected


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("example.com/path@evil", "example.com"),
        ("example.com?u=a@b", "example.com"),
        ("example.com/u@host.com/x", "example.com"),
        ("a@b@example.com", "example.com"),
    ],
)
def test_normalize_domain_path_strip_precedes_userinfo_split(raw, expected):
    assert normalize_domain(raw) == expected


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("example.com.:8080", "com."),
        ("example.co.uk.:443", "uk."),
        ("example.com:8080", "example.com"),
        ("example.com.", "example.com"),
    ],
)
def test_normalize_domain_trailing_dot_before_port_wart(raw, expected):
    assert normalize_domain(raw) == expected


def test_normalize_domain_ipv6_bracket_degrades_to_bracket():
    assert normalize_domain("[::1]:8080") == "["


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("user@example.com:8080", "example.com"),
        ("https://user:pass@www.example.com:443/x?y#z", "example.com"),
    ],
)
def test_normalize_domain_userinfo_and_port(raw, expected):
    assert normalize_domain(raw) == expected


@pytest.mark.parametrize("raw", ["co.uk", "com.au", "co.jp", "gov.uk", "govt.nz"])
def test_normalize_domain_bare_multipart_suffix_returned_verbatim(raw):
    assert normalize_domain(raw) == raw


@pytest.mark.parametrize(
    "raw",
    [
        "@",
        "http://@",
        "user@",
        ":8080",
        "http://",
        "///",
    ],
)
def test_normalize_domain_reduces_to_empty_after_processing(raw):
    assert normalize_domain(raw) == ""


@pytest.mark.parametrize(
    "raw, expected",
    [
        (None, ""),
        (0, ""),
        (False, ""),
        ([], ""),
        (123, "123"),
        (12.5, "12.5"),
    ],
)
def test_normalize_domain_non_string_inputs(raw, expected):
    assert normalize_domain(raw) == expected


def test_normalize_domain_float_label_count():
    assert normalize_domain(12.5) == "12.5"
    assert normalize_domain(1200.0) == "1200.0"


def test_link_rank_whole_float_coerces_to_int():
    link = Link(rank=2.0, url="u", domain="d")
    assert link.rank == 2
    assert isinstance(link.rank, int)


def test_link_rank_fractional_float_raises_int_from_float():
    with pytest.raises(ValidationError) as exc:
        Link(rank=1.5, url="u", domain="d")
    err = exc.value.errors()[0]
    assert err["loc"] == ("rank",)
    assert err["type"] == "int_from_float"


def test_link_rank_non_numeric_string_raises_parsing():
    with pytest.raises(ValidationError) as exc:
        Link(rank="abc", url="u", domain="d")
    err = exc.value.errors()[0]
    assert err["loc"] == ("rank",)
    assert err["type"] == "int_parsing"


def test_link_rank_bool_true_coerces_to_one():
    assert Link(rank=True, url="u", domain="d").rank == 1
    assert Link(rank=False, url="u", domain="d").rank == 0


def test_link_rank_zero_accepted():
    assert Link(rank=0, url="u", domain="d").rank == 0


def test_link_str_fields_do_not_coerce_from_int():
    with pytest.raises(ValidationError) as exc:
        Link(rank=1, url=123, domain="d")
    err = exc.value.errors()[0]
    assert err["loc"] == ("url",)
    assert err["type"] == "string_type"


def test_link_none_for_required_str_raises():
    with pytest.raises(ValidationError) as exc:
        Link(rank=1, url=None, domain="d")
    err = exc.value.errors()[0]
    assert err["loc"] == ("url",)
    assert err["type"] == "string_type"


def test_link_equality_and_repr():
    a = Link(rank=1, url="u", domain="d")
    b = Link(rank=1, url="u", domain="d")
    c = Link(rank=2, url="u", domain="d")
    assert a == b
    assert a != c
    assert "rank=1" in repr(a)


@pytest.mark.parametrize(
    "value, expected",
    [
        ("true", True), ("True", True), ("yes", True), ("on", True), ("1", True),
        ("false", False), ("False", False), ("no", False), ("off", False), ("0", False),
    ],
)
def test_query_capture_bool_string_parsing(value, expected):
    cap = QueryCapture.model_validate({**_min_capture(), "overview_present": value})
    assert cap.overview_present is expected


@pytest.mark.parametrize("bad", [2, -1, "2", "maybe", "trueish"])
def test_query_capture_bool_out_of_range_raises(bad):
    with pytest.raises(ValidationError) as exc:
        QueryCapture.model_validate({**_min_capture(), "overview_present": bad})
    err = exc.value.errors()[0]
    assert err["loc"] == ("overview_present",)
    assert err["type"] == "bool_parsing"


def test_query_capture_rank_lists_coerce_strings_to_int():
    cap = QueryCapture.model_validate(
        {**_min_capture(), "target_source_ranks": ["1", "2"], "target_citation_ranks": [3.0]}
    )
    assert cap.target_source_ranks == [1, 2]
    assert all(isinstance(x, int) for x in cap.target_source_ranks)
    assert cap.target_citation_ranks == [3]


def test_query_capture_rank_list_bad_element_reports_indexed_loc():
    with pytest.raises(ValidationError) as exc:
        QueryCapture.model_validate(
            {**_min_capture(), "target_source_ranks": [1, "oops", 3]}
        )
    err = exc.value.errors()[0]
    assert err["loc"] == ("target_source_ranks", 1)
    assert err["type"] == "int_parsing"


@pytest.mark.parametrize("field", ["sources", "citations"])
def test_query_capture_link_array_given_scalar_raises_list_type(field):
    with pytest.raises(ValidationError) as exc:
        QueryCapture.model_validate({**_min_capture(), field: "notalist"})
    err = exc.value.errors()[0]
    assert err["loc"] == (field,)
    assert err["type"] == "list_type"


def test_query_capture_captured_at_datetime_object_passthrough():
    aware = dt.datetime(2026, 6, 18, 20, 15, 30, tzinfo=dt.timezone.utc)
    cap = QueryCapture.model_validate({**_min_capture(), "captured_at": aware})
    assert cap.captured_at == aware


def test_query_capture_captured_at_int_is_unix_epoch():
    cap = QueryCapture.model_validate({**_min_capture(), "captured_at": 0})
    assert cap.captured_at == dt.datetime(1970, 1, 1, 0, 0, 0, tzinfo=dt.timezone.utc)


def test_query_capture_captured_at_naive_string_parses_without_tz():
    cap = QueryCapture.model_validate({**_min_capture(), "captured_at": "2026-06-18T20:15:30"})
    assert isinstance(cap.captured_at, dt.datetime)
    assert cap.captured_at.utcoffset() is None
    assert cap.captured_at.tzinfo is None


def test_query_capture_accepts_empty_strings_for_query_and_engine():
    cap = QueryCapture.model_validate({**_min_capture(), "query": "", "engine": ""})
    assert cap.query == ""
    assert cap.engine == ""


def test_query_capture_query_and_engine_reject_none():
    for field in ("query", "engine"):
        with pytest.raises(ValidationError) as exc:
            QueryCapture.model_validate({**_min_capture(), field: None})
        err = exc.value.errors()[0]
        assert err["loc"] == (field,)
        assert err["type"] == "string_type"


def test_query_capture_unicode_query_and_sentiment_preserved():
    cap = QueryCapture.model_validate(
        {**_min_capture(), "query": "лучший проект café ☕", "sentiment": "упомянут нейтрально"}
    )
    assert cap.query == "лучший проект café ☕"
    assert cap.sentiment == "упомянут нейтрально"


def test_query_capture_extra_field_ignored():
    cap = QueryCapture.model_validate({**_min_capture(), "unexpected_key": "x"})
    assert not hasattr(cap, "unexpected_key")
    assert "unexpected_key" not in cap.model_dump()


def test_query_capture_multiple_missing_fields_all_reported():
    data = {"lens": "general", "engine": "e"}
    with pytest.raises(ValidationError) as exc:
        QueryCapture.model_validate(data)
    missing = {e["loc"][0] for e in exc.value.errors() if e["type"] == "missing"}
    assert {"query", "captured_at", "overview_present", "brand_in_answer_text"} <= missing


def test_query_capture_full_object_json_round_trip():
    cap = QueryCapture.model_validate(
        {
            "query": "best task tracker",
            "lens": "comparative",
            "engine": "google",
            "captured_at": "2026-06-18T20:15:30+00:00",
            "answer_text_md": "**Example** is solid.",
            "screenshot_path": "data/s/1.png",
            "overview_present": True,
            "sources": [
                {"rank": 1, "url": "https://a.com/1", "domain": "a.com"},
                {"rank": 2, "url": "https://example.com/2", "domain": "example.com"},
            ],
            "citations": [{"rank": 1, "url": "https://example.com/2", "domain": "example.com"}],
            "target_source_ranks": [2],
            "target_citation_ranks": [1],
            "brand_in_answer_text": True,
            "sentiment": "top pick",
        }
    )
    again = QueryCapture.model_validate_json(cap.model_dump_json())
    assert again == cap
    assert isinstance(again.sources[0], Link)
    assert again.sources[1].domain == "example.com"


def test_lens_literal_members_are_exactly_three():
    import typing

    assert set(typing.get_args(schema_mod.Lens)) == {"general", "branded", "comparative"}
