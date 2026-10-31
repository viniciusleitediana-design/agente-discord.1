"""Configuração: variáveis de ambiente, log e constantes gerais."""

import logging
import os
import time
from datetime import timedelta
from zoneinfo import ZoneInfo

try:  # cofre das keys e credenciais das vendas
    from cryptography.fernet import Fernet, InvalidToken
except Exception:  # pragma: no cover
    Fernet = None

    class InvalidToken(Exception):
        pass

try:  # o gateway (eventos em tempo real) é opcional: sem ele o resto continua funcionando
    import discord
except Exception:  # pragma: no cover
    discord = None

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("eco-pulse")

VERSAO = "5.0"
INICIO = time.time()


def _env(*nomes: str, padrao: str | None = None) -> str | None:
    for nome in nomes:
        valor = os.getenv(nome)
        if valor and valor.strip():
            return valor.strip()
    return padrao


TOKEN = (_env("DISCORD_TOKEN", "DISCORD_BOT_TOKEN", "BOT_TOKEN", "TOKEN", "TOKEN_DISCORD",
                "TOKEN_BOT", "DISCORD_KEY", "DISCORD") or "").removeprefix("Bot ").strip()
GUILD_ID = _env("GUILD_ID", "DISCORD_GUILD_ID", "SERVIDOR_ID", "SERVER_ID", "ID_SERVIDOR",
                "DISCORD_SERVER_ID", "GUILD")
# Caminho secreto do endereço do conector: fica só na variável CHAVE_SECRETA, nunca no código.
CHAVE = (_env("CHAVE_SECRETA") or "").strip().strip("/")
FUSO = ZoneInfo(_env("FUSO", padrao="America/Sao_Paulo"))
API = (_env("DISCORD_API", padrao="https://discord.com/api/v10")).rstrip("/")
PORTA = int(_env("PORT", padrao="10000"))
MANTER_ACORDADO = (_env("MANTER_ACORDADO", padrao="1") or "1").lower() not in ("0", "false", "nao", "não", "off")
CONFIG_CANAL_ID = _env("CONFIG_CANAL_ID")
PIX_CHAVE = _env("PIX_CHAVE", "CHAVE_PIX")
PIX_NOME = _env("PIX_NOME", padrao="ECO PULSE")
PIX_CIDADE = _env("PIX_CIDADE", padrao="SAO PAULO")
PIX_COPIA_COLA = _env("PIX_COPIA_COLA")

RAIZ_PROJETO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # pasta do server.py

NOME_CANAL_CONFIG = "agente-config"
ARQUIVO_CONFIG = "agente-config.json"
TOLERANCIA_ATRASO = timedelta(hours=6)   # mensagem agendada atrasada mais que isso é pulada
COR_PADRAO = 0x22C55E                     # verde ECO PULSE
