"""Cofre: keys, logins e nomes de pagadores cifrados (Fernet)."""

import base64
import hashlib
import hmac

# ── cofre: keys, logins e nomes de pagadores ficam cifrados no banco (e nos backups) ──

def _chave_cofre() -> bytes:
    bruto = _env("CHAVE_COFRE")
    if bruto:
        try:
            Fernet(bruto.encode())
            return bruto.encode()
        except Exception:
            pass
    else:
        log.warning("CHAVE_COFRE não está no Render: usando uma chave derivada do token (crie CHAVE_COFRE para não depender dele).")
    semente = (bruto or TOKEN or "eco-cheats").encode()
    return base64.urlsafe_b64encode(hashlib.sha256(b"eco-cofre:" + semente).digest())


_FERNET_CACHE: list = []


def _fernet():
    if not _FERNET_CACHE:
        if Fernet is None:
            raise ErroDiscord("A biblioteca cryptography não está instalada (confira o requirements.txt).")
        _FERNET_CACHE.append(Fernet(_chave_cofre()))
    return _FERNET_CACHE[0]


def cifrar(texto: str) -> str:
    return _fernet().encrypt(texto.encode()).decode()


def decifrar(texto: str | None) -> str:
    if not texto:
        return ""
    try:
        return _fernet().decrypt(texto.encode()).decode()
    except InvalidToken:
        return "⚠️ (não consegui decifrar: a CHAVE_COFRE mudou)"


def _hash_key(valor: str) -> str:
    return hmac.new(_chave_cofre(), b"key:" + valor.encode(), hashlib.sha256).hexdigest()


def _mascarar(valor: str) -> str:
    v = valor.strip()
    return f"••••{v[-4:]}" if len(v) > 4 else "••••"


# Importados no fim: estes módulos também usam este aqui (evita import circular).
from ..config import Fernet, InvalidToken, TOKEN, _env, log
from ..discord_api import ErroDiscord
