"""Ferramentas do conector: verificação."""

import secrets
from typing import Any

from ..conector import mcp

# ── verificação ──

@mcp.tool()
async def publicar_painel_verificacao(canal_id: str, cargo: str, titulo: str | None = None, descricao: str | None = None,
                                      cor: str | None = None, imagem_url: str | None = None, miniatura_url: str | None = None,
                                      rodape: str | None = None, botao_texto: str = "Verificar", botao_emoji: str | None = "✅",
                                      botao_cor: str = "verde", tirar_cargo: str | None = None,
                                      mensagem_sucesso: str | None = None, copiar_de: str | None = None,
                                      mensagem_id: str | None = None) -> dict:
    """Publica o painel de verificação: quem clica no botão ganha o cargo (ex.: Membro) e passa a ver o servidor.
    tirar_cargo = cargo de "não verificado" para remover ao verificar. copiar_de = link/ID de outra mensagem
    para reaproveitar o visual. mensagem_id = atualizar um painel deste bot que já existe."""
    await exigir_config()
    canal = await achar_canal(canal_id, tipos=TIPOS_MENSAGEM)
    c = await achar_cargo(cargo)
    if c["id"] == await servidor_id() or c.get("managed"):
        raise ErroDiscord("Esse cargo não pode ser dado pela verificação.")
    embed, texto = await _montar_painel(
        copiar_de=copiar_de, titulo=titulo, descricao=descricao, cor=cor, imagem_url=imagem_url,
        miniatura_url=miniatura_url, rodape=rodape, titulo_padrao="🔐 Verificação",
        descricao_padrao="Clique no botão abaixo para se verificar e liberar o acesso ao servidor.")
    pid = next((k for k, p in _cfg["paineis"].items() if mensagem_id and p.get("mensagem_id") == mensagem_id), None) \
        or secrets.token_hex(3)
    painel: dict[str, Any] = {"id": pid, "tipo": "verificacao", "canal_id": canal["id"], "canal_nome": canal["name"],
                              "cargo_id": c["id"], "cargo_nome": c["name"],
                              "botao_texto": botao_texto, "botao_emoji": botao_emoji, "botao_cor": botao_cor}
    if tirar_cargo:
        t = await achar_cargo(tirar_cargo)
        painel.update(tirar_cargo_id=t["id"], tirar_cargo_nome=t["name"])
    if mensagem_sucesso:
        painel["mensagem_sucesso"] = mensagem_sucesso[:1500]
    payload: dict[str, Any] = {"embeds": [embed], "allowed_mentions": {"parse": []},
                               "components": [_linha(_botao_painel(botao_texto, f"ecov:{pid}", botao_cor, botao_emoji))]}
    if texto:
        payload["content"] = texto
    msg = await _postar(canal["id"], payload, editar_id=mensagem_id)
    painel["mensagem_id"] = msg["id"]
    _cfg["paineis"][pid] = painel
    await salvar_config()
    return {"ok": True, "painel_id": pid, "canal": canal["name"], "cargo": c["name"], "mensagem_id": msg["id"],
            "link": _link_canal(await servidor_id(), canal["id"], msg["id"])}


# Importados no fim: estes módulos também usam este aqui (evita import circular).
from ..busca import _link_canal, achar_canal, achar_cargo
from ..discord_api import ErroDiscord
from ..interface import _botao_painel, _linha
from ..memoria import _cfg, exigir_config, salvar_config
from ..paineis import _montar_painel, _postar
from ..util import TIPOS_MENSAGEM, servidor_id
