import pytest

from app.settings import MAX_LIST_PANEL_DEBUG_LEVEL
from app.ui.list_panel import ListPanelDebugProfile


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
    assert over_max.base_level <= 40
