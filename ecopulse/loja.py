"""Loja simples (ChatGPT Astra): compra em chat privado com Pix e entrega do produto."""

import asyncio
import json
import re
import secrets
from datetime import datetime, timedelta
from typing import Any

from .discord_api import _Resposta
from .util import PERMISSOES

#
# Fluxo: botão "Comprar agora" no painel → o bot cria um chat privado (comprador + cargo aprovador)
# com o QR Code e o "copia e cola" do Pix → o comprador clica em "Confirmar pagamento" e digita o
# nome completo → o aprovador (Fundador) confirma ou recusa → confirmado: o produto vai por DM
# automaticamente; recusado: o chat é fechado. Tudo fica salvo na memória (#agente-config), então
# os botões continuam funcionando depois que o Render reinicia.

ESPERA_PAGAMENTO = timedelta(hours=24)        # chat sem pagamento informado fecha sozinho
FECHAR_APOS_ENTREGA = timedelta(minutes=5)
FECHAR_APOS_RECUSA = timedelta(minutes=1)
FECHAR_APOS_CANCELAR = timedelta(seconds=10)
GERENCIAR_MSG, EMBED_LINKS = PERMISSOES["gerenciar_mensagens"], PERMISSOES["inserir_links"]
STATUS_ABERTOS = ("aguardando", "analise", "entregando")
_loja_lock = asyncio.Lock()
_estoque_lock = asyncio.Lock()


def _botoes_decisao() -> dict:
    return _linha(_botao("Confirmar", "ecop:aprovar", 3, "✅"), _botao("Recusar", "ecop:recusar", 4, "❌"))


def _ids_cargos(membro: Any) -> set[str]:
    ids: set[str] = set()
    for r in getattr(membro, "roles", None) or []:
        ids.add(str(getattr(r, "id", r)))
    for r in getattr(membro, "_roles", None) or []:
        ids.add(str(r))
    return ids


def _pode_aprovar(inter: Any, prod: dict) -> bool:
    guild = getattr(inter, "guild", None)
    if guild is not None and getattr(guild, "owner_id", None) == inter.user.id:
        return True
    aprov = prod.get("cargo_aprovador_id")
    return bool(aprov) and aprov in _ids_cargos(inter.user)


async def _registrar_venda(prod: dict, texto: str) -> None:
    canal = prod.get("canal_vendas_id")
    if canal:
        try:
            await dc("POST", f"/channels/{canal}/messages", corpo={"content": texto[:2000], "allowed_mentions": {"parse": []}})
        except ErroDiscord as erro:
            log.warning("Falha ao registrar venda: %s", erro)
    if (_cfg.get("logs") or {}).get("canal_id") != canal:
        await registrar(texto)


async def _criar_canal_compra(prod: dict, uid: str, nome_exibicao: str, usuario: str) -> dict:
    gid, bot = await servidor_id(), await eu()
    base = prod.get("prefixo_canal") or f'compra-{prod["id"]}'
    sufixo = _slug(nome_exibicao, 30) or _slug(usuario, 30) or uid[-6:]
    nome = f"{base}-{sufixo}"[:100]
    perms: list[dict[str, Any]] = [
        {"id": gid, "type": 0, "allow": "0", "deny": str(VER)},
        {"id": uid, "type": 1, "allow": str(VER | ENVIAR | HISTORICO | ANEXAR), "deny": "0"},
        {"id": bot["id"], "type": 1, "allow": str(VER | ENVIAR | HISTORICO | ANEXAR | EMBED_LINKS | GERENCIAR_MSG), "deny": "0"},
    ]
    if prod.get("cargo_aprovador_id"):
        perms.append({"id": prod["cargo_aprovador_id"], "type": 0,
                      "allow": str(VER | ENVIAR | HISTORICO | ANEXAR | GERENCIAR_MSG), "deny": "0"})
    corpo: dict[str, Any] = {"name": nome, "type": 0, "permission_overwrites": perms,
                             "topic": f'Compra de {prod["nome"]} • comprador <@{uid}> • chat privado: só você e a equipe veem'}
    if prod.get("categoria_id"):
        corpo["parent_id"] = prod["categoria_id"]
    motivo = f'Compra de {prod["nome"]}'
    try:
        return await dc("POST", f"/guilds/{gid}/channels", corpo=corpo, motivo=motivo)
    except ErroDiscord as erro:
        if erro.codigo != 50035:
            raise
    # nome recusado (ex.: caractere não aceito) ou categoria cheia: tenta de novo mais simples
    corpo["name"] = re.sub(r"[^a-z0-9_-]+", "-", nome.lower()).strip("-")[:100] or f"compra-{uid[-6:]}"
    try:
        return await dc("POST", f"/guilds/{gid}/channels", corpo=corpo, motivo=motivo)
    except ErroDiscord as erro:
        if erro.codigo != 50035 or "parent_id" not in corpo:
            raise
    corpo.pop("parent_id", None)
    return await dc("POST", f"/guilds/{gid}/channels", corpo=corpo, motivo=motivo)


