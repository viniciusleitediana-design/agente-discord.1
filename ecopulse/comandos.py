"""Comandos de barra (/) gerais e roteamento das interações."""

import re
import time
from datetime import datetime, timedelta
from typing import Any

from . import estado
from .discord_api import _Resposta

_CANAL_TEXTO = {"type": 7, "name": "canal", "description": "Canal do painel (vazio = este canal)", "required": False,
                "channel_types": [0, 5]}
COMANDOS: list[dict[str, Any]] = [
    {"name": "ping", "description": "Testar o bot", "type": 1},
    {"name": "loja_painel", "description": "Publicar ou atualizar o painel de compra de um produto da loja", "type": 1,
     "default_member_permissions": "8",
     "options": [{"type": 3, "name": "produto", "description": "Produto (vazio = o do painel deste canal)",
                  "required": False, "autocomplete": True}, _CANAL_TEXTO]},
    {"name": "vendas", "description": "Resumo das vendas", "type": 1, "default_member_permissions": "8"},
    {"name": "pedidos_pendentes", "description": "Consultar pedidos pendentes", "type": 1, "default_member_permissions": "8"},
    {"name": "aprovar_pagamento", "description": "Aprovar pedido após conferir o recebimento do Pix", "type": 1,
     "default_member_permissions": "8",
     "options": [{"type": 3, "name": "pedido", "description": "Código do pedido (vazio = o pedido deste chat)",
                  "required": False, "autocomplete": True}]},
    {"name": "ticket_painel", "description": "Publicar ou atualizar o painel de tickets de suporte", "type": 1,
     "default_member_permissions": "8", "options": [_CANAL_TEXTO]},
    {"name": "verificacao_painel", "description": "Publicar ou atualizar o painel de verificação", "type": 1,
     "default_member_permissions": "8",
     "options": [{"type": 8, "name": "cargo", "description": "Cargo que a pessoa ganha ao se verificar", "required": False},
                 _CANAL_TEXTO]},
]
_NOMES_COMANDOS = {c["name"] for c in COMANDOS}


async def registrar_comandos(app_id: str) -> None:
    if estado._comandos_registrados:
        return
    try:
        await dc("PUT", f"/applications/{app_id}/guilds/{await servidor_id()}/commands", corpo=COMANDOS)
        estado._comandos_registrados = True
        log.info("Comandos de barra registrados: %s", ", ".join("/" + c["name"] for c in COMANDOS))
    except Exception as erro:
        log.warning("Não consegui registrar os comandos de barra: %s", erro)


def _resumo_vendas(dias: int | None = None) -> dict:
    vendas = _cfg.get("vendas", [])
    agora = _agora()
    hoje = agora.astimezone(FUSO).date()

    def soma(lista):
        total = sum(v.get("valor") or 0 for v in lista)
        return {"vendas": len(lista), "total": _reais(total) if total else "R$ 0,00"}

    def desde(delta):
        return [v for v in vendas if datetime.fromisoformat(v["quando"]) >= agora - delta]

    resumo: dict[str, Any] = {
        "hoje": soma([v for v in vendas if datetime.fromisoformat(v["quando"]).astimezone(FUSO).date() == hoje]),
        "ultimos_7_dias": soma(desde(timedelta(days=7))),
        "ultimos_30_dias": soma(desde(timedelta(days=30))),
        "desde_o_inicio": soma(vendas),
    }
    janela = desde(timedelta(days=dias)) if dias else vendas
    por_produto: dict[str, list] = {}
    for v in janela:
        por_produto.setdefault(v.get("produto_nome") or v["produto"], []).append(v)
    resumo["por_produto"] = {k: soma(lista) for k, lista in sorted(por_produto.items(), key=lambda x: -len(x[1]))}
    resumo["ultimas"] = [{"quando": _fmt(v["quando"]), "produto": v.get("produto_nome") or v["produto"],
                          "valor": _reais(v.get("valor")), "comprador": f'<@{v["comprador"]}>', "codigo": v["txid"]}
                         for v in reversed(vendas[-5:])]
    return resumo


