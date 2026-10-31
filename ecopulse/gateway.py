"""Eventos em tempo real (discord.py): entradas, mensagens, reações e interações."""

import asyncio
import re
import time
from typing import Any

from . import estado
from .discord_api import _Resposta

_bot_estado: dict[str, Any] = {"status": "desligado", "intents_privilegiadas": None, "aviso": None}
_ultimas_respostas: dict[tuple[str, str], float] = {}


def _campos_membro(uid: str, nome: str, servidor: str, membros: Any) -> dict[str, str]:
    return {"usuario": f"<@{uid}>", "usuário": f"<@{uid}>", "mencao": f"<@{uid}>", "nome": nome,
            "servidor": servidor, "membros": str(membros if membros is not None else "?")}


async def _mandar_config_mensagem(conf: dict, campos: dict[str, str], canal_id: str) -> None:
    payload = montar_mensagem(texto=conf.get("texto"), titulo=conf.get("titulo"), descricao=conf.get("descricao"),
                              cor=conf.get("cor"), imagem_url=conf.get("imagem_url"))
    await _postar(canal_id, _preencher(payload, campos))


async def ao_entrar(uid: str, nome: str, servidor: str, membros: Any, bot: bool) -> None:
    await garantir_config()
    campos = _campos_membro(uid, nome, servidor, membros)
    bv = _cfg.get("boas_vindas") or {}
    if bv.get("ativo") and not bot:
        if bv.get("cargo_id"):
            try:
                await dc("PUT", f'/guilds/{await servidor_id()}/members/{uid}/roles/{bv["cargo_id"]}', motivo="Cargo automático de entrada")
            except ErroDiscord as erro:
                await registrar(f"⚠️ Não consegui dar o cargo automático para <@{uid}>: {erro}")
        if bv.get("canal_id"):
            try:
                await _mandar_config_mensagem(bv, campos, bv["canal_id"])
            except ErroDiscord as erro:
                await registrar(f"⚠️ Falha na mensagem de boas-vindas: {erro}")
        if bv.get("mandar_dm"):
            try:
                dm = await dc("POST", "/users/@me/channels", corpo={"recipient_id": uid})
                await _mandar_config_mensagem(bv, campos, dm["id"])
            except ErroDiscord:
                pass
    await registrar(f"📥 **{nome}** (<@{uid}>) entrou{' (bot)' if bot else ''} — agora são {campos['membros']} membros.")


async def ao_sair(uid: str, nome: str, servidor: str, membros: Any) -> None:
    await garantir_config()
    campos = _campos_membro(uid, nome, servidor, membros)
    dp = _cfg.get("despedida") or {}
    if dp.get("ativo") and dp.get("canal_id"):
        try:
            await _mandar_config_mensagem(dp, campos, dp["canal_id"])
        except ErroDiscord as erro:
            await registrar(f"⚠️ Falha na mensagem de despedida: {erro}")
    await registrar(f"📤 **{nome}** (<@{uid}>) saiu do servidor.")


def achar_resposta(conteudo: str, canal_id: str) -> dict | None:
    texto = _norm_frase(conteudo)
    if not texto:
        return None
    for regra in _cfg.get("respostas", []):
        if regra.get("canal_id") and regra["canal_id"] != canal_id:
            continue
        gatilho = _norm_frase(regra["gatilho"])
        modo = regra.get("modo", "contem")
        if modo == "exata":
            ok = texto == gatilho
        elif modo == "comeca":
            ok = texto.startswith(gatilho)
        else:
            ok = re.search(rf"(?<!\w){re.escape(gatilho)}(?!\w)", texto) is not None
        if ok:
            return regra
    return None


async def ao_mensagem(conteudo: str, canal_id: str, mensagem_id: str, autor_id: str, autor_nome: str) -> None:
    regra = achar_resposta(conteudo, canal_id)
    if not regra:
        return
    chave = (regra["id"], canal_id)
    if time.time() - _ultimas_respostas.get(chave, 0) < 10:
        return  # evita flood
    _ultimas_respostas[chave] = time.time()
    texto = _preencher(regra["resposta"], {"usuario": f"<@{autor_id}>", "usuário": f"<@{autor_id}>", "nome": autor_nome})
    await dc("POST", f"/channels/{canal_id}/messages", corpo={
        "content": texto[:2000], "message_reference": {"message_id": mensagem_id, "fail_if_not_exists": False},
        "allowed_mentions": {"parse": ["users"], "replied_user": True}})