async def _mandar_pagamento(canal_id: str, prod: dict, compra: dict) -> None:
    uid = compra["comprador"]
    pix = gerar_pix(prod.get("preco"), compra["txid"])
    link = prod.get("link_pagamento")
    qr_url = prod.get("qr_imagem_url")
    passos = []
    if pix:
        passos.append("Escaneie o **QR Code** abaixo no app do seu banco **ou** copie o código Pix da próxima mensagem.")
    elif qr_url:
        passos.append("Escaneie o **QR Code** abaixo no app do seu banco.")
    if link:
        passos.append("Se preferir, pague pelo botão **💳 Pagar pelo link**." if passos else
                      "Pague pelo botão **💳 Pagar pelo link** lá embaixo.")
    sem_pagamento = not (pix or qr_url or link)
    if sem_pagamento:
        passos.append("Aguarde: a equipe vai mandar os dados de pagamento aqui neste chat.")
    passos.append("Depois de pagar, clique em **✅ Confirmar pagamento** e digite seu **nome completo**.")
    passos.append(f"A equipe confere o pagamento e o produto chega {_onde_entrega(prod)} automaticamente.")
    lista = "\n".join(f"**{i}.** {p}" for i, p in enumerate(passos, 1))
    embed: dict[str, Any] = {
        "title": f'🛒 Compra • {prod["nome"]}',
        "description": (f"Olá, <@{uid}>! Este chat é **privado**: só você e a equipe conseguem ver.\n\n"
                        f'💰 **Valor:** {_reais(prod.get("preco"))}\n🧾 **Código da compra:** `{compra["txid"]}`\n\n'
                        f"**Como pagar**\n{lista}\n\n"
                        "⚠️ Pague **somente** pelos dados deste chat. Se o pagamento não for informado em 24 horas, "
                        "este chat fecha sozinho."),
        "color": prod.get("cor") or CORES["roxo"],
        "footer": {"text": "ECO PULSE • Compra segura"},
    }
    mencoes: dict[str, Any] = {"parse": [], "users": [uid]}
    conteudo = f"<@{uid}>"
    aprov = prod.get("cargo_aprovador_id")
    if sem_pagamento and aprov:
        conteudo += f" <@&{aprov}>"
        mencoes["roles"] = [aprov]
    payload: dict[str, Any] = {"content": conteudo, "embeds": [embed], "allowed_mentions": mencoes}
    png = _qr_png(pix) if pix else None
    if png:
        embed["image"] = {"url": "attachment://pix.png"}
        payload["attachments"] = [{"id": 0, "filename": "pix.png"}]
        await dc("POST", f"/channels/{canal_id}/messages", dados={"payload_json": json.dumps(payload)},
                 arquivos={"files[0]": ("pix.png", png, "image/png")})
    else:
        if pix:
            embed["image"] = {"url": _qr_url_online(pix)}
        elif qr_url:
            embed["image"] = {"url": qr_url}
        await dc("POST", f"/channels/{canal_id}/messages", corpo=payload)
    botoes = [_botao("Confirmar pagamento", "ecop:pago", 3, "✅")]
    if link:
        botoes.append({"type": 2, "style": 5, "label": "Pagar pelo link", "url": link, "emoji": {"name": "💳"}})
    botoes.append(_botao("Cancelar compra", "ecop:cancelar", 4, "❌"))
    msg = await dc("POST", f"/channels/{canal_id}/messages", corpo={
        "content": pix or "Quando terminar de pagar, clique no botão abaixo 👇",
        "components": [_linha(*botoes)], "allowed_mentions": {"parse": []}})
    compra["msg_botoes"] = msg["id"]