def _embed_vendas() -> dict:
    r = _resumo_vendas(30)
    linhas = [f'📅 **Hoje:** {r["hoje"]["vendas"]} venda(s) • {r["hoje"]["total"]}',
              f'🗓️ **7 dias:** {r["ultimos_7_dias"]["vendas"]} • {r["ultimos_7_dias"]["total"]}',
              f'📆 **30 dias:** {r["ultimos_30_dias"]["vendas"]} • {r["ultimos_30_dias"]["total"]}',
              f'🏁 **Desde o início:** {r["desde_o_inicio"]["vendas"]} • {r["desde_o_inicio"]["total"]}']
    if r["por_produto"]:
        linhas += ["", "**Por produto (30 dias)**"] + [f'• {k}: {v["vendas"]} • {v["total"]}' for k, v in r["por_produto"].items()]
    if r["ultimas"]:
        linhas += ["", "**Últimas vendas**"] + [f'• {u["quando"]} — {u["produto"]} • {u["valor"]} • {u["comprador"]} `{u["codigo"]}`'
                                               for u in r["ultimas"]]
    if not _cfg.get("vendas"):
        linhas += ["", "_Nenhuma venda confirmada por este bot ainda._"]
    return {"title": "📊 Resumo das vendas", "description": "\n".join(linhas)[:4096], "color": COR_PADRAO,
            "footer": {"text": "Conta as vendas confirmadas pelo ECO PULSE 2"}}


_STATUS_PEDIDO = {"aguardando": "⏳ aguardando pagamento", "analise": "🧾 pagamento informado — conferir",
                  "entregando": "📦 entregando"}


def _pendentes() -> list[tuple[str, dict]]:
    return sorted(((cid, c) for cid, c in _cfg.get("compras", {}).items() if c["status"] in _STATUS_PEDIDO),
                  key=lambda x: (x[1]["status"] != "analise", x[1]["criado"]))


def _embed_pendentes() -> dict:
    itens = _pendentes()
    if not itens:
        return {"title": "📋 Pedidos pendentes", "description": "Nenhum pedido pendente. 🎉", "color": COR_PADRAO}
    linhas = []
    for cid, c in itens[:20]:
        prod = _cfg.get("produtos", {}).get(c["produto"], {})
        linhas.append(f'**`{c["txid"]}`** • {prod.get("nome", c["produto"])} • {_reais(c.get("valor"))}\n'
                      f'{_STATUS_PEDIDO[c["status"]]} • <@{c["comprador"]}>'
                      + (f' ({c["nome_completo"]})' if c.get("nome_completo") else "")
                      + f' • <#{cid}> • {_fmt(c.get("informado") or c["criado"])}')
    if len(itens) > 20:
        linhas.append(f"… e mais {len(itens) - 20}.")
    return {"title": f"📋 Pedidos pendentes ({len(itens)})", "description": "\n\n".join(linhas)[:4096], "color": CORES["amarelo"],
            "footer": {"text": "Para aprovar: /aprovar_pagamento pedido:CÓDIGO (ou use o comando dentro do chat da compra)"}}


def _opcoes(dados: dict) -> dict[str, Any]:
    return {o["name"]: o.get("value") for o in dados.get("options", []) or []}


async def _cmd_ping(r: _Resposta) -> None:
    lat = getattr(estado._bot, "latency", None)
    ms = f"{lat * 1000:.0f} ms" if isinstance(lat, (int, float)) and lat == lat and lat < 60 else "?"
    minutos = int((time.time() - INICIO) / 60)
    await r.efemera(f"🏓 Pong! ECO PULSE 2 online há {minutos // 60}h{minutos % 60:02d}min • latência {ms} • versão {VERSAO}")


