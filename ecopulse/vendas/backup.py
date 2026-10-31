"""Backup do banco no Discord (o disco do Render é apagado a cada deploy)."""

import asyncio
import json
import os
import sqlite3
import tempfile
import time
from typing import Any

from .. import estado

# ── backup no Discord (o disco do Render não é permanente) ──

async def _canal_backup_vendas() -> str:
    salvo = _cfg_vendas("canal_backup_id") if estado._db is not None else None
    if salvo:
        return salvo
    canais = await _canais()
    for c in canais:
        if c["type"] == 0 and "backup" in _norm(c["name"]):
            return c["id"]
    gid, bot = await servidor_id(), await eu()
    staff = next((c for c in canais if c["type"] == 4 and "staff" in _norm(c["name"])), None)
    corpo: dict[str, Any] = {"name": "🗄️・backups-bot", "type": 0,
                             "topic": "Cópias automáticas do banco de vendas (dados sensíveis cifrados). Não apague.",
                             "permission_overwrites": [{"id": gid, "type": 0, "allow": "0", "deny": str(VER)},
                                                       {"id": bot["id"], "type": 1, "allow": str(VER | ENVIAR | ANEXAR | HISTORICO), "deny": "0"}]}
    if staff:
        corpo["parent_id"] = staff["id"]
    return (await dc("POST", f"/guilds/{gid}/channels", corpo=corpo, motivo="Backups do banco de vendas"))["id"]


def _fotografar_db() -> bytes:
    assert estado._db is not None
    with tempfile.TemporaryDirectory() as pasta:
        destino = os.path.join(pasta, "copia.sqlite")
        alvo = sqlite3.connect(destino)
        estado._db.backup(alvo)
        alvo.close()
        with open(destino, "rb") as f:
            return f.read()


async def backup_vendas(motivo: str = "alteração") -> None:
    if estado._db is None or not _vendas["pronto"]:
        return
    canal = await _canal_backup_vendas()
    dados = _fotografar_db()
    payload = {"content": f'🗄️ Banco de vendas • {_fmt(_agora())} • {motivo} • instância {_vendas["instancia"]}. Não apague.',
               "attachments": [{"id": 0, "filename": ARQ_BACKUP_VENDAS}]}
    msg = await dc("POST", f"/channels/{canal}/messages", dados={"payload_json": json.dumps(payload)},
                   arquivos={"files[0]": (ARQ_BACKUP_VENDAS, dados, "application/octet-stream")})
    _vendas["backup_msg"] = msg["id"]
    try:  # mantém só os últimos backups
        msgs = await dc("GET", f"/channels/{canal}/messages", params={"limit": 50})
        bot = (await eu())["id"]
        meus = [m for m in msgs if m["author"]["id"] == bot and any(a["filename"] == ARQ_BACKUP_VENDAS for a in m.get("attachments", []))]
        for velho in meus[MANTER_BACKUPS:]:
            await dc("DELETE", f'/channels/{canal}/messages/{velho["id"]}')
    except ErroDiscord as erro:
        log.warning("Não consegui limpar backups antigos: %s", erro)


def _backup_depois(segundos: float = 4) -> None:
    _vendas["sujo"] = True
    if estado._tarefa_backup and not estado._tarefa_backup.done():
        return

    async def _rodar():
        await asyncio.sleep(segundos)
        while _vendas.get("sujo"):
            _vendas["sujo"] = False
            for tentativa in range(3):
                try:
                    await backup_vendas()
                    break
                except Exception as erro:
                    log.warning("Backup do banco de vendas falhou (%s); tentando de novo.", erro)
                    await asyncio.sleep(10)
            else:
                _vendas["sujo"] = True
                await asyncio.sleep(30)

    try:
        estado._tarefa_backup = asyncio.get_running_loop().create_task(_rodar())
    except RuntimeError:
        pass


async def _ultimo_backup() -> tuple[dict | None, str]:
    canal = await _canal_backup_vendas()
    msgs = await dc("GET", f"/channels/{canal}/messages", params={"limit": 50})
    bot = (await eu())["id"]
    for m in msgs:  # da mais nova para a mais antiga
        if m["author"]["id"] != bot:
            continue
        anexo = next((a for a in m.get("attachments", []) if a["filename"] == ARQ_BACKUP_VENDAS), None)
        if anexo:
            return {"msg": m, "anexo": anexo}, canal
    return None, canal


async def _restaurar(backup: dict) -> None:
    resp = await cliente_web().get(await _refrescar_url(backup["anexo"]["url"]))
    resp.raise_for_status()
    os.makedirs(os.path.dirname(VENDAS_DB), exist_ok=True)
    temporario = VENDAS_DB + ".restaurando"
    with open(temporario, "wb") as f:
        f.write(resp.content)
    teste = sqlite3.connect(temporario)
    try:
        ok = teste.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        teste.execute("SELECT COUNT(*) FROM pedidos").fetchone()
    finally:
        teste.close()
    if not ok:
        raise RuntimeError("backup corrompido")
    if estado._db is not None:
        estado._db.close()
    os.replace(temporario, VENDAS_DB)
    estado._db = _abrir_db(VENDAS_DB)
    _vendas["restaurado"] = backup["msg"]["id"]


