from app.ui.derivation_graph import build_graph_from_links


def test_build_graph_from_links_colors():
    links = [("HLR1", "SYS1"), ("LLR1", "HLR1")]
    graph = build_graph_from_links(links)
    assert set(graph.nodes) == {"SYS1", "HLR1", "LLR1"}
    assert graph.has_edge("HLR1", "SYS1")
    color_sys = graph.nodes["SYS1"]["fillcolor"]
    color_hlr = graph.nodes["HLR1"]["fillcolor"]
    assert color_sys.startswith("#") and len(color_sys) == 7
    assert color_sys != color_hlr
    assert graph.edges["HLR1", "SYS1"]["label"] == "derived-from"
