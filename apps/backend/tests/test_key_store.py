"""The key store: OS keychain through `keyring`, failing closed when there is none."""

import keyring
import keyring.backend
import keyring.backends.fail
import pytest

from app.providers.secrets import KeyringStore, KeyStoreError, MemoryKeyStore, make_key_store

SECRET = "sk-test-secret-value-123456"


class FakeKeyring(keyring.backend.KeyringBackend):
    """An in-memory keychain, so the test never touches the machine's real one."""

    priority = 1  # type: ignore[assignment]

    def __init__(self) -> None:
        self.items: dict[tuple[str, str], str] = {}

    def set_password(self, service: str, username: str, password: str) -> None:
        self.items[(service, username)] = password

    def get_password(self, service: str, username: str) -> str | None:
        return self.items.get((service, username))

    def delete_password(self, service: str, username: str) -> None:
        if (service, username) not in self.items:
            raise keyring.errors.PasswordDeleteError("not found")
        del self.items[(service, username)]


@pytest.fixture
def fake_keyring():
    previous = keyring.get_keyring()
    fake = FakeKeyring()
    keyring.set_keyring(fake)
    yield fake
    keyring.set_keyring(previous)


def test_keyring_store_round_trips_through_the_keychain(fake_keyring: FakeKeyring) -> None:
    store = KeyringStore()

    store.set("connection-a", SECRET)

    assert store.get("connection-a") == SECRET
    assert fake_keyring.items == {("hexmind", "connection-a"): SECRET}  # under our service name
    store.delete("connection-a")
    assert store.get("connection-a") is None
    store.delete("connection-a")  # deleting a missing key is not an error


def test_without_a_keychain_it_fails_closed_without_leaking_the_secret() -> None:
    previous = keyring.get_keyring()
    keyring.set_keyring(keyring.backends.fail.Keyring())
    try:
        with pytest.raises(KeyStoreError) as caught:
            KeyringStore().set("connection-a", SECRET)
        with pytest.raises(KeyStoreError):
            KeyringStore().get("connection-a")
    finally:
        keyring.set_keyring(previous)

    assert "no secure key store" in str(caught.value)
    assert SECRET not in str(caught.value)


def test_memory_store_and_factory() -> None:
    store = MemoryKeyStore()
    store.set("a", SECRET)
    assert store.get("a") == SECRET
    store.delete("a")
    assert store.get("a") is None
    assert isinstance(make_key_store("memory"), MemoryKeyStore)
    assert isinstance(make_key_store("keyring"), KeyringStore)
