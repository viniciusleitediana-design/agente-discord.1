"""Mensagem do pedido: embed, botões do cliente e da equipe."""

import sqlite3
from typing import Any

# ── mensagem do pedido ──

def _embed_pedido(p: sqlite3.Row, pix: str | None = None, com_qr: bool = False, extra: str | None = None) -> dict:
    j = _jogo(p["jogo"])
    st = p["status"]
    cor = {AG_PAGAMENTO: NEON, AG_CONFERENCIA: CORES["amarelo"], REJEITADO: CORES["vermelho"],
           CANCELADO: CORES["cinza"], EXPIRADO: CORES["cinza"], AG_ESTOQUE: CORES["laranja"]}.get(st, NEON)
    if st == AG_PAGAMENTO:
        desc = (f'Olá, <@{p["usuario_id"]}>! Este canal é **privado**: só você e a equipe conseguem ver.\n\n'
                "**1.** Pague o Pix com o **valor exato** (QR Code ou copia e cola)\n"
                "**2.** Clique em **CONFIRMAR PAGAMENTO** e informe o nome completo de quem pagou\n"
                "**3.** A equipe confere o Pix e libera sua key num canal privado de entrega\n\n"
                "⚠️ Clicar em CONFIRMAR PAGAMENTO **não** libera a key sozinho: a equipe confere o recebimento antes.")
    elif st == AG_CONFERENCIA:
        desc = (f'<@{p["usuario_id"]}> informou o pagamento. A equipe está conferindo o Pix.\n\n'
                f'👤 **Pagador:** {decifrar(p["pagador_cifrado"])}')
    else:
        desc = extra or ""
    campos = [
        {"name": "🎮 Jogo", "value": _rotulo_jogo(j), "inline": True},
        {"name": "📦 Produto", "value": p["produto_nome"], "inline": True},
        {"name": "⏳ Duração", "value": _duracao(p["dias"]), "inline": True},
        {"name": "💰 Valor", "value": f'**{_reais_c(p["preco_centavos"])}**', "inline": True},
        {"name": "🆔 Pedido", "value": f'`{p["id"]}`', "inline": True},
        {"name": "📌 Status", "value": ROTULO_STATUS.get(st, st), "inline": True},
    ]
    if pix and st == AG_PAGAMENTO:
        campos.append({"name": "📋 Pix copia e cola", "value": f"```{pix}```"[:1024], "inline": False})
        if p["link_pagamento"]:
            campos.append({"name": "🔗 Link de pagamento", "value": p["link_pagamento"][:1024], "inline": False})
    embed: dict[str, Any] = {"title": f'🧾 Pedido {p["id"]}', "description": desc[:4096], "color": cor, "fields": campos,
                             "footer": {"text": "ECO CHEATS • Pague somente pelos dados deste canal • o pedido expira em 24 h sem pagamento"
                                        if st == AG_PAGAMENTO else "ECO CHEATS • Vendas automáticas"}}
    if com_qr:
        embed["image"] = {"url": "attachment://pix.png"}
    elif pix and st == AG_PAGAMENTO:
        embed["image"] = {"url": _qr_url_online(pix)}
    return embed


def _botoes_cliente(p: sqlite3.Row) -> list[dict]:
    botoes = [_botao("CONFIRMAR PAGAMENTO", f'ecvd:pagar:{p["id"]}', 3, "✅")]
    if p["link_pagamento"]:
        botoes.append({"type": 2, "style": 5, "label": "Pagar pelo link", "url": p["link_pagamento"], "emoji": {"name": "💳"}})
    botoes.append(_botao("CANCELAR PEDIDO", f'ecvd:cancelar:{p["id"]}', 4, "✖️"))
    return [_linha(*botoes)]


def _botoes_admin(pid: str) -> list[dict]:
    return [_linha(_botao("APROVAR PAGAMENTO", f"ecvd:aprovar:{pid}", 3, "✅"),
                   _botao("REJEITAR PAGAMENTO", f"ecvd:rejeitar:{pid}", 4, "⛔"))]


def _pedido(pid: str) -> sqlite3.Row | None:
    return _q1("SELECT * FROM pedidos WHERE id = ?", (pid,))


async def _editar_msg_pedido(p: sqlite3.Row, embed: dict, componentes: list[dict]) -> None:
    if not (p["canal_pagamento_id"] and p["mensagem_pedido_id"]) or p["pagamento_apagado"]:
        return
    try:
        await dc("PATCH", f'/channels/{p["canal_pagamento_id"]}/messages/{p["mensagem_pedido_id"]}',
                 corpo={"embeds": [embed], "components": componentes, "attachments": []})
    except ErroDiscord as erro:
        log.warning("Não consegui atualizar a mensagem do pedido %s: %s", p["id"], erro)


# Importados no fim: estes módulos também usam este aqui (evita import circular).
from ..config import log
from ..discord_api import ErroDiscord, dc
from ..interface import _botao, _linha
from ..pix import _qr_url_online
from ..util import CORES
from .banco import _duracao, _jogo, _q1, _reais_c, _rotulo_jogo
from .base import AG_CONFERENCIA, AG_ESTOQUE, AG_PAGAMENTO, CANCELADO, EXPIRADO, NEON, REJEITADO, ROTULO_STATUS
from .cofre import decifrar
