"""RID normalization helpers shared across UI formatting."""

from app.services.requirements import canonicalize_rid, same_rid, title_starts_with_rid


def test_canonicalize_rid_accepts_dash_and_zero_variants() -> None:
    assert canonicalize_rid("SYS-0001") == "SYS1"
    assert canonicalize_rid("sys-01") == "sys1"


def test_same_rid_matches_dash_variants() -> None:
    assert same_rid("HLR1", "HLR-01") is True
    assert same_rid("HLR1", "LLR-01") is False


def test_title_starts_with_rid_detects_prefixed_title() -> None:
    assert title_starts_with_rid("HLR-01 Thrust limiting algorithm", "HLR1") is True
    assert title_starts_with_rid("Thrust limiting algorithm", "HLR1") is False
