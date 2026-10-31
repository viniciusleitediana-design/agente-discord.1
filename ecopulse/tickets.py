"""Tickets de suporte: abrir, assumir, fechar e histórico em .txt."""

import asyncio
import json
from datetime import datetime, timedelta
from typing import Any

from .discord_api import _Resposta

# ── tickets ──

def _botoes_ticket(assumido: bool) -> dict:
    botoes = [_botao("Fechar ticket", "ecot:fechar", 4, "🔒")]
    if not assumido:
        botoes.append(_botao("Assumir", "ecot:assumir", 2, "🙋"))
    return _linha(*botoes)


async def _abrir_ticket(r: _Resposta, pid: str, escolha: str | None) -> None:
    inter = r.inter
    await r.adiar()
    await exigir_config()
    painel = _cfg["paineis"].get(pid)
    if not painel or painel.get("tipo") != "ticket":
        await r.efemera("Este painel não está mais ativo. Avise a equipe.")
        return
    motivo = None
    if escolha is not None:
        try:
            motivo = (painel.get("motivos") or [])[int(escolha)]
        except (ValueError, IndexError):
            motivo = str(escolha)
    uid = str(inter.user.id)
    nome = getattr(inter.user, "display_name", None) or inter.user.name
    async with _ticket_lock:
        for canal_id, t in list(_cfg["tickets"].items()):
            if t["dono"] == uid and t.get("painel") == pid and t.get("status") == "aberto":
                if await _canal_existe(canal_id):
                    await r.efemera(f"Você já tem um ticket aberto: <#{canal_id}>")
                    return
                _cfg["tickets"].pop(canal_id, None)
        _cfg["contador_tickets"] = int(_cfg.get("contador_tickets") or 0) + 1
        numero = _cfg["contador_tickets"]
        gid, bot = await servidor_id(), await eu()
        acesso = VER | ENVIAR | HISTORICO | ANEXAR | EMBED_LINKS
        perms: list[dict[str, Any]] = [
            {"id": gid, "type": 0, "allow": "0", "deny": str(VER)},
            {"id": uid, "type": 1, "allow": str(acesso), "deny": "0"},
            {"id": bot["id"], "type": 1, "allow": str(acesso | GERENCIAR_MSG), "deny": "0"},
        ] + [{"id": c["id"], "type": 0, "allow": str(acesso | GERENCIAR_MSG), "deny": "0"} for c in painel.get("cargos_equipe", [])]
        prefixo = painel.get("prefixo") or "🎫・ticket"
        canal = await _criar_canal_privado(
            f"{prefixo}-{_slug(nome, 30) or _slug(inter.user.name, 30) or numero}", perms, painel.get("categoria_id"),
            f"Ticket #{numero:04d} de <@{uid}>" + (f" • {motivo}" if motivo else "") + " • só você e a equipe veem",
            f"Ticket de {inter.user.name}")
        _cfg["tickets"][canal["id"]] = {"painel": pid, "dono": uid, "dono_nome": nome, "numero": numero,
                                        "motivo": motivo, "aberto": _agora().isoformat(), "status": "aberto"}
    abertura = painel.get("mensagem_abertura") or (
        "Olá, {usuario}! Este canal é **privado**: só você e a equipe conseguem ver.\n\n"
        "Explique com detalhes o que você precisa que a equipe já vem te atender.")
    descricao = _preencher(abertura, {"usuario": f"<@{uid}>", "usuário": f"<@{uid}>", "nome": nome})
    if motivo:
        descricao += f"\n\n📌 **Assunto:** {motivo}"
    equipe = [c["id"] for c in painel.get("cargos_equipe", [])] if painel.get("avisar_equipe", True) else []
    if painel.get("avisar_equipe", True) and await alertar_equipe(
            f'🎫 **Novo ticket** #{numero:04d} • <@{uid}>' + (f" • {motivo}" if motivo else "") + f' → <#{canal["id"]}>', equipe):
        equipe = []  # a equipe já foi avisada no canal de alertas; aqui só o cliente é mencionado
    try:
        await dc("POST", f'/channels/{canal["id"]}/messages', corpo={
            "content": " ".join([f"<@{uid}>"] + [f"<@&{c}>" for c in equipe]),
            "embeds": [{"title": f"🎫 Ticket #{numero:04d}", "description": descricao, "color": painel.get("cor") or COR_PADRAO,
                        "footer": {"text": "Para encerrar, clique em 🔒 Fechar ticket"}}],
            "components": [_botoes_ticket(False)],
            "allowed_mentions": {"parse": [], "users": [uid], "roles": equipe}})
    finally:
        await salvar_config()
    await r.efemera(f'✅ Seu ticket foi aberto: <#{canal["id"]}>')
    await registrar(f'🎫 <@{uid}> abriu o ticket #{numero:04d} em <#{canal["id"]}>' + (f" ({motivo})." if motivo else "."))