async def _clicou_comprar(r: _Resposta, produto: str) -> None:
    inter = r.inter
    await r.adiar()
    await exigir_config()
    prod = _cfg["produtos"].get(produto)
    if not prod or not prod.get("ativo", True):
        await r.efemera("Este produto não está disponível no momento.")
        return
    uid = str(inter.user.id)
    async with _loja_lock:
        for canal_id, c in list(_cfg["compras"].items()):
            if c["comprador"] == uid and c["produto"] == produto and c["status"] in STATUS_ABERTOS:
                if await _canal_existe(canal_id):
                    await r.efemera(f"Você já tem uma compra aberta deste produto: <#{canal_id}>")
                    return
                _cfg["compras"].pop(canal_id, None)
        nome = getattr(inter.user, "display_name", None) or inter.user.name
        canal = await _criar_canal_compra(prod, uid, nome, inter.user.name)
        agora = _agora()
        compra: dict[str, Any] = {
            "produto": produto, "comprador": uid, "comprador_nome": nome, "status": "aguardando",
            "valor": prod.get("preco"), "txid": "ECOP" + secrets.token_hex(4).upper(),
            "criado": agora.isoformat(), "fechar_em": (agora + ESPERA_PAGAMENTO).isoformat(),
        }
        _cfg["compras"][canal["id"]] = compra
    try:
        await _mandar_pagamento(canal["id"], prod, compra)
    finally:
        await salvar_config()
    await r.efemera(f'✅ Seu chat de compra foi criado: <#{canal["id"]}>\nO pagamento por Pix já está lá.')
    await registrar(f'🛒 <@{uid}> abriu uma compra de **{prod["nome"]}** em <#{canal["id"]}>.')


async def _clicou_pago(r: _Resposta) -> None:
    inter = r.inter
    if not _cfg_estado["carregada"]:
        asyncio.create_task(garantir_config())
        await r.efemera("O bot acabou de reiniciar. Tente de novo em alguns segundos.")
        return
    c = _cfg["compras"].get(str(inter.channel_id))
    if not c:
        await r.efemera("Esta compra já foi encerrada.")
        return
    if str(inter.user.id) != c["comprador"]:
        await r.efemera("Só quem está comprando pode confirmar o pagamento.")
        return
    if c["status"] != "aguardando":
        await r.efemera("Você já informou o pagamento. Agora é só aguardar a equipe conferir.")
        return
    await r.enviar(9, {
        "custom_id": "ecop:modal_pago", "title": "Confirmar pagamento",
        "components": [_linha({"type": 4, "custom_id": "nome", "style": 1, "label": "Seu nome completo",
                               "placeholder": "Ex.: Maria da Silva Souza", "min_length": 5, "max_length": 100,
                               "required": True})],
    })


async def _modal_pago(r: _Resposta) -> None:
    inter = r.inter
    canal = str(inter.channel_id)
    c = _cfg["compras"].get(canal)
    if not c or str(inter.user.id) != c["comprador"]:
        await r.efemera("Esta compra já foi encerrada.")
        return
    if c["status"] != "aguardando":
        await r.efemera("Você já informou o pagamento. Agora é só aguardar a equipe conferir.")
        return
    nome = re.sub(r"[`*_~|<>@#\\]", "", _valor_modal(inter.data, "nome") or "")
    nome = re.sub(r"\s+", " ", nome).strip()
    if len(nome) < 5 or len(nome.split()) < 2:
        await r.efemera("Digite seu **nome completo** (nome e sobrenome). Clique em ✅ Confirmar pagamento de novo.")
        return
    prod = _cfg["produtos"].get(c["produto"], {})
    c.update(status="analise", nome_completo=nome, informado=_agora().isoformat(), fechar_em=None)
    aprov = prod.get("cargo_aprovador_id")
    embed = {
        "title": "🧾 Pagamento informado",
        "description": (f'<@{c["comprador"]}> disse que já pagou **{prod.get("nome", c["produto"])}**.\n\n'
                        f"👤 **Nome completo:** {nome}\n💰 **Valor:** {_reais(c.get('valor'))}\n"
                        f'🧾 **Código da compra:** `{c["txid"]}`\n\n'
                        "Confira no extrato do banco e escolha abaixo.\n"
                        f'<@{c["comprador"]}>, agora é só aguardar a equipe conferir. 🙏'),
        "color": CORES["amarelo"],
        "footer": {"text": f'Só o cargo {prod.get("cargo_aprovador_nome") or "Fundador"} pode confirmar ou recusar'},
    }
    central = await tem_canal_alertas()
    dados: dict[str, Any] = {"embeds": [embed], "components": [_botoes_decisao()],
                             "allowed_mentions": {"parse": [], "roles": [aprov] if aprov and not central else []}}
    if aprov and not central:
        dados["content"] = f"<@&{aprov}>"
    await r.enviar(4, dados)
    if central and not await alertar_equipe(
            f'💰 **Pagamento para conferir** • {prod.get("nome", c["produto"])} • **{_reais(c.get("valor"))}** • '
            f'<@{c["comprador"]}> → <#{canal}>', [aprov] if aprov else None) and aprov:
        await dc("POST", f"/channels/{canal}/messages", corpo={
            "content": f"<@&{aprov}> pagamento informado acima.", "allowed_mentions": {"parse": [], "roles": [aprov]}})
    await salvar_config()


