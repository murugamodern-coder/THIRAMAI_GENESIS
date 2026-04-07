"""Life OS crypto + daily flow heuristics."""

from __future__ import annotations

import services.personal_crypto as pc
from services.daily_flow import append_life_os_if_relevant, user_requests_daily_flow


def test_personal_crypto_roundtrip():
    salt = pc.new_salt()
    raw = pc.derive_raw_key("my-long-passphrase-here", salt)
    assert pc.verify_raw_key(raw, pc.verifier_hash(raw))
    f = pc.fernet_from_raw(raw)
    tok = pc.encrypt_utf8(f, "secret note")
    assert pc.decrypt_utf8(f, tok) == "secret note"


def test_daily_flow_phrases():
    assert user_requests_daily_flow("Please plan my day with stock and meetings") is True
    assert user_requests_daily_flow("How is my day looking?") is True
    assert user_requests_daily_flow("random chit chat") is False


def test_append_life_os_skips_without_user():
    assert append_life_os_if_relevant("plan my day", organization_id=1, user_id=None, vault_passphrase=None) == ""
    assert append_life_os_if_relevant("plan my day", organization_id=1, user_id=0, vault_passphrase=None) == ""
