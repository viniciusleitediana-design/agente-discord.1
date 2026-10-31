"""Memória das automações: configuração salva como anexo num canal privado do próprio servidor."""

import asyncio
import json
import time
from copy import deepcopy
from typing import Any

from . import estado

CONFIG_PADRAO: dict[str, Any] = {"versao": 1, "agendadas": [], "boas_vindas": {}, "despedida": {},
                                 "respostas": [], "cargos_reacao": [], "logs": {},
                                 "produtos": {}, "compras": {}, "paineis": {}, "tickets": {}, "sorteios": {}, "vendas": [], "entregas": {}}
_cfg: dict[str, Any] = deepcopy(CONFIG_PADRAO)
_cfg_estado: dict[str, Any] = {"carregada": False, "canal_id": None, "msg_id": None, "aviso": None, "tentativa": 0.0}
_cfg_lock = asyncio.Lock()


async def _canal_config() -> str:
    if CONFIG_CANAL_ID:
        return CONFIG_CANAL_ID
    canais = await _canais()
    for c in canais:
        if c["type"] == 0 and c["name"] == NOME_CANAL_CONFIG:
            return c["id"]
    gid, bot = await servidor_id(), await eu()
    corpo: dict[str, Any] = {
        "name": NOME_CANAL_CONFIG, "type": 0,
        "topic": "Memória do agente ECO PULSE (automações). Não apague as mensagens deste canal.",
        "permission_overwrites": [
            {"id": gid, "type": 0, "allow": "0", "deny": str(VER)},
            {"id": bot["id"], "type": 1, "allow": str(VER | ENVIAR | ANEXAR | HISTORICO), "deny": "0"},
        ],
    }
    staff = next((c for c in canais if c["type"] == 4 and "staff" in _norm(c["name"])), None)
    if staff:
        corpo["parent_id"] = staff["id"]
    novo = await dc("POST", f"/guilds/{gid}/channels", corpo=corpo, motivo="Memória do agente ECO PULSE")
    log.info("Canal de memória criado: %s", novo["id"])
    return novo["id"]


async def carregar_config(forcar: bool = False) -> None:
    async with _cfg_lock:
        if _cfg_estado["carregada"] and not forcar:
            return
        _cfg_estado["tentativa"] = time.time()
        try:
            canal = await _canal_config()
            _cfg_estado["canal_id"] = canal
            bot = await eu()
            mensagens = await dc("GET", f"/channels/{canal}/messages", params={"limit": 50})
            for msg in mensagens:  # da mais nova para a mais antiga
                if msg["author"]["id"] != bot["id"]:
                    continue
                anexo = next((a for a in msg.get("attachments", []) if a["filename"] == ARQUIVO_CONFIG), None)
                if not anexo:
                    continue
                resp = await cliente_web().get(anexo["url"])
                resp.raise_for_status()
                novo = deepcopy(CONFIG_PADRAO)
                novo.update(resp.json())
                _cfg.clear()
                _cfg.update(novo)
                _cfg_estado["msg_id"] = msg["id"]
                break
            _cfg_estado["carregada"] = True
            _cfg_estado["aviso"] = None
            log.info("Memória carregada: %d agendadas, %d respostas, %d cargos por reação",
                     len(_cfg["agendadas"]), len(_cfg["respostas"]), len(_cfg["cargos_reacao"]))
        except Exception as erro:
            _cfg_estado["aviso"] = f"Não consegui ler a memória das automações: {erro}"
            log.warning(_cfg_estado["aviso"])


async def garantir_config() -> None:
    if not _cfg_estado["carregada"] and time.time() - _cfg_estado["tentativa"] > 30:
        await carregar_config()


async def exigir_config() -> None:
    """Antes de mudar automações: sem ler a memória, mudar poderia apagar o que já existe."""
    if not _cfg_estado["carregada"]:
        await carregar_config()
    if not _cfg_estado["carregada"]:
        raise ErroDiscord((_cfg_estado["aviso"] or "Não consegui ler a memória das automações.") +
                          " Confira se o bot tem permissão de Administrador e tente de novo.")


async def salvar_config() -> None:
    _fila_depois()
    async with _cfg_lock:
        canal = _cfg_estado["canal_id"] or await _canal_config()
        _cfg_estado["canal_id"] = canal
        conteudo = json.dumps(_cfg, ensure_ascii=False, indent=1).encode()
        payload = {"content": f"🧠 Memória do agente ECO PULSE — atualizada {_fmt(_agora())}. Não apague.",
                   "attachments": [{"id": 0, "filename": ARQUIVO_CONFIG}]}
        msg = await dc("POST", f"/channels/{canal}/messages", dados={"payload_json": json.dumps(payload)},
                       arquivos={"files[0]": (ARQUIVO_CONFIG, conteudo, "application/json")})
        antiga, _cfg_estado["msg_id"] = _cfg_estado["msg_id"], msg["id"]
        if antiga:
            try:
                await dc("DELETE", f"/channels/{canal}/messages/{antiga}")
            except ErroDiscord:
                pass


async def registrar(texto: str) -> None:
    """Manda uma linha para o canal de registros, se estiver configurado."""
    logs = _cfg.get("logs") or {}
    if not logs.get("ativo") or not logs.get("canal_id"):
        return
    try:
        await dc("POST", f'/channels/{logs["canal_id"]}/messages',
                 corpo={"content": texto[:2000], "allowed_mentions": {"parse": []}})
    except ErroDiscord as erro:
        log.warning("Falha ao registrar no canal de logs: %s", erro)


def _salvar_depois(segundos: float = 15) -> None:
    """Junta várias mudanças pequenas (ex.: cliques em sorteio) em um salvamento só."""
    if estado._salvar_tarefa and not estado._salvar_tarefa.done():
        return

    async def _rodar():
        await asyncio.sleep(segundos)
        try:
            await salvar_config()
        except Exception:
            log.exception("Falha ao salvar a memória")

    estado._salvar_tarefa = asyncio.create_task(_rodar())


async def _salvar_pendente() -> None:
    """No desligamento: salva na hora o que estava esperando para ser salvo."""
    if estado._salvar_tarefa and not estado._salvar_tarefa.done():
        estado._salvar_tarefa.cancel()
        try:
            await salvar_config()
        except Exception:
            log.exception("Falha ao salvar a memória no desligamento")


# Importados no fim: estes módulos também usam este aqui (evita import circular).
from .busca import _canais
from .central import _fila_depois
from .config import ARQUIVO_CONFIG, CONFIG_CANAL_ID, NOME_CANAL_CONFIG, log
from .discord_api import ErroDiscord, cliente_web, dc
from .util import ANEXAR, ENVIAR, HISTORICO, VER, _agora, _fmt, _norm, eu, servidor_id