async def _pegar_item(prod: dict) -> tuple[str | None, tuple[str, str] | None]:
    """Pega o próximo produto do estoque (mensagem mais antiga do canal; fixadas são ignoradas)."""
    canal = prod.get("canal_estoque_id")
    if canal:
        msgs = await dc("GET", f"/channels/{canal}/messages", params={"limit": 100})
        validas = [m for m in msgs if not m.get("pinned") and (m.get("content") or m.get("attachments"))]
        if validas and prod.get("conteudo_fixo"):
            m = validas[0]  # conteúdo fixo: a mensagem mais recente, igual para todos e nunca apagada
            partes = [m.get("content") or ""] + [a["url"] for a in m.get("attachments", [])]
            return "\n".join(p for p in partes if p).strip(), None
        if validas:
            m = validas[-1]  # a API devolve da mais nova para a mais antiga
            partes = [m.get("content") or ""] + [a["url"] for a in m.get("attachments", [])]
            return "\n".join(p for p in partes if p).strip(), (canal, m["id"])
    if prod.get("entrega_texto"):
        return prod["entrega_texto"], None
    return None, None


async def _contar_estoque(prod: dict) -> str:
    try:
        msgs = await dc("GET", f'/channels/{prod["canal_estoque_id"]}/messages', params={"limit": 100})
    except ErroDiscord as erro:
        return f"erro: {erro}"
    n = len([m for m in msgs if not m.get("pinned") and (m.get("content") or m.get("attachments"))])
    if prod.get("conteudo_fixo"):
        return "conteúdo fixo pronto (ilimitado)" if n else "VAZIO: mande o conteúdo no canal"
    return "100 ou mais" if n >= 100 else str(n)


async def _entregar_dm(c: dict, prod: dict, item: str) -> bool:
    try:
        dm = await dc("POST", "/users/@me/channels", corpo={"recipient_id": c["comprador"]})
        await dc("POST", f'/channels/{dm["id"]}/messages', corpo={"embeds": [{
            "title": "✅ Compra confirmada!",
            "description": (f'Seu pagamento de **{prod["nome"]}** foi confirmado. Seu produto está logo abaixo 👇\n\n'
                            f'Guarde esta mensagem. Código da compra: `{c["txid"]}`'),
            "color": CORES["verde"], "footer": {"text": "ECO PULSE • Obrigado pela compra!"}}]})
        for parte in _partes(item):
            await dc("POST", f'/channels/{dm["id"]}/messages', corpo={"content": parte, "allowed_mentions": {"parse": []}})
        return True
    except ErroDiscord as erro:
        log.warning("Não consegui entregar por DM para %s: %s", c["comprador"], erro)
        return False


DIAS_ENTREGA_PADRAO = 7
_MODOS_ENTREGA = {"canal": "canal", "canalprivado": "canal", "privado": "canal", "dm": "dm", "mensagemdireta": "dm",
                  "canaledm": "canal_e_dm", "canalmaisdm": "canal_e_dm", "ambos": "canal_e_dm", "osdois": "canal_e_dm"}


def _modo_entrega(prod: dict) -> str:
    return prod.get("entrega_modo") or "canal"


def _onde_entrega(prod: dict) -> str:
    return {"canal": "num **canal privado** só seu", "dm": "na sua **DM**",
            "canal_e_dm": "num **canal privado** só seu e na sua **DM**"}[_modo_entrega(prod)]


async def _criar_canal_entrega(c: dict, prod: dict) -> dict:
    gid, bot = await servidor_id(), await eu()
    uid = c["comprador"]
    perms: list[dict[str, Any]] = [
        {"id": gid, "type": 0, "allow": "0", "deny": str(VER)},
        {"id": uid, "type": 1, "allow": str(VER | HISTORICO | ENVIAR | ANEXAR), "deny": "0"},
        {"id": bot["id"], "type": 1, "allow": str(VER | ENVIAR | HISTORICO | ANEXAR | EMBED_LINKS | GERENCIAR_MSG), "deny": "0"},
    ]
    if prod.get("cargo_aprovador_id"):
        perms.append({"id": prod["cargo_aprovador_id"], "type": 0, "allow": str(VER | ENVIAR | HISTORICO | GERENCIAR_MSG), "deny": "0"})
    nome = f'{prod.get("prefixo_entrega") or "📦・entrega"}-{_slug(c.get("comprador_nome"), 30) or uid[-6:]}'
    dias = int(prod.get("dias_entrega") or DIAS_ENTREGA_PADRAO)
    return await _criar_canal_privado(
        nome, perms, prod.get("categoria_entrega_id") or prod.get("categoria_id"),
        f'Entrega de {prod["nome"]} para <@{uid}> • código {c["txid"]} • disponível por {dias} dias',
        f'Entrega de {prod["nome"]}')


