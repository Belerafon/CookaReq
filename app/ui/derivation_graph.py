"""Display derivation graph for requirements using ``networkx`` and Graphviz.

The graph shows requirement nodes (prefixed with ``SR``) and ``derived-from``
links. It relies on ``networkx`` and the Graphviz ``dot`` tool. If these
packages are missing, a friendly message is shown instead of the graph.
"""

from __future__ import annotations

from app.i18n import _
import io
from typing import Sequence

import wx

from app.core.model import Requirement


class DerivationGraphFrame(wx.Frame):
    """Render a graph of requirement derivations."""

    def __init__(self, parent: wx.Window | None, requirements: Sequence[Requirement]):
        super().__init__(parent=parent, title=_("Derivation Graph"))
        self.SetSize((600, 400))
        self._panel = wx.ScrolledWindow(self)
        sizer = wx.BoxSizer(wx.VERTICAL)
        self._panel.SetSizer(sizer)
        self._bitmap = wx.StaticBitmap(self._panel)
        sizer.Add(self._bitmap, 0, wx.ALL, 5)
        self._build_graph(requirements)
        main_sizer = wx.BoxSizer(wx.VERTICAL)
        main_sizer.Add(self._panel, 1, wx.EXPAND)
        self.SetSizer(main_sizer)

    # ------------------------------------------------------------------
    def _build_graph(self, requirements: Sequence[Requirement]) -> None:
        """Generate graph image and place it inside the scrolled window."""
        try:
            import networkx as nx
            from networkx.drawing.nx_pydot import to_pydot
        except Exception:  # pragma: no cover - optional dependency
            wx.StaticText(
                self._panel,
                label=_("Install networkx and graphviz to view the derivation graph."),
            )
            return

        graph = nx.DiGraph()
        for req in requirements:
            node = f"SR{req.id}"
            graph.add_node(node)
        for req in requirements:
            src_node = f"SR{req.id}"
            for link in req.derived_from:
                target = f"SR{link.source_id}"
                if target not in graph:
                    graph.add_node(target)
                graph.add_edge(src_node, target, label="derived-from")

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