async def _cmd_ticket_painel(r: _Resposta, op: dict) -> None:
    await r.adiar()
    await exigir_config()
    canal_id = str(op.get("canal") or r.inter.channel_id)
    paineis = [p for p in _cfg["paineis"].values() if p["tipo"] == "ticket"]
    aqui = next((p for p in paineis if p["canal_id"] == canal_id), None)
    base = aqui or (paineis[-1] if paineis else None)
    if base:
        kw: dict[str, Any] = dict(
            categoria=base.get("categoria_id"), cargos_equipe=[c["id"] for c in base.get("cargos_equipe", [])],
            canal_historico=base.get("canal_historico_id"), motivos=base.get("motivos"),
            mensagem_abertura=base.get("mensagem_abertura"), avisar_equipe=base.get("avisar_equipe", True),
            botao_texto=base.get("botao_texto") or "Abrir ticket", botao_emoji=base.get("botao_emoji", "🎫"),
            botao_cor=base.get("botao_cor") or "azul", copiar_de=f'{base["canal_id"]}/{base["mensagem_id"]}')
    else:
        canais, cargos = await _canais(), await _cargos()
        cat = next((c for c in canais if c["type"] == 4 and "ticket" in _norm(c["name"])), None)
        hist = next((c for c in canais if c["type"] == 0 and "ticketsfechados" in _norm(c["name"])), None)
        kw = dict(categoria=cat["id"] if cat else None, canal_historico=hist["id"] if hist else None,
                  cargos_equipe=[c["id"] for c in cargos if not c.get("managed")
                                 and any(k in _norm(c["name"]) for k in ("suporte", "moderador", "administrador", "fundador"))])
    try:
        res = await publicar_painel_ticket(canal_id=canal_id, mensagem_id=aqui["mensagem_id"] if aqui else None, **kw)
    except ErroDiscord as erro:
        if not aqui or erro.codigo != 10008:
            raise
        _cfg["paineis"].pop(aqui["id"], None)  # a mensagem do painel foi apagada: publica um novo
        kw.pop("copiar_de", None)
        res = await publicar_painel_ticket(canal_id=canal_id, **kw)
        aqui = None
    await r.efemera(f'✅ Painel de tickets {"atualizado" if aqui else "publicado"} em <#{canal_id}>.\n'
                    f'Tickets em: {res["tickets_em"]} • Equipe: {", ".join(res["equipe"]) if isinstance(res["equipe"], list) else res["equipe"]}'
                    f' • Histórico: {res["historico_em"]}\nPara mudar textos ou imagem, peça ao Claude.')


async def _cmd_verificacao_painel(r: _Resposta, op: dict) -> None:
    await r.adiar()
    await exigir_config()
    canal_id = str(op.get("canal") or r.inter.channel_id)
    paineis = [p for p in _cfg["paineis"].values() if p["tipo"] == "verificacao"]
    aqui = next((p for p in paineis if p["canal_id"] == canal_id), None)
    base = aqui or (paineis[-1] if paineis else None)
    cargo = op.get("cargo") or (base or {}).get("cargo_id")
    if not cargo:
        membro = next((c for c in await _cargos() if "membro" in _norm(c["name"]) and not c.get("managed")), None)
        if not membro:
            await r.efemera("Escolha o cargo que a pessoa ganha na opção **cargo** do comando.")
            return
        cargo = membro["id"]
    kw: dict[str, Any] = {"cargo": str(cargo)}
    if base:
        kw.update(tirar_cargo=base.get("tirar_cargo_id"), mensagem_sucesso=base.get("mensagem_sucesso"),
                  botao_texto=base.get("botao_texto") or "Verificar", botao_emoji=base.get("botao_emoji", "✅"),
                  botao_cor=base.get("botao_cor") or "verde", copiar_de=f'{base["canal_id"]}/{base["mensagem_id"]}')
    try:
        res = await publicar_painel_verificacao(canal_id=canal_id, mensagem_id=aqui["mensagem_id"] if aqui else None, **kw)
    except ErroDiscord as erro:
        if not aqui or erro.codigo != 10008:
            raise
        _cfg["paineis"].pop(aqui["id"], None)
        kw.pop("copiar_de", None)
        res = await publicar_painel_verificacao(canal_id=canal_id, **kw)
        aqui = None
    await r.efemera(f'✅ Painel de verificação {"atualizado" if aqui else "publicado"} em <#{canal_id}>. '
                    f'Quem clicar ganha o cargo **{res["cargo"]}**.')