async def _entregar(c: dict, prod: dict, item: str) -> dict:
    """Entrega o produto conforme o modo do produto: canal privado só do comprador (padrão), DM ou os dois.
    Se o canal não puder ser criado, cai para a DM."""
    modo = _modo_entrega(prod)
    uid = c["comprador"]
    res: dict[str, Any] = {"canal": None, "dm": False}
    if modo in ("canal", "canal_e_dm"):
        ch = None
        try:
            ch = await _criar_canal_entrega(c, prod)
            dias = int(prod.get("dias_entrega") or DIAS_ENTREGA_PADRAO)
            fim = _agora() + timedelta(days=dias)
            await dc("POST", f'/channels/{ch["id"]}/messages', corpo={
                "content": f"<@{uid}>", "allowed_mentions": {"parse": [], "users": [uid]},
                "embeds": [{"title": f'✅ Compra confirmada • {prod["nome"]}', "color": CORES["verde"],
                            "description": (f"Seu pagamento foi confirmado! Seu produto está **logo abaixo** 👇\n\n"
                                            f'🧾 **Código da compra:** `{c["txid"]}`\n'
                                            f"⚠️ **Copie e guarde o conteúdo:** este canal é apagado <t:{int(fim.timestamp())}:R> "
                                            f"(<t:{int(fim.timestamp())}:f>)."),
                            "footer": {"text": "ECO PULSE • Obrigado pela compra! Este canal é só seu."}}]})
            for parte in _partes(item):
                await dc("POST", f'/channels/{ch["id"]}/messages', corpo={"content": parte, "allowed_mentions": {"parse": []}})
            await dc("POST", f'/channels/{ch["id"]}/messages', corpo={
                "content": "Já copiou e guardou tudo? Pode fechar este canal quando quiser.",
                "components": [_linha(_botao("Já salvei, fechar canal", "ecop:fechar_entrega", 2, "🔒"))]})
            _cfg.setdefault("entregas", {})[ch["id"]] = {
                "comprador": uid, "produto": c["produto"], "txid": c["txid"],
                "criado": _agora().isoformat(), "fechar_em": fim.isoformat()}
            res["canal"] = ch["id"]
        except ErroDiscord as erro:
            log.warning("Não consegui entregar no canal privado (%s); tentando a DM.", erro)
            if ch:
                try:
                    await dc("DELETE", f'/channels/{ch["id"]}', motivo="Entrega falhou")
                except ErroDiscord:
                    pass
    if modo in ("dm", "canal_e_dm") or not res["canal"]:
        res["dm"] = await _entregar_dm(c, prod, item)
    else:
        try:  # só um aviso na DM, sem o conteúdo
            dm = await dc("POST", "/users/@me/channels", corpo={"recipient_id": uid})
            await dc("POST", f'/channels/{dm["id"]}/messages', corpo={"embeds": [{
                "title": "✅ Compra confirmada!", "color": CORES["verde"],
                "description": f'Seu pagamento de **{prod["nome"]}** foi confirmado. Seu produto está no canal privado <#{res["canal"]}>.'}]})
        except ErroDiscord:
            pass
    return res


async def _clicou_fechar_entrega(r: _Resposta, confirmado: bool) -> None:
    inter = r.inter
    if not _cfg_estado["carregada"]:
        asyncio.create_task(garantir_config())
        await r.efemera("O bot acabou de reiniciar. Tente de novo em alguns segundos.")
        return
    canal = str(inter.channel_id)
    e = _cfg.get("entregas", {}).get(canal)
    if not e:
        await r.efemera("Este canal já está sendo fechado.")
        return
    prod = _cfg.get("produtos", {}).get(e["produto"], {})
    if str(inter.user.id) != e["comprador"] and not _pode_aprovar(inter, prod):
        await r.efemera("Só quem comprou pode fechar este canal.")
        return
    if not confirmado:
        await r.enviar(4, {"content": "Tem certeza? Depois de fechar, o conteúdo some. Confira se você copiou e guardou tudo.",
                           "flags": 64, "components": [_linha(_botao("Sim, fechar", "ecop:fechar_entrega_ok", 4, "🔒"))]})
        return
    e["fechar_em"] = (_agora() + timedelta(seconds=3)).isoformat()
    await r.enviar(7, {"content": "🔒 Fechando o canal…", "components": []})
    await salvar_config()


