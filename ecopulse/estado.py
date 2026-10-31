"""Estado compartilhado que muda durante a execução (conexões, tarefas, banco)."""

import asyncio
import sqlite3

import httpx2 as httpx

from .config import GUILD_ID

_api: httpx.AsyncClient | None = None
_web: httpx.AsyncClient | None = None


_servidor: str | None = GUILD_ID
_servidor_ok = False
_eu: dict | None = None


_bot = None
_salvar_tarefa: asyncio.Task | None = None
_comandos_registrados = False

_db: sqlite3.Connection | None = None
_tarefa_backup: asyncio.Task | None = None
_tarefa_paineis: asyncio.Task | None = None
_tarefa_fila: asyncio.Task | None = None
