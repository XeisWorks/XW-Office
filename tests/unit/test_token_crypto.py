"""Token crypto tests."""
import pytest
from cryptography.fernet import Fernet

from xw_office.core.exceptions import ConfigError
from xw_office.core.token_crypto import decrypt_secret, encrypt_secret


def test_round_trip() -> None:
    key = Fernet.generate_key().decode("ascii")
    ct = encrypt_secret("secret-value", key)
    assert decrypt_secret(ct, key) == "secret-value"


def test_bad_key_raises() -> None:
    key = Fernet.generate_key().decode("ascii")
    ct = encrypt_secret("x", key)
    with pytest.raises(ConfigError):
        decrypt_secret(ct, Fernet.generate_key().decode("ascii"))