async def fechar_entregas() -> None:
    """Apaga canais de entrega vencidos (avisa o comprador 1 dia antes)."""
    if not _cfg_estado["carregada"] or not _cfg.get("entregas"):
        return
    agora = _agora()
    mudou = False
    for canal_id, e in list(_cfg["entregas"].items()):
        fim = datetime.fromisoformat(e["fechar_em"])
        if fim <= agora:
            try:
                await dc("DELETE", f"/channels/{canal_id}", motivo="Entrega encerrada")
            except ErroDiscord as erro:
                if erro.status != 404 and erro.codigo != 10003:
                    log.warning("Não consegui apagar o canal de entrega %s: %s", canal_id, erro)
                    continue
            _cfg["entregas"].pop(canal_id, None)
            mudou = True
        elif not e.get("avisado") and fim - agora <= timedelta(hours=24) and fim - datetime.fromisoformat(e["criado"]) > timedelta(hours=25):
            e["avisado"] = True
            mudou = True
            try:
                await dc("POST", f"/channels/{canal_id}/messages", corpo={
                    "content": f'⏰ <@{e["comprador"]}>, este canal será apagado <t:{int(fim.timestamp())}:R>. Copie e guarde o seu produto!',
                    "allowed_mentions": {"parse": [], "users": [e["comprador"]]}})
            except ErroDiscord as erro:
                if erro.status == 404 or erro.codigo == 10003:
                    _cfg["entregas"].pop(canal_id, None)
    if mudou:
        await salvar_config()


async def _aprovar(r: _Resposta, canal: str, c: dict, prod: dict, quem: str, embed: dict) -> None:
    nome_quem = getattr(r.inter.user, "display_name", None) or r.inter.user.name
    async with _estoque_lock:
        item, origem = await _pegar_item(prod)
        if item is None:
            c["status"] = "analise"
            await r.editar_original({"embeds": [_com_rodape(embed, "⚠️ Sem produto para entregar: abasteça e clique em Confirmar de novo")],
                                     "components": [_botoes_decisao()]})
            onde = (f'Mande o conteúdo em <#{prod["canal_estoque_id"]}> (o mesmo para todos)' if prod.get("conteudo_fixo") and prod.get("canal_estoque_id")
                    else f'Mande o produto em <#{prod["canal_estoque_id"]}> (1 mensagem = 1 entrega)'
                    if prod.get("canal_estoque_id") else "Configure a entrega do produto")
            await dc("POST", f"/channels/{canal}/messages", corpo={
                "content": (f"⚠️ <@{quem}>, acabou o estoque de **{prod['nome']}**. {onde} e clique em **✅ Confirmar** de novo.\n"
                            f'<@{c["comprador"]}>, seu pagamento já foi visto. Só aguarde um pouquinho.'),
                "allowed_mentions": {"parse": [], "users": list(dict.fromkeys([quem, c["comprador"]]))}})
            return
        entrega = await _entregar(c, prod, item)
        na_dm = entrega["dm"]
        if not entrega["canal"] and not na_dm:
            await dc("POST", f"/channels/{canal}/messages", corpo={"embeds": [{
                "title": "📦 Seu produto", "color": CORES["verde"],
                "description": "Não consegui te mandar DM (ela está fechada), então o produto vai aqui embaixo. "
                               "Copie e guarde antes de fechar o chat."}]})
            for parte in _partes(item):
                await dc("POST", f"/channels/{canal}/messages", corpo={"content": parte, "allowed_mentions": {"parse": []}})
        if origem:
            try:
                await dc("DELETE", f"/channels/{origem[0]}/messages/{origem[1]}", motivo="Produto entregue")
            except ErroDiscord as erro:
                log.warning("Não consegui tirar o item entregue do estoque: %s", erro)
    agora = _agora()
    c.update(status="entregue", aprovado_por=quem, entregue=agora.isoformat())
    _cfg.setdefault("vendas", []).append({
        "txid": c["txid"], "produto": c["produto"], "produto_nome": prod.get("nome"), "valor": c.get("valor"),
        "comprador": c["comprador"], "comprador_nome": c.get("comprador_nome"), "nome_completo": c.get("nome_completo"),
        "aprovado_por": quem, "quando": agora.isoformat()})
    del _cfg["vendas"][:-3000]
    if prod.get("cargo_cliente_id"):
        try:
            await dc("PUT", f'/guilds/{await servidor_id()}/members/{c["comprador"]}/roles/{prod["cargo_cliente_id"]}',
                     motivo=f'Comprou {prod["nome"]}')
        except ErroDiscord as erro:
            log.warning("Não consegui dar o cargo de cliente: %s", erro)
    if entrega["canal"]:
        c["fechar_em"] = (agora + FECHAR_APOS_ENTREGA).isoformat()
        c["canal_entrega"] = entrega["canal"]
        texto = (f'<@{c["comprador"]}> ✅ Pagamento confirmado! Seu produto está no canal privado <#{entrega["canal"]}>'
                 + (" e na sua **DM**" if na_dm else "") + ". Este chat fecha sozinho em 5 minutos.")
        componentes: list[dict] = []
        onde_curto, onde = "num canal privado", f'no canal <#{entrega["canal"]}>'
    elif na_dm:
        c["fechar_em"] = (agora + FECHAR_APOS_ENTREGA).isoformat()
        texto = (f'<@{c["comprador"]}> ✅ Pagamento confirmado! Seu produto foi enviado na sua **DM**. '
                 "Este chat fecha sozinho em 5 minutos.")
        componentes = []
        onde_curto = onde = "na DM"
    else:
        onde_curto = onde = "no chat"
        c["fechar_em"] = (agora + ESPERA_PAGAMENTO).isoformat()
        texto = (f'<@{c["comprador"]}> ✅ Pagamento confirmado! O produto está **logo acima**. '
                 "Depois de copiar, clique em **Fechar chat**.")
        componentes = [_linha(_botao("Fechar chat", "ecop:fechar", 2, "🔒"))]
    await dc("POST", f"/channels/{canal}/messages", corpo={"content": texto, "components": componentes,
                                                           "allowed_mentions": {"parse": [], "users": [c["comprador"]]}})
    await r.editar_original({"embeds": [_com_rodape(embed, f"✅ Confirmado por {nome_quem} • entregue {onde_curto}",
                                                    CORES["verde"])], "components": []})
    await _registrar_venda(prod, (f'🧾 **Venda confirmada** — {prod["nome"]} • {_reais(c.get("valor"))}\n'
                                  f'Comprador: <@{c["comprador"]}> ({c.get("nome_completo")}) • Código `{c["txid"]}` • '
                                  f"Confirmado por <@{quem}> • entregue {onde} • {_fmt(agora)}"))
    await salvar_config()


