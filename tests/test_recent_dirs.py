import importlib
import pytest

def test_recent_dirs_history(tmp_path, wx_app):
    wx = pytest.importorskip("wx")
    import app.ui.list_panel as list_panel
    import app.ui.main_frame as main_frame
    importlib.reload(list_panel)
    importlib.reload(main_frame)
    frame = main_frame.MainFrame(None)

    dirs = [tmp_path / f"d{i}" for i in range(6)]
    for d in dirs:
        d.mkdir()
        frame._load_directory(d)
    assert frame.recent_dirs == [str(dirs[i]) for i in (5,4,3,2,1)]

    frame._load_directory(dirs[4])
    assert frame.recent_dirs == [str(dirs[4]), str(dirs[5]), str(dirs[3]), str(dirs[2]), str(dirs[1])]

    items = [i.GetItemLabelText() for i in frame._recent_menu.GetMenuItems()]
    assert items == frame.recent_dirs

    frame.Destroy()