async def _cmd_loja_painel(r: _Resposta, op: dict) -> None:
    await r.adiar()
    await exigir_config()
    produtos = _cfg.get("produtos", {})
    if not produtos:
        await r.efemera("Nenhum produto cadastrado ainda. Peça ao Claude para cadastrar o produto (nome, preço e "
                        "canal de estoque) e depois use **/loja_painel** de novo.")
        return
    canal_id = str(op.get("canal") or r.inter.channel_id)
    pid = _slug(op.get("produto") or "", 40)
    if pid and pid not in produtos:
        pid = next((k for k, p in produtos.items() if _norm(p.get("nome")) == _norm(op.get("produto"))), "")
    if not pid:
        pid = next((k for k, p in produtos.items() if (p.get("painel") or {}).get("canal_id") == canal_id), "")
        if not pid and len(produtos) == 1:
            pid = next(iter(produtos))
    if not pid:
        await r.efemera("Escolha o produto na opção **produto**: " + ", ".join(p["nome"] for p in produtos.values()))
        return
    painel = produtos[pid].get("painel") or {}
    editar = painel.get("mensagem_id") if painel.get("canal_id") == canal_id else None
    try:
        await publicar_painel_compra(canal_id=canal_id, produto=pid, mensagem_id=editar)
    except ErroDiscord as erro:
        if not editar or erro.codigo != 10008:
            raise
        editar = None
        await publicar_painel_compra(canal_id=canal_id, produto=pid)
    await r.efemera(f'✅ Painel de **{produtos[pid]["nome"]}** {"atualizado" if editar else "publicado"} em <#{canal_id}>.')


async def _cmd_aprovar(r: _Resposta, op: dict) -> None:
    await r.adiar()
    await exigir_config()
    codigo = re.sub(r"[^A-Z0-9]", "", str(op.get("pedido") or "").upper())
    achado = None
    for cid, c in _cfg.get("compras", {}).items():
        if (codigo and c["txid"].upper() == codigo) or (not codigo and cid == str(r.inter.channel_id)):
            achado = (cid, c)
            break
    if not achado:
        await r.efemera("Não achei esse pedido. Veja os códigos em **/pedidos_pendentes**." if codigo else
                        "Use este comando dentro do chat da compra ou informe o código do pedido.")
        return
    canal, c = achado
    prod = _cfg.get("produtos", {}).get(c["produto"], {"nome": c["produto"]})
    if not _pode_aprovar(r.inter, prod):
        await r.efemera(f'Só quem tem o cargo {prod.get("cargo_aprovador_nome") or "Fundador"} pode aprovar pagamentos.')
        return
    if c["status"] not in ("aguardando", "analise"):
        await r.efemera("Esse pedido já foi decidido.")
        return
    c.setdefault("nome_completo", "não informado")
    embed = {"title": f'🧾 Pedido `{c["txid"]}`', "color": CORES["amarelo"],
             "description": f'**{prod.get("nome")}** • {_reais(c.get("valor"))}\nComprador: <@{c["comprador"]}> • chat <#{canal}>'}
    status_antes = c["status"]
    c["status"] = "entregando"
    try:
        await _aprovar(r, canal, c, prod, str(r.inter.user.id), embed)
    except Exception:
        if c.get("status") == "entregando":
            c["status"] = status_antes
        raise