async def ao_reagir(mensagem_id: str, emoji_chave: str, uid: str, adicionou: bool) -> None:
    for regra in _cfg.get("cargos_reacao", []):
        if regra["mensagem_id"] == mensagem_id and regra["emoji"] == emoji_chave:
            metodo = "PUT" if adicionou else "DELETE"
            try:
                await dc(metodo, f'/guilds/{await servidor_id()}/members/{uid}/roles/{regra["cargo_id"]}', motivo="Cargo por reação")
            except ErroDiscord as erro:
                await registrar(f"⚠️ Cargo por reação falhou para <@{uid}>: {erro}")


async def _clique_loja(r: _Resposta, tipo: int, acao: str, partes: list[str]) -> None:
    if tipo == 5:
        if acao == "modal_pago":
            await _modal_pago(r)
    elif acao == "comprar":
        await _clicou_comprar(r, partes[2] if len(partes) > 2 else "")
    elif acao == "pago":
        await _clicou_pago(r)
    elif acao in ("aprovar", "recusar"):
        await _decidir(r, acao == "aprovar")
    elif acao in ("cancelar", "fechar"):
        await _clicou_fechar(r, acao)
    elif acao in ("fechar_entrega", "fechar_entrega_ok"):
        await _clicou_fechar_entrega(r, acao == "fechar_entrega_ok")


async def _clique_ticket(r: _Resposta, acao: str, partes: list[str], dados: dict) -> None:
    if acao == "abrir":
        valores = dados.get("values") or []
        await _abrir_ticket(r, partes[2] if len(partes) > 2 else "", valores[0] if valores else None)
        return
    if not _cfg_estado["carregada"]:
        asyncio.create_task(garantir_config())
        await r.efemera("O bot acabou de reiniciar. Tente de novo em alguns segundos.")
        return
    if acao == "assumir":
        await _assumir_ticket(r)
    elif acao == "fechar":
        await _pedir_confirmacao_fechar(r)
    elif acao == "confirmar":
        await _confirmar_fechar(r)


async def ao_interagir(inter: Any) -> None:
    dados = inter.data or {}
    if getattr(inter.type, "value", inter.type) in (2, 4):   # comando de barra / autocompletar
        await ao_comando(inter, getattr(inter.type, "value", inter.type), dados)
        return
    cid = str(dados.get("custom_id") or "")
    partes = cid.split(":")
    prefixo = partes[0]
    if prefixo not in ("ecop", "ecot", "ecov", "ecos", "ecvd"):
        return
    acao = partes[1] if len(partes) > 1 else ""
    tipo = getattr(inter.type, "value", inter.type)   # 3 = botão/menu, 5 = formulário
    r = _Resposta(inter)
    try:
        if prefixo == "ecop":
            await _clique_loja(r, tipo, acao, partes)
        elif prefixo == "ecot":
            await _clique_ticket(r, acao, partes, dados)
        elif prefixo == "ecov":
            await _verificar(r, acao)
        elif prefixo == "ecos" and acao in ("entrar", "sair"):
            await _clique_sorteio(r, acao, partes[2] if len(partes) > 2 else "")
        elif prefixo == "ecvd":
            await ao_clique_vendas(r, tipo, partes, dados)
    except Exception as erro:
        log.exception("Falha no botão %s", cid)
        texto = str(erro) if isinstance(erro, ErroDiscord) else "Deu um erro aqui. Tente de novo ou chame a equipe."
        try:
            await r.efemera(f"⚠️ {texto}")
        except Exception:
            pass


