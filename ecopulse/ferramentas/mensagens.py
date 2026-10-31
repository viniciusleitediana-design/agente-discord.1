"""Ferramentas do conector: mensagens."""

from datetime import timedelta
from typing import Any

from ..conector import DESTRUTIVA, LEITURA, mcp

# ── mensagens ──

@mcp.tool()
async def enviar_mensagem(canal_id: str, texto: str | None = None, titulo: str | None = None,
                          descricao: str | None = None, cor: str | None = None, imagem_url: str | None = None,
                          miniatura_url: str | None = None, rodape: str | None = None,
                          botao_texto: str | None = None, botao_link: str | None = None,
                          mencionar_todos: bool = False, responder_a: str | None = None,
                          painel: str | None = None, opcoes_painel: dict | None = None) -> dict:
    """Envia uma mensagem em um canal. Use texto para mensagem simples e/ou titulo + descricao para um
    embed (caixa colorida; cor = #RRGGBB ou verde, azul, vermelho, amarelo, roxo, laranja, rosa, dourado...).
    botao_link adiciona um botão com link. mencionar_todos=true permite @everyone/@here funcionar.
    responder_a = ID de uma mensagem para responder.
    painel = "ticket" ou "verificacao" publica esse painel neste canal (o mesmo que publicar_painel_ticket /
    publicar_painel_verificacao); opcoes_painel leva os campos deles, ex.: {"cargo": "Membro", "copiar_de": link}."""
    if painel:
        func = {"ticket": publicar_painel_ticket, "verificacao": publicar_painel_verificacao}.get(_norm(painel))
        if not func:
            raise ErroDiscord('painel aceita "ticket" ou "verificacao".')
        return await func(canal_id=canal_id, **(opcoes_painel or {}))
    canal = await achar_canal(canal_id, tipos=TIPOS_MENSAGEM)
    payload = montar_mensagem(texto, titulo, descricao, cor, imagem_url, miniatura_url, rodape,
                              botao_texto, botao_link, mencionar_todos)
    if responder_a:
        payload["message_reference"] = {"message_id": _id(responder_a) or responder_a, "fail_if_not_exists": False}
    msg = await dc("POST", f'/channels/{canal["id"]}/messages', corpo=payload)
    return {"ok": True, "mensagem_id": msg["id"], "canal": canal["name"],
            "link": _link_canal(await servidor_id(), canal["id"], msg["id"])}


@mcp.tool()
async def editar_mensagem(canal_id: str, mensagem_id: str, texto: str | None = None, titulo: str | None = None,
                          descricao: str | None = None, cor: str | None = None, imagem_url: str | None = None,
                          rodape: str | None = None, botao_texto: str | None = None, botao_link: str | None = None,
                          remover_embed: bool = False) -> dict:
    """Edita uma mensagem enviada pelo bot. Só os campos passados mudam; texto="" apaga o texto."""
    canal = await achar_canal(canal_id, tipos=TIPOS_MENSAGEM)
    atual = await dc("GET", f'/channels/{canal["id"]}/messages/{mensagem_id}')
    if atual["author"]["id"] != (await eu())["id"]:
        raise ErroDiscord("Só consigo editar mensagens enviadas pelo próprio bot.")
    sorteio = next((s for s in _cfg.get("sorteios", {}).values() if s.get("mensagem_id") == str(atual["id"])), None)
    if sorteio:
        return await _editar_sorteio(sorteio, titulo, descricao, cor, imagem_url, botao_link)
    corpo: dict[str, Any] = {}
    if texto is not None:
        if len(texto) > 2000:
            raise ErroDiscord("O texto passou de 2000 caracteres.")
        corpo["content"] = texto
    if remover_embed:
        corpo["embeds"] = []
    elif any(v is not None for v in (titulo, descricao, cor, imagem_url, rodape)):
        embed = dict(atual["embeds"][0]) if atual.get("embeds") else {"color": COR_PADRAO}
        for chave in ("type", "video", "provider"):
            embed.pop(chave, None)
        if titulo is not None:
            embed["title"] = titulo[:256]
        if descricao is not None:
            embed["description"] = descricao[:4096]
        if cor is not None:
            embed["color"] = _cor(cor)
        if imagem_url is not None:
            embed["image"] = {"url": imagem_url} if imagem_url else None
        if rodape is not None:
            embed["footer"] = {"text": rodape} if rodape else None
        corpo["embeds"] = [{k: v for k, v in embed.items() if v is not None}]
    if botao_link is not None:
        corpo["components"] = [] if not botao_link else [{"type": 1, "components": [
            {"type": 2, "style": 5, "label": (botao_texto or "Abrir")[:80], "url": botao_link}]}]
    if not corpo:
        raise ErroDiscord("Nada para mudar.")
    await dc("PATCH", f'/channels/{canal["id"]}/messages/{mensagem_id}', corpo=corpo)
    return {"ok": True, "mensagem_id": mensagem_id, "mudou": list(corpo)}


