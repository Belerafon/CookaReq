import pytest

from app.settings import MAX_LIST_PANEL_DEBUG_LEVEL
from app.ui.list_panel import ListPanelDebugDelta, ListPanelDebugProfile


def test_debug_profile_base_level_without_instrumentation():
    profile = ListPanelDebugProfile.from_level(35)

    assert profile.level == 35
    assert profile.base_level == 35
    assert profile.instrumentation_tier == 0
    assert profile.probe_force_refresh is False
    assert profile.probe_column_reset is False
    assert profile.probe_deferred_population is False


@pytest.mark.parametrize(
    "level,tier,expected_flags",
    [
        (135, 1, {"probe_force_refresh"}),
        (235, 2, {"probe_force_refresh", "probe_column_reset"}),
        (
            min(335, MAX_LIST_PANEL_DEBUG_LEVEL),
            3,
            {
                "probe_force_refresh",
                "probe_column_reset",
                "probe_deferred_population",
            },
        ),
    ],
)
def test_debug_profile_instrumentation_tiers(level, tier, expected_flags):
    base_reference = ListPanelDebugProfile.from_level(35)
    profile = ListPanelDebugProfile.from_level(level)

    assert profile.base_level == 35
    assert profile.instrumentation_tier >= tier
    active = {
        name
        for name in (
            "probe_force_refresh",
            "probe_column_reset",
            "probe_deferred_population",
        )
        if getattr(profile, name)
    }
    assert expected_flags.issubset(active)
    assert profile.disabled_features() == base_reference.disabled_features()


def test_debug_profile_clamps_to_maximum_level():
    over_max = ListPanelDebugProfile.from_level(MAX_LIST_PANEL_DEBUG_LEVEL + 500)

    assert over_max.level == MAX_LIST_PANEL_DEBUG_LEVEL
    assert over_max.base_level <= 57


def test_debug_profile_rollback_stage_progression():
    base_reference = ListPanelDebugProfile.from_level(35)
    assert base_reference.rollback_stage == 0

    expected_progression = {
        35: 0,
        36: 0,
        37: 0,
        38: 0,
        39: 0,
        40: 0,
        41: 0,
        42: 0,
        43: 0,
        44: 0,
        45: 0,
        46: 0,
        47: 0,
        48: 1,
        49: 2,
        50: 3,
        51: 4,
        52: 5,
        53: 6,
        54: 7,
        55: 8,
        56: 9,
        57: 10,
    }
    for level, expected in expected_progression.items():
        profile = ListPanelDebugProfile.from_level(level)
        assert profile.rollback_stage == expected

    beyond = ListPanelDebugProfile.from_level(99)
    assert beyond.rollback_stage == 10


def test_debug_profile_diff_reports_width_guard_drop():
    before = ListPanelDebugProfile.from_level(47)
    after = ListPanelDebugProfile.from_level(48)

    delta = after.diff(before)

    assert delta.enabled_features == ()
    assert "report column width enforcement" in delta.disabled_features
    assert not delta.enabled_instrumentation
    assert not delta.disabled_instrumentation


def test_debug_profile_diff_reports_plain_queue_toggle():
    before = ListPanelDebugProfile.from_level(42)
    after = ListPanelDebugProfile.from_level(43)

    delta = after.diff(before)

    assert "plain deferred payload queue" in delta.disabled_features
    assert delta.enabled_features == ()