async def iniciar_vendas() -> None:
    """Restaura o banco do último backup (ou cria um novo, se nunca houve backup) e deixa o sistema pronto."""
    async with _vendas_lock:
        if _vendas["pronto"]:
            return
        if Fernet is None:
            _vendas["aviso"] = "biblioteca cryptography não instalada"
            return
        try:
            backup, _ = await _ultimo_backup()
        except Exception as erro:
            _vendas["aviso"] = f"não consegui ler os backups ({erro}); tentando de novo"
            log.warning("Vendas: %s", _vendas["aviso"])
            return  # nunca começa um banco vazio sem ter certeza de que não existe backup
        try:
            if backup:
                await _restaurar(backup)
                log.info("Vendas: banco restaurado do backup %s", backup["msg"]["id"])
            else:
                os.makedirs(os.path.dirname(VENDAS_DB), exist_ok=True)
                if estado._db is None:
                    if os.path.exists(VENDAS_DB):
                        os.remove(VENDAS_DB)
                    estado._db = _abrir_db(VENDAS_DB)
                log.info("Vendas: nenhum backup encontrado, banco novo criado")
        except Exception as erro:
            _vendas["aviso"] = f"não consegui restaurar o backup ({erro}); tentando de novo"
            log.exception("Vendas: falha ao restaurar")
            return
        assert estado._db is not None
        try:
            fund = next((c for c in await _cargos() if _norm(c["name"]) == "fundador"), None)
            logc = next((c for c in await _canais() if c["type"] == 0 and "registrodevendas" in _norm(c["name"])), None)
            canal_backup = await _canal_backup_vendas()
        except Exception as erro:
            _vendas["aviso"] = f"não consegui ler cargos/canais ({erro}); tentando de novo"
            return
        estado._db.execute("BEGIN IMMEDIATE")
        try:
            _semear(estado._db)
            if fund and not _cfg_vendas("cargo_fundador_id"):
                estado._db.execute("INSERT OR REPLACE INTO config VALUES ('cargo_fundador_id', ?)", (fund["id"],))
            if logc and not _cfg_vendas("canal_logs_id"):
                estado._db.execute("INSERT OR REPLACE INTO config VALUES ('canal_logs_id', ?)", (logc["id"],))
            estado._db.execute("INSERT OR REPLACE INTO config VALUES ('canal_backup_id', ?)", (canal_backup,))
            estado._db.execute("COMMIT")
        except Exception:
            estado._db.execute("ROLLBACK")
            raise
        _vendas.update(pronto=True, aviso=None, iniciado=time.time(), escritas=0)
    if not backup:
        await backup_vendas("banco criado")
    await _limpar_keys_invalidas_seguro()
    _paineis_depois(2, criar=True)


async def _limpar_keys_invalidas_seguro() -> None:
    try:
        _limpar_keys_invalidas((await eu())["id"])
    except Exception:
        log.exception("Vendas: falha ao conferir o estoque")


async def _rechecar_backup() -> None:
    """Num deploy, a instância antiga pode salvar um backup segundos depois de a nova já ter restaurado.
    Se isso acontecer e esta instância ainda não alterou nada, ela restaura a versão mais nova."""
    if not _vendas["pronto"] or _vendas["rechecagens"] >= 2 or time.time() - _vendas["iniciado"] < 40:
        return
    _vendas["rechecagens"] += 1
    try:
        backup, _ = await _ultimo_backup()
    except Exception:
        return
    if not backup or backup["msg"]["id"] in (_vendas["restaurado"], _vendas["backup_msg"]):
        return
    if f'instância {_vendas["instancia"]}' in backup["msg"].get("content", ""):
        return
    if _vendas["escritas"] == 0:
        log.info("Vendas: backup mais novo de outra instância encontrado; restaurando")
        await _restaurar(backup)
        await _limpar_keys_invalidas_seguro()
    else:
        log.warning("Vendas: existe um backup mais novo de outra instância, mas esta já gravou dados; mantendo o atual")


async def registrar_venda_log(texto: str) -> None:
    canal = _cfg_vendas("canal_logs_id")
    if canal:
        try:
            await dc("POST", f"/channels/{canal}/messages", corpo={"content": texto[:2000], "allowed_mentions": {"parse": []}})
        except ErroDiscord as erro:
            log.warning("Falha no registro de vendas: %s", erro)


# Importados no fim: estes módulos também usam este aqui (evita import circular).
from ..busca import _canais, _cargos
from ..config import Fernet, log
from ..discord_api import ErroDiscord, cliente_web, dc
from ..paineis import _refrescar_url
from ..util import ANEXAR, ENVIAR, HISTORICO, VER, _agora, _fmt, _norm, eu, servidor_id
from .banco import _abrir_db, _cfg_vendas, _semear
from .base import ARQ_BACKUP_VENDAS, MANTER_BACKUPS, VENDAS_DB, _vendas, _vendas_lock
from .comandos import _limpar_keys_invalidas
from .paineis import _paineis_depois
