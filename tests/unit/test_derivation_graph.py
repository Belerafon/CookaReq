from app.ui.derivation_graph import build_graph_from_links


def test_build_graph_from_links_colors():
    links = [("HLR001", "SYS001"), ("LLR001", "HLR001")]
    graph = build_graph_from_links(links)
    assert set(graph.nodes) == {"SYS001", "HLR001", "LLR001"}
    assert graph.has_edge("HLR001", "SYS001")
    color_sys = graph.nodes["SYS001"]["fillcolor"]
    color_hlr = graph.nodes["HLR001"]["fillcolor"]
    assert color_sys.startswith("#") and len(color_sys) == 7
    assert color_sys != color_hlr
    assert graph.edges["HLR001", "SYS001"]["label"] == "derived-from"
