from src.config import hash_password, verify_password

def test_password_hash_roundtrip():
    p = 'secret123'
    h = hash_password(p)
    assert verify_password(p, h)