@mcp.tool(annotations=DESTRUTIVA)
async def apagar_mensagem(canal_id: str, mensagem_id: str) -> str:
    """Apaga uma mensagem."""
    canal = await achar_canal(canal_id, tipos=TIPOS_MENSAGEM)
    await dc("DELETE", f'/channels/{canal["id"]}/messages/{mensagem_id}', motivo="Agente ECO PULSE")
    return f'✅ Mensagem {mensagem_id} apagada de #{canal["name"]}.'


@mcp.tool(annotations=LEITURA)
async def ler_mensagens(canal_id: str, limite: int = 20, completo: bool = False) -> dict:
    """Lê as últimas mensagens de um canal (até 100), da mais antiga para a mais nova.
    completo=true traz o texto e o embed inteiros (sem cortar), para revisar textos longos como regras."""
    canal = await achar_canal(canal_id, tipos=TIPOS_MENSAGEM)
    msgs = await dc("GET", f'/channels/{canal["id"]}/messages', params={"limit": max(1, min(100, limite))})
    saida, vazias = [], 0
    for m in reversed(msgs):
        item: dict[str, Any] = {"id": m["id"], "autor": m["author"].get("global_name") or m["author"]["username"],
                                "autor_id": m["author"]["id"], "quando": _fmt(m["timestamp"]),
                                "texto": (m.get("content") or "")[:None if completo else 600]}
        if m.get("embeds"):
            e0 = m["embeds"][0]
            item["embed"] = "\n".join(x for x in (e0.get("title"), (e0.get("description") or "")[:None if completo else 1500]) if x)
            if completo and e0.get("fields"):
                item["embed"] += "".join(f'\n\n{f.get("name")}\n{f.get("value")}' for f in e0["fields"])
        if m.get("components"):
            item["botoes"] = [b.get("texto") or b.get("tipo") for b in _resumo_componentes(m["components"])]
            opcoes = [f'{o.get("texto")} — {o.get("descricao") or ""}'.strip(" —")
                      for b in _resumo_componentes(m["components"]) for o in b.get("opcoes", [])]
            if opcoes:
                item["opcoes_do_menu"] = opcoes
        if m.get("attachments"):
            item["anexos"] = [a["filename"] for a in m["attachments"]]
        if m.get("pinned"):
            item["fixada"] = True
        if not m.get("content") and not m.get("embeds") and not m.get("attachments") and not m["author"].get("bot"):
            vazias += 1
        saida.append(item)
    resultado: dict[str, Any] = {"canal": canal["name"], "mensagens": saida}
    if vazias and vazias >= len(saida) // 2:
        resultado["aviso"] = "Muitas mensagens vieram sem texto: ative MESSAGE CONTENT INTENT no Developer Portal → Bot."
    return resultado


@mcp.tool(annotations=DESTRUTIVA)
async def limpar_mensagens(canal_id: str, quantidade: int, confirmado: bool = False,
                           apenas_do_membro: str | None = None) -> str:
    """Apaga em massa as últimas mensagens de um canal (até 500; só as com menos de 14 dias).
    apenas_do_membro limita a uma pessoa. Só chame com confirmado=true depois que o usuário confirmar."""
    canal = await achar_canal(canal_id, tipos=TIPOS_MENSAGEM)
    quantidade = max(1, min(500, int(quantidade)))
    uid = None
    if apenas_do_membro:
        uid = _id(apenas_do_membro) or (await achar_membro(apenas_do_membro))["user"]["id"]
    if not confirmado:
        quem = f" de <@{uid}>" if uid else ""
        return f"⚠️ Nada foi apagado. Confirme com o usuário: apagar as últimas {quantidade} mensagens{quem} de #{canal['name']}? Depois chame com confirmado=true."
    limite = _agora() - timedelta(days=13, hours=23)
    ids: list[str] = []
    antigas, antes = 0, None
    for _ in range(20):
        params: dict[str, Any] = {"limit": 100}
        if antes:
            params["before"] = antes
        lote = await dc("GET", f'/channels/{canal["id"]}/messages', params=params)
        if not lote:
            break
        for m in lote:
            if uid and m["author"]["id"] != uid:
                continue
            if _data_snowflake(m["id"]) < limite:
                antigas += 1
                continue
            ids.append(m["id"])
            if len(ids) >= quantidade:
                break
        antes = lote[-1]["id"]
        if len(ids) >= quantidade or len(lote) < 100 or _data_snowflake(antes) < limite:
            break
    for i in range(0, len(ids), 100):
        grupo = ids[i:i + 100]
        if len(grupo) == 1:
            await dc("DELETE", f'/channels/{canal["id"]}/messages/{grupo[0]}', motivo="Limpeza pelo agente")
        else:
            await dc("POST", f'/channels/{canal["id"]}/messages/bulk-delete', corpo={"messages": grupo}, motivo="Limpeza pelo agente")
    await registrar(f'🧹 O agente apagou {len(ids)} mensagens de <#{canal["id"]}>.')
    extra = f" ({antigas} tinham mais de 14 dias e o Discord não deixa apagar em massa)" if antigas else ""
    return f'✅ Apaguei {len(ids)} mensagens de #{canal["name"]}{extra}.'


