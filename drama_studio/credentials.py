from __future__ import annotations

import os
import platform
import subprocess

SERVICE = "DramaStudio"


def save_api_key(provider: str, key: str) -> None:
    account = provider.lower()
    system = platform.system()
    if system == "Darwin":
        subprocess.run(["security", "add-generic-password", "-U", "-s", SERVICE, "-a", account, "-w", key], check=True, capture_output=True)
    elif system == "Windows":
        _windows_write(account, key)
    else:
        raise RuntimeError("Secure key storage is supported on macOS and Windows.")


def load_api_key(provider: str) -> str:
    env_key = os.getenv(f"{provider.upper()}_API_KEY", "")
    if env_key:
        return env_key
    account = provider.lower()
    system = platform.system()
    try:
        if system == "Darwin":
            result = subprocess.run(["security", "find-generic-password", "-s", SERVICE, "-a", account, "-w"], check=True, capture_output=True, text=True)
            return result.stdout.strip()
        if system == "Windows":
            return _windows_read(account)
    except subprocess.CalledProcessError:
        return ""
    return ""


def _windows_types():
    import ctypes
    from ctypes import wintypes

    class CREDENTIAL(ctypes.Structure):
        _fields_ = [
            ("Flags", wintypes.DWORD), ("Type", wintypes.DWORD),
            ("TargetName", wintypes.LPWSTR), ("Comment", wintypes.LPWSTR),
            ("LastWritten", wintypes.FILETIME), ("CredentialBlobSize", wintypes.DWORD),
            ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)), ("Persist", wintypes.DWORD),
            ("AttributeCount", wintypes.DWORD), ("Attributes", ctypes.c_void_p),
            ("TargetAlias", wintypes.LPWSTR), ("UserName", wintypes.LPWSTR),
        ]
    return ctypes, wintypes, CREDENTIAL


def _windows_write(account: str, key: str) -> None:
    ctypes, _, credential_type = _windows_types()
    target = f"{SERVICE}-{account}"
    blob = key.encode("utf-16-le")
    buffer = (ctypes.c_ubyte * len(blob)).from_buffer_copy(blob)
    credential = credential_type()
    credential.Type = 1  # CRED_TYPE_GENERIC
    credential.TargetName = target
    credential.CredentialBlobSize = len(blob)
    credential.CredentialBlob = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))
    credential.Persist = 2  # CRED_PERSIST_LOCAL_MACHINE
    credential.UserName = account
    if not ctypes.windll.advapi32.CredWriteW(ctypes.byref(credential), 0):
        raise ctypes.WinError()


def _windows_read(account: str) -> str:
    ctypes, _, credential_type = _windows_types()
    pointer = ctypes.POINTER(credential_type)()
    target = f"{SERVICE}-{account}"
    if not ctypes.windll.advapi32.CredReadW(target, 1, 0, ctypes.byref(pointer)):
        return ""
    try:
        credential = pointer.contents
        raw = ctypes.string_at(credential.CredentialBlob, credential.CredentialBlobSize)
        return raw.decode("utf-16-le")
    finally:
        ctypes.windll.advapi32.CredFree(pointer)