def _novo_cliente(privilegiadas: bool):
    intents = discord.Intents.none()
    intents.guilds = True
    intents.guild_messages = True
    intents.guild_reactions = True
    if privilegiadas:
        intents.members = True
        intents.message_content = True
    cliente = discord.Client(intents=intents, max_messages=None, chunk_guilds_at_startup=False,
                             member_cache_flags=discord.MemberCacheFlags.none())

    def _do_servidor(guild) -> bool:
        return guild is not None and (not estado._servidor or str(guild.id) == estado._servidor)

    @cliente.event
    async def on_ready():
        servidores = ", ".join(f"{g.name} (ID {g.id})" for g in cliente.guilds) or "nenhum"
        _bot_estado["status"] = f"conectado como {cliente.user}"
        _bot_estado["servidores"] = servidores
        log.info("Gateway conectado como %s. Servidores do bot: %s", cliente.user, servidores)
        if estado._servidor and not any(str(g.id) == estado._servidor for g in cliente.guilds):
            log.warning("O bot NÃO está no servidor GUILD_ID=%s. Convide o bot para o ECO PULSE ou corrija GUILD_ID.", estado._servidor)
        asyncio.create_task(registrar_comandos(str(getattr(cliente, "application_id", None) or cliente.user.id)))
        asyncio.create_task(iniciar_vendas())

    @cliente.event
    async def on_member_join(member):
        if _do_servidor(member.guild):
            await ao_entrar(str(member.id), member.display_name, member.guild.name, member.guild.member_count, member.bot)

    @cliente.event
    async def on_member_remove(member):
        if _do_servidor(member.guild):
            await ao_sair(str(member.id), member.display_name, member.guild.name, member.guild.member_count)

    @cliente.event
    async def on_message(message):
        if message.author.bot or not _do_servidor(message.guild) or not message.content:
            return
        try:
            await ao_mensagem(message.content, str(message.channel.id), str(message.id),
                              str(message.author.id), message.author.display_name)
        except ErroDiscord as erro:
            log.warning("Resposta automática falhou: %s", erro)

    async def _reacao(payload, adicionou: bool):
        if payload.guild_id is None or (cliente.user and payload.user_id == cliente.user.id):
            return
        if estado._servidor and str(payload.guild_id) != estado._servidor:
            return
        e = payload.emoji
        chave = f"id:{e.id}" if e.id else (e.name or "").replace("️", "")
        await ao_reagir(str(payload.message_id), chave, str(payload.user_id), adicionou)

    @cliente.event
    async def on_raw_reaction_add(payload):
        await _reacao(payload, True)

    @cliente.event
    async def on_raw_reaction_remove(payload):
        await _reacao(payload, False)

    @cliente.event
    async def on_interaction(interaction):
        if interaction.guild_id is None or (estado._servidor and str(interaction.guild_id) != estado._servidor):
            return
        if interaction.type not in (discord.InteractionType.component, discord.InteractionType.modal_submit,
                                    discord.InteractionType.application_command, discord.InteractionType.autocomplete):
            return
        await ao_interagir(interaction)

    return cliente


async def rodar_bot() -> None:
    if discord is None:
        _bot_estado["status"] = "desligado: biblioteca discord.py não instalada (confira o requirements.txt)"
        return
    if not TOKEN:
        _bot_estado["status"] = "desligado: falta DISCORD_TOKEN"
        return
    for privilegiadas in (True, False):
        estado._bot = _novo_cliente(privilegiadas)
        _bot_estado["intents_privilegiadas"] = privilegiadas
        _bot_estado["status"] = "conectando"
        try:
            await estado._bot.start(TOKEN)
            return
        except discord.PrivilegedIntentsRequired:
            _bot_estado["aviso"] = ("Ative SERVER MEMBERS INTENT e MESSAGE CONTENT INTENT no Developer Portal → Bot. "
                                    "Sem elas, boas-vindas, despedida e respostas automáticas não funcionam.")
            log.warning(_bot_estado["aviso"])
            try:
                await estado._bot.close()
            except Exception:
                pass
        except discord.LoginFailure:
            _bot_estado["status"] = "desligado: token inválido"
            return
        except asyncio.CancelledError:
            raise
        except Exception as erro:
            _bot_estado["status"] = f"desligado: {type(erro).__name__}: {erro}"
            log.exception("Gateway caiu")
            return


# Importados no fim: estes módulos também usam este aqui (evita import circular).
from .comandos import ao_comando, registrar_comandos
from .config import TOKEN, discord, log
from .discord_api import ErroDiscord, dc
from .loja import _clicou_comprar, _clicou_fechar, _clicou_fechar_entrega, _clicou_pago, _decidir, _modal_pago
from .memoria import _cfg, _cfg_estado, garantir_config, registrar
from .paineis import _postar
from .sorteios import _clique_sorteio
from .tickets import _abrir_ticket, _assumir_ticket, _confirmar_fechar, _pedir_confirmacao_fechar
from .util import _norm_frase, _preencher, montar_mensagem, servidor_id
from .vendas.backup import iniciar_vendas
from .vendas.comandos import ao_clique_vendas
from .verificacao import _verificar
