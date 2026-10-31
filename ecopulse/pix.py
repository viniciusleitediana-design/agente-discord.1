"""Pix: código copia e cola (BR Code com CRC16) e QR Code."""

import io
import re
import unicodedata
from urllib.parse import quote

def _campo_emv(id_: str, valor: str) -> str:
    return f"{id_}{len(valor):02d}{valor}"


def _crc16(texto: str) -> str:
    """CRC16-CCITT (0x1021, início 0xFFFF), o mesmo que o Banco Central usa no Pix."""
    crc = 0xFFFF
    for byte in texto.encode("utf-8"):
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) if crc & 0x8000 else (crc << 1)
            crc &= 0xFFFF
    return f"{crc:04X}"


def _ascii_pix(texto: str, limite: int, padrao: str) -> str:
    s = unicodedata.normalize("NFKD", str(texto)).encode("ascii", "ignore").decode()
    s = re.sub(r"[^A-Za-z0-9 ]", "", s).strip().upper()
    return s[:limite].strip() or padrao


def gerar_pix(valor: float | None, txid: str) -> str | None:
    """Monta o Pix "copia e cola" (BR Code estático) com a chave do Render e o valor do produto."""
    if PIX_COPIA_COLA:
        return PIX_COPIA_COLA
    if not PIX_CHAVE:
        return None
    chave = PIX_CHAVE.strip()
    if "@" in chave:
        chave = chave.lower()
    conta = _campo_emv("00", "br.gov.bcb.pix") + _campo_emv("01", chave)
    corpo = _campo_emv("00", "01") + _campo_emv("01", "11") + _campo_emv("26", conta) + _campo_emv("52", "0000") + _campo_emv("53", "986")
    if valor:
        corpo += _campo_emv("54", f"{valor:.2f}")
    corpo += _campo_emv("58", "BR") + _campo_emv("59", _ascii_pix(PIX_NOME, 25, "ECO PULSE"))
    corpo += _campo_emv("60", _ascii_pix(PIX_CIDADE, 15, "SAO PAULO"))
    corpo += _campo_emv("62", _campo_emv("05", re.sub(r"[^A-Za-z0-9]", "", txid)[:25] or "***"))
    corpo += "6304"
    return corpo + _crc16(corpo)


def _qr_png(texto: str) -> bytes | None:
    try:
        import segno
        buf = io.BytesIO()
        segno.make_qr(texto, error="m").save(buf, kind="png", scale=8, border=3)
        return buf.getvalue()
    except Exception as erro:
        log.warning("Não consegui gerar o QR Code localmente (%s); usando gerador online.", erro)
        return None


def _qr_url_online(texto: str) -> str:
    return "https://api.qrserver.com/v1/create-qr-code/?size=420x420&margin=12&data=" + quote(texto, safe="")


# Importados no fim: estes módulos também usam este aqui (evita import circular).
from .config import PIX_CHAVE, PIX_CIDADE, PIX_COPIA_COLA, PIX_NOME, log
