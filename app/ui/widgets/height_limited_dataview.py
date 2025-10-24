"""DataViewListCtrl variants with constrained best size reporting."""

from __future__ import annotations

import wx
import wx.dataview as dv


class HeightLimitedDataViewListCtrl(dv.DataViewListCtrl):
    """A ``DataViewListCtrl`` that caps its reported best height.

    ``wx.DataViewListCtrl`` returns the height required to display all rows when
    queried for its best size. When the parent sizer relies on that value the
    widget expands indefinitely and the native scrollbars never become
    available.  This subclass constrains the advertised best height so layouts
    keep the control at a manageable size and allow scrolling for overflow.
    """

    def __init__(
        self,
        *args,
        height_limit: int | None = None,
        **kwargs,
    ) -> None:
        self._height_limit: int | None = None
        super().__init__(*args, **kwargs)
        self.SetHeightLimit(height_limit)

    # ------------------------------------------------------------------
    def SetHeightLimit(self, height: int | None) -> None:
        """Define the maximum height advertised through :meth:`GetBestSize`.

        Passing ``None`` removes the limit and restores the default behaviour.
        Non-positive values clamp the limit to the effective minimum height so
        callers can disable the cap without needing to compute a specific
        number of pixels.
        """

        limit = self._normalize_height(height)
        if limit == self._height_limit:
            return
        self._height_limit = limit
        self.InvalidateBestSize()
        self.SendSizeEvent()
        parent = self.GetParent()
        if parent is not None:
            parent.SendSizeEvent()

    # ------------------------------------------------------------------
    def GetHeightLimit(self) -> int | None:
        """Return the current height cap applied to the control."""

        return self._height_limit

    # ------------------------------------------------------------------
    def DoGetBestSize(self) -> wx.Size:  # noqa: N802 - matches wx API
        size = super().DoGetBestSize()
        return self._limit_height(size)

    # ------------------------------------------------------------------
    def _limit_height(self, size: wx.Size) -> wx.Size:
        limit = self._height_limit
        min_height = self._effective_min_height()
        if limit is None:
            target_height = max(size.height, min_height)
        else:
            target_height = max(min_height, min(size.height, limit))
        if target_height != size.height:
            size = wx.Size(size.width, target_height)
        return size

    # ------------------------------------------------------------------
    def _effective_min_height(self) -> int:
        getter = getattr(self, "GetEffectiveMinSize", None)
        if callable(getter):
            min_size = getter()
        else:
            min_size = self.GetMinSize()
        if isinstance(min_size, wx.Size):
            return max(int(min_size.height), 0)
        return 0

    # ------------------------------------------------------------------
    @staticmethod
    def _normalize_height(height: int | None) -> int | None:
        if height is None:
            return None
        try:
            value = int(height)
        except (TypeError, ValueError):
            return None
        if value <= 0:
            return 0
        return value


__all__ = ["HeightLimitedDataViewListCtrl"]

