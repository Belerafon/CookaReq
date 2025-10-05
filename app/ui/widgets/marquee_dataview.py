"""Simplified :class:`~wx.dataview.DataViewListCtrl` used by the chat panel."""

from __future__ import annotations

import wx.dataview as dv


class MarqueeDataViewListCtrl(dv.DataViewListCtrl):
    """Plain DataViewListCtrl without custom marquee logic."""

    # The widget used to provide marquee selection. After removing that feature
    # we keep the dedicated subclass so layout code does not need to change the
    # type signature, but no additional behaviour is implemented.


__all__ = ["MarqueeDataViewListCtrl"]

