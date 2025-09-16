"""Display derivation graph for requirement links."""

from __future__ import annotations

import io
from collections.abc import Sequence

import wx

from ..core.document_store import parse_rid, stable_color
from ..i18n import _


def build_graph_from_links(links: Sequence[tuple[str, str]]):
    """Return ``networkx`` graph for ``links`` with colored nodes."""
    import networkx as nx

    graph = nx.DiGraph()
    for child, parent in links:
        for rid in (child, parent):
            if rid not in graph:
                prefix, _ = parse_rid(rid)
                graph.add_node(
                    rid,
                    style="filled",
                    fillcolor=stable_color(prefix),
                )
        graph.add_edge(child, parent, label="derived-from")
    return graph


class DerivationGraphFrame(wx.Frame):
    """Render a graph of requirement derivations."""

    def __init__(self, parent: wx.Window | None, links: Sequence[tuple[str, str]]):
        """Create frame displaying derivation graph for ``links``."""
        super().__init__(parent=parent, title=_("Derivation Graph"))
        self.SetSize((600, 400))
        self._panel = wx.ScrolledWindow(self)
        sizer = wx.BoxSizer(wx.VERTICAL)
        self._panel.SetSizer(sizer)
        self._bitmap = wx.StaticBitmap(self._panel)
        sizer.Add(self._bitmap, 0, wx.ALL, 5)
        self._build_graph(links)
        main_sizer = wx.BoxSizer(wx.VERTICAL)
        main_sizer.Add(self._panel, 1, wx.EXPAND)
        self.SetSizer(main_sizer)

    # ------------------------------------------------------------------
    def _build_graph(self, links: Sequence[tuple[str, str]]) -> None:
        """Generate graph image and place it inside the scrolled window."""
        try:
            from networkx.drawing.nx_pydot import to_pydot
        except Exception:  # pragma: no cover - optional dependency
            wx.StaticText(
                self._panel,
                label=_("Install networkx and graphviz to view the derivation graph."),
            )
            return

        graph = build_graph_from_links(links)
        if graph.number_of_edges() == 0:
            wx.StaticText(self._panel, label=_("No derivation links found."))
            return

        dot = to_pydot(graph)
        dot.set_rankdir("LR")
        try:
            png = dot.create_png()
        except Exception:  # pragma: no cover - missing dot executable
            wx.StaticText(
                self._panel,
                label=_("Graphviz 'dot' executable not found."),
            )
            return

        stream = io.BytesIO(png)
        image = wx.Image(stream)
        bmp = wx.Bitmap(image)
        self._bitmap.SetBitmap(bmp)
        self._panel.SetScrollbars(1, 1, bmp.GetWidth(), bmp.GetHeight())