async def _decidir(r: _Resposta, aprovar: bool) -> None:
    inter = r.inter
    canal = str(inter.channel_id)
    c = _cfg["compras"].get(canal)
    if not c:
        await r.efemera("Esta compra já foi encerrada.")
        return
    prod = _cfg["produtos"].get(c["produto"], {"nome": c["produto"]})
    if not _pode_aprovar(inter, prod):
        await r.efemera(f'Só quem tem o cargo {prod.get("cargo_aprovador_nome") or "Fundador"} pode confirmar ou recusar.')
        return
    if c["status"] != "analise":
        await r.efemera("Essa compra já foi decidida.")
        return
    quem = str(inter.user.id)
    nome_quem = getattr(inter.user, "display_name", None) or inter.user.name
    embed = _embed_da_mensagem(inter)
    if aprovar:
        c["status"] = "entregando"   # trava na hora: dois cliques ao mesmo tempo não entregam duas vezes
        await r.enviar(7, {"embeds": [_com_rodape(embed, f"⏳ Confirmando… ({nome_quem})")], "components": []})
        try:
            await _aprovar(r, canal, c, prod, quem, embed)
        except Exception:
            if c.get("status") == "entregando":
                c["status"] = "analise"
                try:
                    await r.editar_original({"embeds": [_com_rodape(embed, "⚠️ Deu erro na entrega. Tente Confirmar de novo.")],
                                             "components": [_botoes_decisao()]})
                except Exception:
                    pass
            raise
        return
    agora = _agora()
    c.update(status="recusado", recusado_por=quem, fechar_em=(agora + FECHAR_APOS_RECUSA).isoformat())
    await r.enviar(7, {"embeds": [_com_rodape(embed, f"❌ Recusado por {nome_quem}", CORES["vermelho"])], "components": []})
    await dc("POST", f"/channels/{canal}/messages", corpo={
        "content": (f'<@{c["comprador"]}> ❌ A equipe **não confirmou** o seu pagamento. Este chat fecha em 1 minuto.\n'
                    "Se você pagou de verdade, fale com a equipe e mande o comprovante."),
        "allowed_mentions": {"parse": [], "users": [c["comprador"]]}})
    try:
        dm = await dc("POST", "/users/@me/channels", corpo={"recipient_id": c["comprador"]})
        await dc("POST", f'/channels/{dm["id"]}/messages', corpo={"embeds": [{
            "title": "❌ Pagamento não confirmado", "color": CORES["vermelho"],
            "description": (f'Seu pagamento de **{prod["nome"]}** não foi confirmado e o chat de compra foi fechado.\n'
                            f'Se você pagou de verdade, fale com a equipe do servidor e mande o comprovante. '
                            f'Código da compra: `{c["txid"]}`')}]})
    except ErroDiscord:
        pass
    await _registrar_venda(prod, (f'❌ **Pagamento recusado** — {prod["nome"]} • {_reais(c.get("valor"))}\n'
                                  f'Comprador: <@{c["comprador"]}> ({c.get("nome_completo")}) • Código `{c["txid"]}` • '
                                  f"Recusado por <@{quem}> • {_fmt(agora)}"))
    await salvar_config()


