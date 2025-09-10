from app.util.hashing import id_to_hash


def test_id_to_hash_deterministic():
    assert id_to_hash("REQ-1") == id_to_hash("REQ-1")


def test_id_to_hash_length_and_value():
    h = id_to_hash("REQ-1", length=16)
    assert len(h) == 16
    assert h == id_to_hash("REQ-1", length=16)
    assert h != id_to_hash("REQ-2", length=16)


def test_id_to_hash_invalid_length():
    try:
        id_to_hash("REQ-1", length=0)
    except ValueError:
        pass
    else:
        assert False, "ValueError not raised"
