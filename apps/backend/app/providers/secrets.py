"""Where API keys live (PRD §10.2, §13.3).

Keys are kept in the operating system's keychain (macOS Keychain, Windows Credential Manager,
Linux Secret Service). Postgres stores only a reference (`key_ref`). A key is never returned by
the API, logged, put in an event or trace, committed, or mounted into the sandbox. If the system
has no usable keychain the store fails closed with a clear error; it never falls back to a
plain-text file.

The functions are blocking (the OS may show a prompt), so call them through a thread pool.
"""

from typing import Protocol

import keyring
import keyring.errors

SERVICE = "hexmind"


class KeyStoreError(RuntimeError):
    """The key store could not do what was asked. The message never contains a secret."""


class KeyStore(Protocol):
    def set(self, ref: str, secret: str) -> None: ...

    def get(self, ref: str) -> str | None: ...

    def delete(self, ref: str) -> None: ...


class KeyringStore:
    """The OS keychain, through the `keyring` package."""

    def set(self, ref: str, secret: str) -> None:
        try:
            keyring.set_password(SERVICE, ref, secret)
        except keyring.errors.KeyringError as exc:
            raise KeyStoreError(_explain(exc)) from None

    def get(self, ref: str) -> str | None:
        try:
            return keyring.get_password(SERVICE, ref)
        except keyring.errors.KeyringError as exc:
            raise KeyStoreError(_explain(exc)) from None

    def delete(self, ref: str) -> None:
        try:
            keyring.delete_password(SERVICE, ref)
        except keyring.errors.PasswordDeleteError:
            return  # already gone
        except keyring.errors.KeyringError as exc:
            raise KeyStoreError(_explain(exc)) from None


class MemoryKeyStore:
    """Keys held in this process only (tests and throwaway sessions). They are lost on exit."""

    def __init__(self) -> None:
        self._secrets: dict[str, str] = {}

    def set(self, ref: str, secret: str) -> None:
        self._secrets[ref] = secret

    def get(self, ref: str) -> str | None:
        return self._secrets.get(ref)

    def delete(self, ref: str) -> None:
        self._secrets.pop(ref, None)


def _explain(exc: Exception) -> str:
    if isinstance(exc, keyring.errors.NoKeyringError):
        return "no secure key store is available on this system, so keys cannot be saved"
    return f"the system key store refused the request ({type(exc).__name__})"


def make_key_store(kind: str) -> KeyStore:
    if kind == "memory":
        return MemoryKeyStore()
    return KeyringStore()