async def _autocompletar(r: _Resposta, nome: str, dados: dict) -> None:
    foco = next((o for o in dados.get("options", []) if o.get("focused")), {})
    texto = _norm(foco.get("value") or "")
    escolhas: list[dict] = []
    if nome == "loja_painel":
        escolhas = [{"name": p["nome"][:100], "value": k} for k, p in _cfg.get("produtos", {}).items()
                    if not texto or texto in _norm(p["nome"]) or texto in _norm(k)]
    elif nome == "aprovar_pagamento":
        for cid, c in _pendentes():
            if c["status"] == "entregando":
                continue
            prod = _cfg.get("produtos", {}).get(c["produto"], {})
            rotulo = f'{c["txid"]} • {prod.get("nome", c["produto"])} • {c.get("nome_completo") or c.get("comprador_nome") or ""}'
            if not texto or texto in _norm(rotulo):
                escolhas.append({"name": rotulo[:100], "value": c["txid"]})
    await r.enviar(8, {"choices": escolhas[:25]})


async def ao_comando(inter: Any, tipo: int, dados: dict) -> None:
    nome = dados.get("name")
    if nome not in _NOMES_COMANDOS:
        return
    r = _Resposta(inter)
    try:
        if tipo == 4:
            if nome in _NOMES_VENDAS:
                await _autocompletar_vendas(r, nome, dados)
            else:
                await _autocompletar(r, nome, dados)
            return
        op = _opcoes(dados)
        if nome in _NOMES_VENDAS:
            await ao_comando_vendas(r, nome, op, dados)
            return
        if nome not in ("ping", "aprovar_pagamento"):  # o /aprovar_pagamento tem a própria checagem de cargo
            fundador_definido = _vendas["pronto"] and bool(_cfg_vendas("cargo_fundador_id"))
            eh_fundador = fundador_definido and _eh_fundador(inter)
            if nome in ("vendas", "pedidos_pendentes"):  # mostram valores e nomes de pagadores
                autorizado = eh_fundador if fundador_definido else _eh_admin(inter)
            else:
                autorizado = eh_fundador or _eh_admin(inter)
            if not autorizado:
                await r.efemera("⛔ Você não tem permissão para usar este comando.")
                return
        if nome == "ping":
            await _cmd_ping(r)
        elif nome == "vendas":
            await r.adiar()
            await exigir_config()
            await r.editar_original({"embeds": [_embed_vendas()], "allowed_mentions": {"parse": []}})
            r.adiada = False
        elif nome == "pedidos_pendentes":
            await r.adiar()
            await exigir_config()
            embeds = ([_embed_pendentes_vendas()] if _vendas["pronto"] else []) + [_embed_pendentes()]
            await r.editar_original({"embeds": embeds, "allowed_mentions": {"parse": []}})
            r.adiada = False
        elif nome == "aprovar_pagamento":
            await _cmd_aprovar(r, op)
        elif nome == "ticket_painel":
            await _cmd_ticket_painel(r, op)
        elif nome == "verificacao_painel":
            await _cmd_verificacao_painel(r, op)
        elif nome == "loja_painel":
            await _cmd_loja_painel(r, op)
    except Exception as erro:
        log.exception("Falha no comando /%s", nome)
        if tipo == 4:
            return
        texto = str(erro) if isinstance(erro, ErroDiscord) else "Deu um erro aqui. Tente de novo ou chame o Claude."
        try:
            await r.efemera(f"⚠️ {texto}")
        except Exception:
            pass


# Importados no fim: estes módulos também usam este aqui (evita import circular).
from .busca import _canais, _cargos
from .config import COR_PADRAO, FUSO, INICIO, VERSAO, log
from .discord_api import ErroDiscord, dc
from .ferramentas.loja import publicar_painel_compra
from .ferramentas.tickets import publicar_painel_ticket
from .ferramentas.verificacao import publicar_painel_verificacao
from .loja import _aprovar, _pode_aprovar
from .memoria import _cfg, exigir_config
from .paineis import _eh_admin
from .util import CORES, _agora, _fmt, _norm, _reais, _slug, servidor_id
from .vendas.banco import _cfg_vendas, _eh_fundador
from .vendas.base import _vendas
from .vendas.comandos import _NOMES_VENDAS, _autocompletar_vendas, _embed_pendentes_vendas, ao_comando_vendas