async def _assumir_ticket(r: _Resposta) -> None:
    inter = r.inter
    t = _cfg["tickets"].get(str(inter.channel_id))
    if not t or t.get("status") != "aberto":
        await r.efemera("Este ticket já foi encerrado.")
        return
    painel = _cfg["paineis"].get(t.get("painel"), {})
    if not _eh_equipe(inter, painel):
        await r.efemera("Só a equipe pode assumir tickets.")
        return
    if t.get("assumido_por"):
        await r.efemera(f'Este ticket já está com <@{t["assumido_por"]}>.')
        return
    quem = str(inter.user.id)
    nome_quem = getattr(inter.user, "display_name", None) or inter.user.name
    t["assumido_por"], t["assumido_nome"] = quem, nome_quem
    embed = _com_rodape(_embed_da_mensagem(inter), f"🙋 Atendido por {nome_quem} • para encerrar, clique em 🔒 Fechar ticket")
    await r.enviar(7, {"embeds": [embed], "components": [_botoes_ticket(True)]})
    await dc("POST", f"/channels/{inter.channel_id}/messages", corpo={
        "content": f'🙋 <@{quem}> assumiu o seu atendimento, <@{t["dono"]}>.',
        "allowed_mentions": {"parse": [], "users": [t["dono"]]}})
    await salvar_config()


async def _pedir_confirmacao_fechar(r: _Resposta) -> None:
    inter = r.inter
    t = _cfg["tickets"].get(str(inter.channel_id))
    if not t or t.get("status") != "aberto":
        await r.efemera("Este ticket já está sendo encerrado.")
        return
    painel = _cfg["paineis"].get(t.get("painel"), {})
    if str(inter.user.id) != t["dono"] and not _eh_equipe(inter, painel):
        await r.efemera("Só quem abriu o ticket ou a equipe pode fechar.")
        return
    await r.enviar(4, {"content": "Tem certeza que quer **fechar** este ticket? O canal será apagado e o histórico fica salvo.",
                       "flags": 64, "components": [_linha(_botao("Sim, fechar", "ecot:confirmar", 4, "🔒"))]})


async def _historico_ticket(canal_id: str) -> tuple[bytes, int]:
    msgs: list[dict] = []
    antes = None
    for _ in range(30):  # até 3000 mensagens
        params: dict[str, Any] = {"limit": 100}
        if antes:
            params["before"] = antes
        lote = await dc("GET", f"/channels/{canal_id}/messages", params=params)
        if not lote:
            break
        msgs.extend(lote)
        antes = lote[-1]["id"]
        if len(lote) < 100:
            break
    linhas = []
    for m in reversed(msgs):
        autor = m["author"].get("global_name") or m["author"]["username"]
        partes = [m.get("content") or ""]
        for e in m.get("embeds", []):
            partes.append(" | ".join(x for x in (e.get("title"), e.get("description")) if x))
        partes += [a["url"].split("?")[0] for a in m.get("attachments", [])]
        texto = "\n    ".join(p for p in partes if p) or "(sem texto)"
        linhas.append(f"[{_fmt(m['timestamp'])}] {autor} (@{m['author']['username']}): {texto}")
    return ("\n".join(linhas) + "\n").encode(), len(msgs)