@mcp.tool()
async def fixar_mensagem(canal_id: str, mensagem_id: str, fixar: bool = True) -> str:
    """Fixa ou desafixa uma mensagem no canal."""
    canal = await achar_canal(canal_id, tipos=TIPOS_MENSAGEM)
    metodo = "PUT" if fixar else "DELETE"
    try:
        await dc(metodo, f'/channels/{canal["id"]}/messages/pins/{mensagem_id}', motivo="Agente ECO PULSE")
    except ErroDiscord as erro:
        if erro.status not in (404, 405) or erro.codigo:
            raise
        await dc(metodo, f'/channels/{canal["id"]}/pins/{mensagem_id}', motivo="Agente ECO PULSE")
    return f'📌 Mensagem {"fixada" if fixar else "desafixada"} em #{canal["name"]}.'


@mcp.tool()
async def reagir(canal_id: str, mensagem_id: str, emoji: str) -> str:
    """Faz o bot reagir a uma mensagem com um emoji (ex.: ✅ ou <:nome:id> para emoji do servidor)."""
    canal = await achar_canal(canal_id, tipos=TIPOS_MENSAGEM)
    await dc("PUT", f'/channels/{canal["id"]}/messages/{mensagem_id}/reactions/{_emoji_url(emoji)}/@me')
    return f"✅ Reagi com {emoji}."


@mcp.tool()
async def criar_enquete(canal_id: str, pergunta: str, opcoes: list[str], horas: int = 24,
                        multipla_escolha: bool = False) -> dict:
    """Cria uma enquete nativa do Discord (2 a 10 opções, de 1 a 768 horas)."""
    canal = await achar_canal(canal_id, tipos=TIPOS_MENSAGEM)
    if not 2 <= len(opcoes) <= 10:
        raise ErroDiscord("A enquete precisa de 2 a 10 opções.")
    corpo = {"poll": {"question": {"text": pergunta[:300]},
                      "answers": [{"poll_media": {"text": o[:55]}} for o in opcoes],
                      "duration": max(1, min(768, int(horas))), "allow_multiselect": multipla_escolha}}
    msg = await dc("POST", f'/channels/{canal["id"]}/messages', corpo=corpo)
    return {"ok": True, "mensagem_id": msg["id"], "link": _link_canal(await servidor_id(), canal["id"], msg["id"])}


@mcp.tool()
async def enviar_dm(membro: str, texto: str | None = None, titulo: str | None = None, descricao: str | None = None,
                    cor: str | None = None, imagem_url: str | None = None, botao_texto: str | None = None,
                    botao_link: str | None = None) -> str:
    """Manda uma mensagem direta (DM) do bot para um membro."""
    m = await achar_membro(membro)
    payload = montar_mensagem(texto, titulo, descricao, cor, imagem_url, None, None, botao_texto, botao_link)
    dm = await dc("POST", "/users/@me/channels", corpo={"recipient_id": m["user"]["id"]})
    await dc("POST", f'/channels/{dm["id"]}/messages', corpo=payload)
    return f"✅ DM enviada para {_nome_membro(m)}."


# Importados no fim: estes módulos também usam este aqui (evita import circular).
from ..busca import _link_canal, achar_canal, achar_membro
from ..config import COR_PADRAO
from ..discord_api import ErroDiscord, dc
from .tickets import publicar_painel_ticket
from .verificacao import publicar_painel_verificacao
from ..memoria import _cfg, registrar
from ..paineis import _resumo_componentes
from ..sorteios import _editar_sorteio
from ..util import (
    TIPOS_MENSAGEM,
    _agora,
    _cor,
    _data_snowflake,
    _emoji_url,
    _fmt,
    _id,
    _nome_membro,
    _norm,
    eu,
    montar_mensagem,
    servidor_id,
)
