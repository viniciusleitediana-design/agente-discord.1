"""Painéis de venda: 1 por canal de jogo, com menu de planos, preço e estoque."""

import asyncio
import sqlite3
from typing import Any

from .. import estado

# ── painéis de venda (1 por canal de jogo) ──

def _embed_painel(j: sqlite3.Row) -> dict:
    intro = j["descricao"] or (f'Keys para **{j["nome"]}** na plataforma **{j["plataforma"]}**.\n'
                               "Escolha o plano no menu abaixo e finalize a compra num canal privado só seu.")
    descricao = (f"{intro}\n\n"
                 "💳 **PAGAMENTO**\nPix com QR Code e copia e cola, gerado com o **valor exato** do plano escolhido. "
                 "A equipe confere cada pagamento antes de liberar a key.\n\n"
                 "🛒 **COMO COMPRAR**\n**1.** Escolha o plano no menu abaixo\n"
                 "**2.** Um canal privado de pagamento é criado só para você\n"
                 "**3.** Pague o Pix e clique em **CONFIRMAR PAGAMENTO**\n"
                 "**4.** Informe o nome completo de quem pagou\n"
                 "**5.** Aprovado o pagamento, o passo a passo, seu login e sua key chegam num **canal privado de entrega**")
    embed: dict[str, Any] = {"title": f'{j["emoji"] or "🟢"} ECO CHEATS • {j["nome"].upper()} {j["plataforma"].upper()}',
                             "description": descricao[:4096], "color": NEON,
                             "footer": {"text": "ECO CHEATS • Pagamento via Pix • Entrega em canal privado"}}
    if j["imagem_url"]:
        embed["image"] = {"url": j["imagem_url"]}
    return embed


def _menu_painel(j: sqlite3.Row) -> dict:
    opcoes = []
    for p in sorted(_q("SELECT * FROM produtos WHERE jogo = ? AND ativo = 1", (j["id"],)),
                    key=lambda p: _ORDEM_PLANOS.get(p["plano"], 99)):
        if p["usa_keys"]:
            est = _estoque(j["id"], p["plano"])["livre"]
            estoque = f"Estoque: {est}" if est else "Esgotado"
        else:
            estoque = "Estoque: ∞"
        opcoes.append({"label": p["nome"][:100], "value": p["plano"], "emoji": {"name": "🔑"},
                       "description": f'Preço: {_reais_c(p["preco_centavos"])} | {estoque}'[:100]})
    menu: dict[str, Any] = {"type": 3, "custom_id": f'ecvd:menu:{j["id"]}', "placeholder": "➡️ Clique aqui para ver as opções",
                            "min_values": 1, "max_values": 1}
    if opcoes:
        menu["options"] = opcoes
    else:
        menu.update(options=[{"label": "Vendas pausadas", "value": "nada"}], disabled=True, placeholder="Vendas pausadas no momento")
    return {"type": 1, "components": [menu]}


async def _achar_painel_existente(canal_id: str, jid: str) -> str | None:
    """Antes de publicar, procura um painel deste bot já no canal (evita duplicar)."""
    try:
        msgs = await dc("GET", f"/channels/{canal_id}/messages", params={"limit": 50})
    except ErroDiscord:
        return None
    bot = (await eu())["id"]
    for m in msgs:
        if m["author"]["id"] != bot:
            continue
        for linha in m.get("components", []):
            for c in linha.get("components", []):
                if c.get("custom_id") == f"ecvd:menu:{jid}":
                    return m["id"]
    return None


async def atualizar_painel(jid: str, criar: bool) -> str:
    j = _jogo(jid)
    if not j["canal_id"]:
        return f'{_rotulo_jogo(j)}: sem canal configurado'
    payload = {"embeds": [_embed_painel(j)], "components": [_menu_painel(j)], "allowed_mentions": {"parse": []}}
    msg_id = j["mensagem_id"]
    if msg_id:
        try:
            await _postar(j["canal_id"], payload, editar_id=msg_id)
            return f'{_rotulo_jogo(j)}: atualizado'
        except ErroDiscord as erro:
            if erro.codigo != 10008 and erro.status != 404:
                raise
            msg_id = None  # a mensagem foi apagada
    if not criar:
        return f'{_rotulo_jogo(j)}: sem painel publicado'
    existente = await _achar_painel_existente(j["canal_id"], jid)
    if existente:
        await _postar(j["canal_id"], payload, editar_id=existente)
        novo_id, acao = existente, "reaproveitado"
    else:
        novo_id, acao = (await _postar(j["canal_id"], payload))["id"], "publicado"
    with _tx() as conn:
        conn.execute("UPDATE jogos SET mensagem_id = ? WHERE id = ?", (novo_id, jid))
    return f'{_rotulo_jogo(j)}: {acao}'


async def sincronizar_paineis(criar: bool, jogos: set[str] | None = None) -> list[str]:
    resultado = []
    for j in _q("SELECT id FROM jogos WHERE ativo = 1 ORDER BY ordem"):
        if jogos is not None and j["id"] not in jogos:
            continue
        try:
            resultado.append(await atualizar_painel(j["id"], criar))
        except ErroDiscord as erro:
            resultado.append(f'{j["id"]}: erro — {erro}')
            log.warning("Painel %s: %s", j["id"], erro)
    return resultado


_paineis_pendentes: dict[str, Any] = {"jogos": set(), "todos": False, "criar": False}


def _paineis_depois(segundos: float = 5, criar: bool = False, jogo: str | None = None) -> None:
    if jogo:
        _paineis_pendentes["jogos"].add(jogo)
    else:
        _paineis_pendentes["todos"] = True
    _paineis_pendentes["criar"] = _paineis_pendentes["criar"] or criar
    if estado._tarefa_paineis and not estado._tarefa_paineis.done():
        return

    async def _rodar():
        await asyncio.sleep(segundos)
        while _paineis_pendentes["todos"] or _paineis_pendentes["jogos"]:
            jogos = None if _paineis_pendentes["todos"] else set(_paineis_pendentes["jogos"])
            criar_agora = _paineis_pendentes["criar"]
            _paineis_pendentes.update(jogos=set(), todos=False, criar=False)
            try:
                await sincronizar_paineis(criar_agora, jogos)
            except Exception:
                log.exception("Falha ao atualizar os painéis de venda")

    try:
        estado._tarefa_paineis = asyncio.get_running_loop().create_task(_rodar())
    except RuntimeError:
        pass


# Importados no fim: estes módulos também usam este aqui (evita import circular).
from ..config import log
from ..discord_api import ErroDiscord, dc
from ..paineis import _postar
from ..util import eu
from .banco import _estoque, _jogo, _q, _reais_c, _rotulo_jogo, _tx
from .base import NEON, _ORDEM_PLANOS