async def encerrar_ticket(canal_id: str, quem: str | None, quem_nome: str) -> None:
    """Salva o histórico, avisa o dono e apaga o canal do ticket."""
    t = _cfg["tickets"].get(canal_id)
    if not t or t.get("status") == "fechando":
        return
    t["status"] = "fechando"
    t["fechar_em"] = (_agora() + timedelta(seconds=FECHAR_TICKET_EM)).isoformat()
    t["fechado_por"] = quem
    await salvar_config()
    painel = _cfg["paineis"].get(t.get("painel"), {})
    try:
        historico, total = await _historico_ticket(canal_id)
    except ErroDiscord as erro:
        log.warning("Não consegui ler o histórico do ticket %s: %s", canal_id, erro)
        historico, total = b"", 0
    nome_arquivo = f'ticket-{int(t.get("numero") or 0):04d}-{_slug(t.get("dono_nome"), 20) or t["dono"]}.txt'
    resumo = {"title": f'🎫 Ticket #{int(t.get("numero") or 0):04d} fechado', "color": CORES["cinza"], "description": (
        f'👤 **Aberto por:** <@{t["dono"]}>\n' + (f'📌 **Assunto:** {t["motivo"]}\n' if t.get("motivo") else "")
        + (f'🙋 **Atendido por:** <@{t["assumido_por"]}>\n' if t.get("assumido_por") else "")
        + f"🔒 **Fechado por:** {f'<@{quem}>' if quem else quem_nome}\n"
        + f'🕐 **Aberto em:** {_fmt(t.get("aberto"))} • **Fechado em:** {_fmt(_agora())}\n💬 **Mensagens:** {total}')}
    destino = painel.get("canal_historico_id") or ((_cfg.get("logs") or {}).get("canal_id") if (_cfg.get("logs") or {}).get("ativo") else None)
    if destino and historico:
        try:
            await dc("POST", f"/channels/{destino}/messages", dados={"payload_json": json.dumps({
                "embeds": [resumo], "allowed_mentions": {"parse": []}, "attachments": [{"id": 0, "filename": nome_arquivo}]})},
                arquivos={"files[0]": (nome_arquivo, historico, "text/plain")})
        except ErroDiscord as erro:
            log.warning("Não consegui salvar o histórico do ticket: %s", erro)
    try:
        dm = await dc("POST", "/users/@me/channels", corpo={"recipient_id": t["dono"]})
        aviso = {"title": "🎫 Seu ticket foi fechado", "color": CORES["cinza"],
                 "description": "Obrigado pelo contato! Se precisar de novo, é só abrir outro ticket no servidor."}
        if historico:
            await dc("POST", f'/channels/{dm["id"]}/messages', dados={"payload_json": json.dumps({
                "embeds": [aviso], "attachments": [{"id": 0, "filename": nome_arquivo}]})},
                arquivos={"files[0]": (nome_arquivo, historico, "text/plain")})
        else:
            await dc("POST", f'/channels/{dm["id"]}/messages', corpo={"embeds": [aviso]})
    except ErroDiscord:
        pass
    await asyncio.sleep(max(0.0, (datetime.fromisoformat(t["fechar_em"]) - _agora()).total_seconds()))
    await _apagar_ticket(canal_id)


async def _apagar_ticket(canal_id: str) -> None:
    t = _cfg["tickets"].get(canal_id)
    try:
        await dc("DELETE", f"/channels/{canal_id}", motivo="Ticket fechado")
    except ErroDiscord as erro:
        if erro.status != 404 and erro.codigo != 10003:
            log.warning("Não consegui apagar o ticket %s: %s", canal_id, erro)
            return
    if t:
        _cfg["tickets"].pop(canal_id, None)
        await registrar(f'🔒 Ticket #{int(t.get("numero") or 0):04d} de <@{t["dono"]}> fechado.')
        await salvar_config()


async def _confirmar_fechar(r: _Resposta) -> None:
    inter = r.inter
    canal_id = str(inter.channel_id)
    t = _cfg["tickets"].get(canal_id)
    if not t or t.get("status") != "aberto":
        await r.efemera("Este ticket já está sendo encerrado.")
        return
    painel = _cfg["paineis"].get(t.get("painel"), {})
    if str(inter.user.id) != t["dono"] and not _eh_equipe(inter, painel):
        await r.efemera("Só quem abriu o ticket ou a equipe pode fechar.")
        return
    await r.enviar(7, {"content": "🔒 Fechando…", "components": []})
    nome = getattr(inter.user, "display_name", None) or inter.user.name
    await dc("POST", f"/channels/{canal_id}/messages", corpo={
        "content": f"🔒 Ticket fechado por <@{inter.user.id}>. O histórico foi salvo e este canal some em {FECHAR_TICKET_EM} segundos.",
        "allowed_mentions": {"parse": []}})
    await encerrar_ticket(canal_id, str(inter.user.id), nome)


async def limpar_tickets() -> None:
    """Termina de fechar tickets que ficaram pela metade (ex.: o bot reiniciou) e esquece canais apagados à mão."""
    if not _cfg_estado["carregada"] or not _cfg.get("tickets"):
        return
    agora = _agora()
    for canal_id, t in list(_cfg["tickets"].items()):
        if t.get("status") == "fechando" and t.get("fechar_em") and datetime.fromisoformat(t["fechar_em"]) <= agora - timedelta(seconds=30):
            await _apagar_ticket(canal_id)


# Importados no fim: estes módulos também usam este aqui (evita import circular).
from .busca import _canal_existe
from .central import alertar_equipe
from .config import COR_PADRAO, log
from .discord_api import ErroDiscord, dc
from .interface import _botao, _com_rodape, _embed_da_mensagem, _linha
from .loja import EMBED_LINKS, GERENCIAR_MSG
from .memoria import _cfg, _cfg_estado, exigir_config, registrar, salvar_config
from .paineis import FECHAR_TICKET_EM, _criar_canal_privado, _eh_equipe, _ticket_lock
from .util import ANEXAR, CORES, ENVIAR, HISTORICO, VER, _agora, _fmt, _preencher, _slug, eu, servidor_id