async def _clicou_fechar(r: _Resposta, acao: str) -> None:
    inter = r.inter
    if not _cfg_estado["carregada"]:
        asyncio.create_task(garantir_config())
        await r.efemera("O bot acabou de reiniciar. Tente de novo em alguns segundos.")
        return
    canal = str(inter.channel_id)
    c = _cfg["compras"].get(canal)
    if not c:
        await r.efemera("Esta compra já foi encerrada.")
        return
    prod = _cfg["produtos"].get(c["produto"], {"nome": c["produto"]})
    eh_comprador = str(inter.user.id) == c["comprador"]
    eh_equipe = _pode_aprovar(inter, prod)
    if not (eh_comprador or eh_equipe):
        await r.efemera("Você não pode fechar este chat.")
        return
    agora = _agora()
    if acao == "cancelar":
        if c["status"] not in ("aguardando", "analise"):
            await r.efemera("Essa compra não pode mais ser cancelada.")
            return
        if c["status"] == "analise" and not eh_equipe:
            await r.efemera("Você já informou o pagamento. Agora só a equipe pode encerrar esta compra.")
            return
        c.update(status="cancelado", fechar_em=(agora + FECHAR_APOS_CANCELAR).isoformat())
        await r.enviar(4, {"content": f"🗑️ Compra cancelada por <@{inter.user.id}>. Este chat fecha em alguns segundos.",
                           "allowed_mentions": {"parse": []}})
        await registrar(f'🗑️ Compra de **{prod["nome"]}** de <@{c["comprador"]}> cancelada por <@{inter.user.id}>.')
    else:
        c["fechar_em"] = (agora + timedelta(seconds=3)).isoformat()
        await r.enviar(4, {"content": "🔒 Fechando o chat em alguns segundos…", "allowed_mentions": {"parse": []}})
    await salvar_config()


async def fechar_compras() -> None:
    """Apaga os chats de compra encerrados (e os abandonados sem pagamento informado)."""
    if not _cfg_estado["carregada"] or not _cfg.get("compras"):
        return
    agora = _agora()
    mudou = False
    for canal_id, c in list(_cfg["compras"].items()):
        quando = c.get("fechar_em")
        if not quando or datetime.fromisoformat(quando) > agora:
            continue
        try:
            await dc("DELETE", f"/channels/{canal_id}", motivo="Compra encerrada")
        except ErroDiscord as erro:
            if erro.status != 404 and erro.codigo != 10003:
                log.warning("Não consegui fechar o chat de compra %s: %s", canal_id, erro)
                continue
        if c["status"] == "aguardando":
            await registrar(f'⌛ A compra de <@{c["comprador"]}> (código `{c["txid"]}`) expirou sem pagamento informado.')
        _cfg["compras"].pop(canal_id, None)
        mudou = True
    if mudou:
        await salvar_config()


# Importados no fim: estes módulos também usam este aqui (evita import circular).
from .busca import _canal_existe
from .central import alertar_equipe, tem_canal_alertas
from .config import log
from .discord_api import ErroDiscord, dc
from .interface import _botao, _com_rodape, _embed_da_mensagem, _linha, _partes, _valor_modal
from .memoria import _cfg, _cfg_estado, exigir_config, garantir_config, registrar, salvar_config
from .paineis import _criar_canal_privado
from .pix import _qr_png, _qr_url_online, gerar_pix
from .util import ANEXAR, CORES, ENVIAR, HISTORICO, VER, _agora, _fmt, _reais, _slug, eu, servidor_id
