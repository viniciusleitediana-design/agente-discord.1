"""Compra: menu, Pix exato, pagamento informado, aprovação e rejeição pelo FUNDADOR."""

import json
import re
import time
from datetime import datetime, timedelta
from typing import Any

from ..discord_api import _Resposta

# ── compra ──

async def _vendas_menu(r: _Resposta, jid: str, plano: str) -> None:
    inter = r.inter
    uid = str(inter.user.id)
    await r.enviar(6)  # responde na hora (sem mexer no painel); o resto vem como mensagem só para a pessoa
    if not _vendas["pronto"]:
        await r.efemera("O sistema de vendas está iniciando. Tente de novo em alguns segundos.")
        return
    if time.time() - _cliques_menu.get(uid, 0) < 4:
        await r.efemera("Calma! Seu pedido anterior ainda está sendo criado.")
        return
    _cliques_menu[uid] = time.time()
    try:
        j = _jogo(jid)
        prod = _produto(jid, plano)
    except ErroDiscord:
        await r.efemera("Esta opção não existe mais. Atualize o painel.")
        return
    if not j["ativo"] or not prod["ativo"]:
        await r.efemera("Este plano não está à venda no momento.")
        return
    async with _vendas_lock:
        aberto = _q1(f"SELECT * FROM pedidos WHERE usuario_id = ? AND jogo = ? AND status IN "
                     f"({','.join('?' * len(STATUS_ABERTOS_VENDA))}) ORDER BY criado_em DESC", (uid, jid, *STATUS_ABERTOS_VENDA))
        if aberto:
            recente = datetime.fromisoformat(aberto["criado_em"]) > _agora() - timedelta(seconds=90)
            if not aberto["canal_pagamento_id"] and recente:
                await r.efemera("Seu pedido já está sendo criado. Aguarde alguns segundos.")
                return
            if aberto["canal_pagamento_id"] and not aberto["pagamento_apagado"] and await _canal_existe(aberto["canal_pagamento_id"]):
                await r.efemera(f'Você já tem um pedido aberto deste jogo: <#{aberto["canal_pagamento_id"]}> (pedido `{aberto["id"]}`).')
                return
            if aberto["status"] != AG_PAGAMENTO:
                await r.efemera(f'Você já tem um pedido em andamento deste jogo (`{aberto["id"]}`). Se precisar, abra um ticket de suporte.')
                return
            with _tx() as conn:  # o canal de pagamento sumiu: encerra o pedido antigo sem pagamento
                conn.execute("UPDATE pedidos SET status = ?, pagamento_apagado = 1 WHERE id = ? AND status = ?",
                             (CANCELADO, aberto["id"], AG_PAGAMENTO))
                _auditar(conn, "cancelado_canal_sumiu", aberto["id"])
        if prod["usa_keys"] and _estoque(jid, plano)["livre"] <= 0:
            await r.efemera(f'😕 **{prod["nome"]}** de {_rotulo_jogo(j)} está **esgotado** no momento. Avise a equipe ou tente mais tarde.')
            _paineis_depois(1, jogo=jid)
            return
        pid = _novo_id_pedido()
        nome = getattr(inter.user, "display_name", None) or inter.user.name
        link = prod["link_pagamento"] or _env("PIX_LINK")
        with _tx() as conn:
            conn.execute("INSERT INTO pedidos (id, usuario_id, usuario_nome, jogo, plano, produto_nome, dias, preco_centavos, "
                         "status, criado_em, link_pagamento) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                         (pid, uid, nome, jid, plano, prod["nome"], prod["dias"], prod["preco_centavos"], AG_PAGAMENTO, _agora_iso(), link))
            _auditar(conn, "pedido_criado", pid, uid, f'{jid}/{plano} {_reais_c(prod["preco_centavos"])}')
    try:
        canal = await _canal_privado_venda(f"venda-painel-{jid}", uid, nome if _slug(nome) else inter.user.name, pid, "🧾 PAGAMENTOS",
                                           f'Pedido {pid} • {_rotulo_jogo(j)} • {prod["nome"]} • {_reais_c(prod["preco_centavos"])} • cliente <@{uid}>')
    except Exception:
        with _tx() as conn:
            conn.execute("UPDATE pedidos SET status = ?, pagamento_apagado = 1 WHERE id = ?", (CANCELADO, pid))
            _auditar(conn, "erro_criar_canal", pid)
        raise
    with _tx() as conn:
        conn.execute("UPDATE pedidos SET canal_pagamento_id = ? WHERE id = ?", (canal["id"], pid))
    p = _pedido(pid)
    pix = gerar_pix(p["preco_centavos"] / 100, pid.replace("-", ""))
    payload: dict[str, Any] = {"content": f"<@{uid}>", "allowed_mentions": {"parse": [], "users": [uid]},
                               "components": _botoes_cliente(p)}
    png = _qr_png(pix) if pix else None
    if png:
        payload["embeds"] = [_embed_pedido(p, pix, com_qr=True)]
        payload["attachments"] = [{"id": 0, "filename": "pix.png"}]
        msg = await dc("POST", f'/channels/{canal["id"]}/messages', dados={"payload_json": json.dumps(payload)},
                       arquivos={"files[0]": ("pix.png", png, "image/png")})
    else:
        payload["embeds"] = [_embed_pedido(p, pix)]
        msg = await dc("POST", f'/channels/{canal["id"]}/messages', corpo=payload)
    if pix:
        await dc("POST", f'/channels/{canal["id"]}/messages', corpo={"content": pix, "allowed_mentions": {"parse": []}})
    else:
        fund = _cfg_vendas("cargo_fundador_id")
        await dc("POST", f'/channels/{canal["id"]}/messages', corpo={
            "content": (f"<@&{fund}> " if fund else "") + "⚠️ A chave Pix não está configurada no Render (PIX_CHAVE). "
                       "A equipe vai mandar os dados de pagamento aqui.", "allowed_mentions": {"parse": [], "roles": [fund] if fund else []}})
    with _tx() as conn:
        conn.execute("UPDATE pedidos SET mensagem_pedido_id = ? WHERE id = ?", (msg["id"], pid))
    await r.efemera(f'✅ Pedido `{pid}` criado! Seu canal de pagamento é <#{canal["id"]}>.')
    await registrar_venda_log(f'🛒 Pedido `{pid}` aberto por <@{uid}> — {_rotulo_jogo(j)} • {prod["nome"]} • '
                              f'{_reais_c(prod["preco_centavos"])} • <#{canal["id"]}>')
    _paineis_depois(2, jogo=jid)


async def _vendas_pagar(r: _Resposta, pid: str) -> None:
    p = _pedido(pid)
    if not p or str(r.inter.user.id) != p["usuario_id"]:
        await r.efemera("Só quem fez o pedido pode confirmar o pagamento.")
        return
    if p["status"] != AG_PAGAMENTO:
        await r.efemera("O pagamento deste pedido já foi informado. Agora é só aguardar a equipe conferir.")
        return
    await r.enviar(9, {"custom_id": f"ecvd:m_pagador:{pid}", "title": "Confirmar pagamento",
                       "components": [_linha({"type": 4, "custom_id": "nome", "style": 1, "label": "Nome completo do pagador",
                                              "placeholder": "Ex.: Maria da Silva Souza", "min_length": 5, "max_length": 100,
                                              "required": True})]})


async def _vendas_modal_pagador(r: _Resposta, pid: str) -> None:
    inter = r.inter
    nome = re.sub(r"[`*_~|<>@#\\]", "", _valor_modal(inter.data, "nome") or "")
    nome = re.sub(r"\s+", " ", nome).strip()
    if len(nome) < 5 or len(nome.split()) < 2:
        await r.efemera("Digite o **nome completo** do pagador (nome e sobrenome). Clique em CONFIRMAR PAGAMENTO de novo.")
        return
    async with _lock_pedido(pid):
        p = _pedido(pid)
        if not p or str(inter.user.id) != p["usuario_id"]:
            await r.efemera("Só quem fez o pedido pode confirmar o pagamento.")
            return
        with _tx() as conn:
            mudou = conn.execute("UPDATE pedidos SET status = ?, pagador_cifrado = ?, informado_em = ? WHERE id = ? AND status = ?",
                                 (AG_CONFERENCIA, cifrar(nome), _agora_iso(), pid, AG_PAGAMENTO)).rowcount
            if mudou:
                _auditar(conn, "pagamento_informado", pid, p["usuario_id"])
        if not mudou:
            await r.efemera("O pagamento deste pedido já foi informado.")
            return
        p = _pedido(pid)
    await r.enviar(7, {"embeds": [_embed_pedido(p)], "components": _botoes_admin(pid), "attachments": []})
    alertou = await alertar_equipe(
        f'💰 **Pagamento para conferir** • `{pid}` • {_rotulo_jogo(_jogo(p["jogo"]))} • {p["produto_nome"]} • '
        f'**{_reais_c(p["preco_centavos"])}** • <@{p["usuario_id"]}> → <#{p["canal_pagamento_id"]}>')
    fund = None if alertou else _cfg_vendas("cargo_fundador_id")
    await dc("POST", f'/channels/{p["canal_pagamento_id"]}/messages', corpo={
        "content": (f"🔔 <@&{fund}> " if fund else "🔔 ") + f'Pagamento informado no pedido `{pid}`: confira se o Pix de '
                   f'**{_reais_c(p["preco_centavos"])}** caiu na conta e aprove ou rejeite na mensagem do pedido.\n'
                   f'<@{p["usuario_id"]}>, aguarde: a equipe vai conferir o recebimento.',
        "allowed_mentions": {"parse": [], "roles": [fund] if fund else [], "users": [p["usuario_id"]]}})
    await registrar_venda_log(f'🔎 Pedido `{pid}` aguardando conferência — <@{p["usuario_id"]}> informou pagamento de '
                              f'{_reais_c(p["preco_centavos"])} (pagador: {nome}).')


async def _vendas_cancelar(r: _Resposta, pid: str, confirmado: bool) -> None:
    inter = r.inter
    p = _pedido(pid)
    if not p:
        await r.efemera("Pedido não encontrado.")
        return
    dono = str(inter.user.id) == p["usuario_id"]
    if not (dono or _eh_fundador(inter)):
        await r.efemera("Só quem fez o pedido pode cancelar.")
        return
    if p["status"] != AG_PAGAMENTO:
        await r.efemera("Este pedido não pode mais ser cancelado (o pagamento já foi informado ou o pedido foi encerrado).")
        return
    if not confirmado:
        await r.enviar(4, {"content": f'Cancelar o pedido `{pid}`? Se você já pagou, **não cancele**: clique em CONFIRMAR PAGAMENTO.',
                           "flags": 64, "components": [_linha(_botao("Sim, cancelar pedido", f"ecvd:cancelar_ok:{pid}", 4, "✖️"))]})
        return
    async with _lock_pedido(pid):
        with _tx() as conn:
            mudou = conn.execute("UPDATE pedidos SET status = ?, cancelado_por = ?, fechar_pagamento_em = ? WHERE id = ? AND status = ?",
                                 (CANCELADO, str(inter.user.id), (_agora() + APAGAR_PAGAMENTO_APOS_CANCELAR).isoformat(), pid, AG_PAGAMENTO)).rowcount
            if mudou:
                _auditar(conn, "cancelado", pid, str(inter.user.id))
    if not mudou:
        await r.enviar(7, {"content": "Este pedido já foi encerrado.", "components": []})
        return
    await r.enviar(7, {"content": "🗑️ Pedido cancelado. Este canal será apagado em instantes.", "components": []})
    p = _pedido(pid)
    await _editar_msg_pedido(p, _embed_pedido(p, extra=f"🗑️ Pedido cancelado por <@{inter.user.id}>."), [])
    await registrar_venda_log(f'🗑️ Pedido `{pid}` cancelado por <@{inter.user.id}>.')
    _paineis_depois(2, jogo=p["jogo"])


async def _vendas_pedir_aprovacao(r: _Resposta, pid: str, aprovar: bool) -> None:
    if not _eh_fundador(r.inter):
        await r.efemera("⛔ Só quem tem o cargo **FUNDADOR** pode aprovar ou rejeitar pagamentos.")
        return
    p = _pedido(pid)
    if not p:
        await r.efemera("Pedido não encontrado.")
        return
    if aprovar and p["status"] != AG_CONFERENCIA:
        await r.efemera(f'Este pedido não está aguardando conferência (status: {ROTULO_STATUS.get(p["status"], p["status"])}).')
        return
    if not aprovar and p["status"] not in (AG_CONFERENCIA, AG_PAGAMENTO):
        await r.efemera(f'Este pedido não pode mais ser rejeitado (status: {ROTULO_STATUS.get(p["status"], p["status"])}).')
        return
    if aprovar:
        await r.enviar(9, {"custom_id": f"ecvd:m_aprovar:{pid}", "title": f"Aprovar {pid}",
                           "components": [_linha({"type": 4, "custom_id": "confirmo", "style": 1,
                                                  "label": f'Pix de {_reais_c(p["preco_centavos"])} caiu? Digite CONFIRMO'[:45],
                                                  "placeholder": "CONFIRMO", "min_length": 1, "max_length": 20, "required": True})]})
    else:
        await r.enviar(9, {"custom_id": f"ecvd:m_rejeitar:{pid}", "title": f"Rejeitar {pid}",
                           "components": [_linha({"type": 4, "custom_id": "motivo", "style": 2, "label": "Motivo da rejeição",
                                                  "placeholder": "Ex.: Pix não encontrado no extrato", "min_length": 3,
                                                  "max_length": 300, "required": True})]})


async def _vendas_modal_aprovar(r: _Resposta, pid: str) -> None:
    inter = r.inter
    if not _eh_fundador(inter):
        await r.efemera("⛔ Só quem tem o cargo **FUNDADOR** pode aprovar pagamentos.")
        return
    if _norm(_valor_modal(inter.data, "confirmo") or "") != "confirmo":
        await r.efemera("Aprovação **não** feita: é preciso digitar CONFIRMO depois de conferir o Pix.")
        return
    quem = str(inter.user.id)
    async with _lock_pedido(pid):
        with _tx() as conn:
            mudou = conn.execute("UPDATE pedidos SET status = ?, aprovado_por = ?, aprovado_em = ? WHERE id = ? AND status = ?",
                                 (APROVADO, quem, _agora_iso(), pid, AG_CONFERENCIA)).rowcount
            if mudou:
                _auditar(conn, "aprovado", pid, quem, "Pix conferido (digitou CONFIRMO)")
        p = _pedido(pid)
    if not mudou:
        await r.efemera(f'Este pedido já foi decidido (status: {ROTULO_STATUS.get(p["status"], p["status"]) if p else "?"}).')
        return
    nome_quem = getattr(inter.user, "display_name", None) or inter.user.name
    await r.enviar(7, {"embeds": [_embed_pedido(p, extra=f"✅ Pagamento aprovado por <@{quem}> em {_fmt(_agora())}. Preparando a entrega…")],
                       "components": [], "attachments": []})
    await registrar_venda_log(f'✅ Pedido `{pid}` aprovado por <@{quem}> ({nome_quem}) — {_reais_c(p["preco_centavos"])}.')
    await entregar_pedido(pid)


async def _vendas_modal_rejeitar(r: _Resposta, pid: str) -> None:
    inter = r.inter
    if not _eh_fundador(inter):
        await r.efemera("⛔ Só quem tem o cargo **FUNDADOR** pode rejeitar pagamentos.")
        return
    motivo = re.sub(r"\s+", " ", (_valor_modal(inter.data, "motivo") or "")).strip()[:300] or "não informado"
    quem = str(inter.user.id)
    async with _lock_pedido(pid):
        with _tx() as conn:
            mudou = conn.execute("UPDATE pedidos SET status = ?, rejeitado_por = ?, rejeitado_em = ?, motivo_rejeicao = ?, "
                                 "fechar_pagamento_em = ? WHERE id = ? AND status IN (?, ?)",
                                 (REJEITADO, quem, _agora_iso(), motivo, (_agora() + APAGAR_PAGAMENTO_APOS_REJEICAO).isoformat(),
                                  pid, AG_CONFERENCIA, AG_PAGAMENTO)).rowcount
            if mudou:
                _auditar(conn, "rejeitado", pid, quem, motivo)
        p = _pedido(pid)
    if not mudou:
        await r.efemera("Este pedido já foi decidido.")
        return
    await r.enviar(7, {"embeds": [_embed_pedido(p, extra=f"❌ Pagamento rejeitado por <@{quem}>.\n**Motivo:** {motivo}")],
                       "components": [], "attachments": []})
    await dc("POST", f'/channels/{p["canal_pagamento_id"]}/messages', corpo={
        "content": (f'<@{p["usuario_id"]}> ❌ O pagamento do pedido `{pid}` **não foi aprovado**.\n**Motivo:** {motivo}\n'
                    "Se você pagou de verdade, abra um ticket de suporte e envie o comprovante. Este canal será apagado em 10 minutos."),
        "allowed_mentions": {"parse": [], "users": [p["usuario_id"]]}})
    await _dm(p["usuario_id"], {"title": "❌ Pagamento não aprovado", "color": CORES["vermelho"],
                                "description": f'Seu pedido `{pid}` ({p["produto_nome"]}) foi rejeitado.\n**Motivo:** {motivo}\n'
                                               "Se você pagou, abra um ticket de suporte no servidor com o comprovante."})
    await registrar_venda_log(f'❌ Pedido `{pid}` rejeitado por <@{quem}>. Motivo: {motivo}')
    _paineis_depois(2, jogo=p["jogo"])


async def _dm(uid: str, embed: dict) -> bool:
    try:
        canal = await dc("POST", "/users/@me/channels", corpo={"recipient_id": uid})
        await dc("POST", f'/channels/{canal["id"]}/messages', corpo={"embeds": [embed]})
        return True
    except ErroDiscord:
        return False


# Importados no fim: estes módulos também usam este aqui (evita import circular).
from ..busca import _canal_existe
from ..central import alertar_equipe
from ..config import _env
from ..discord_api import ErroDiscord, dc
from ..interface import _botao, _linha, _valor_modal
from ..pix import _qr_png, gerar_pix
from ..util import CORES, _agora, _fmt, _norm, _slug
from .backup import registrar_venda_log
from .banco import (
    _agora_iso,
    _auditar,
    _cfg_vendas,
    _eh_fundador,
    _estoque,
    _jogo,
    _lock_pedido,
    _novo_id_pedido,
    _produto,
    _q1,
    _reais_c,
    _rotulo_jogo,
    _tx,
)
from .base import (
    AG_CONFERENCIA,
    AG_PAGAMENTO,
    APAGAR_PAGAMENTO_APOS_CANCELAR,
    APAGAR_PAGAMENTO_APOS_REJEICAO,
    APROVADO,
    CANCELADO,
    REJEITADO,
    ROTULO_STATUS,
    STATUS_ABERTOS_VENDA,
    _cliques_menu,
    _vendas,
    _vendas_lock,
)
from .canais import _canal_privado_venda
from .cofre import cifrar
from .entrega import entregar_pedido
from .paineis import _paineis_depois
from .pedido import _botoes_admin, _botoes_cliente, _editar_msg_pedido, _embed_pedido, _pedido
