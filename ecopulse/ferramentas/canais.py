"""Ferramentas do conector: canais e categorias."""

from typing import Any

from ..conector import DESTRUTIVA, LEITURA, mcp

# ── canais ──

@mcp.tool(annotations=LEITURA)
async def listar_canais() -> dict:
    """Lista todos os canais e categorias do servidor, com id, nome, tipo e categoria."""
    canais = await _canais()
    gid = await servidor_id()
    cats = {c["id"]: c for c in canais if c["type"] == 4}

    def ordem(c):
        voz = 1 if c["type"] in (2, 13) else 0
        if c["type"] == 4:
            return (c["position"], 0, 0, 0)
        pai = cats.get(c.get("parent_id"))
        return (pai["position"] if pai else -1, 1, voz, c["position"])

    saida = []
    for c in sorted(canais, key=ordem):
        item: dict[str, Any] = {"id": c["id"], "nome": c["name"], "tipo": TIPOS.get(c["type"], str(c["type"]))}
        if c["type"] != 4 and c.get("parent_id") in cats:
            item["categoria"] = cats[c["parent_id"]]["name"]
        todos = next((o for o in c.get("permission_overwrites", []) if o["id"] == gid), None)
        if todos and int(todos["deny"]) & VER:
            item["privado"] = True
        saida.append(item)
    return {"canais": saida}


@mcp.tool()
async def criar_canal(nome: str, tipo: str = "texto", categoria_id: str | None = None, topico: str | None = None,
                      privado: bool = False, cargos_com_acesso: list[str] | None = None,
                      modo_lento_segundos: int | None = None) -> dict:
    """Cria um canal. tipo: texto, voz, categoria, anuncios, forum ou palco. categoria_id aceita ID ou nome.
    privado=true esconde de todos e libera só para cargos_com_acesso (nomes ou IDs)."""
    t = TIPOS_CRIAR.get(_norm(tipo))
    if t is None:
        raise ErroDiscord(f'Tipo "{tipo}" inválido. Use: texto, voz, categoria, anuncios, forum ou palco.')
    gid = await servidor_id()
    corpo: dict[str, Any] = {"name": nome, "type": t}
    if topico and t in (0, 5, 15):
        corpo["topic"] = topico[:1024]
    if categoria_id and t != 4:
        corpo["parent_id"] = (await achar_categoria(categoria_id))["id"]
    if modo_lento_segundos is not None and t in (0, 15):
        corpo["rate_limit_per_user"] = max(0, min(21600, int(modo_lento_segundos)))
    if privado or cargos_com_acesso:
        acesso = VER | ENVIAR | HISTORICO | CONECTAR | FALAR
        bot = await eu()
        sobre = [{"id": gid, "type": 0, "allow": "0", "deny": str(VER)},
                 {"id": bot["id"], "type": 1, "allow": str(acesso), "deny": "0"}]
        for ref in cargos_com_acesso or []:
            cargo = await achar_cargo(ref)
            sobre.append({"id": cargo["id"], "type": 0, "allow": str(acesso), "deny": "0"})
        corpo["permission_overwrites"] = sobre
    canal = await dc("POST", f"/guilds/{gid}/channels", corpo=corpo, motivo="Agente ECO PULSE")
    return {"ok": True, "id": canal["id"], "nome": canal["name"], "tipo": TIPOS.get(canal["type"]),
            "link": _link_canal(gid, canal["id"])}


@mcp.tool()
async def editar_canal(canal_id: str, nome: str | None = None, topico: str | None = None,
                       categoria_id: str | None = None, posicao: int | None = None,
                       modo_lento_segundos: int | None = None, nsfw: bool | None = None,
                       definir_como: str | None = None) -> dict:
    """Renomeia, muda o tópico, move de categoria (categoria_id = ID/nome, ou "nenhuma" para tirar),
    muda a posição, o modo lento (segundos, 0 desliga) ou a marcação +18 de um canal.
    posicao = lugar na lista (0 = primeiro): de uma categoria entre as categorias, de um canal dentro da
    categoria dele (canais de voz contam só entre os de voz). Os outros são empurrados, sem posições repetidas.
    definir_como = "regras" (canal de regras da Comunidade), "atualizacoes" (avisos do Discord para a
    moderação) ou "sistema" (entradas e impulsos): troca o canal usado pelo servidor para isso."""
    canal = await achar_canal(canal_id)
    corpo: dict[str, Any] = {}
    if nome is not None:
        corpo["name"] = nome
    if topico is not None:
        corpo["topic"] = topico[:1024]
    if categoria_id is not None:
        corpo["parent_id"] = None if _norm(categoria_id) in ("", "nenhuma", "semcategoria", "nada", "none") \
            else (await achar_categoria(categoria_id))["id"]
    if modo_lento_segundos is not None:
        corpo["rate_limit_per_user"] = max(0, min(21600, int(modo_lento_segundos)))
    if nsfw is not None:
        corpo["nsfw"] = nsfw
    campo_servidor = None
    if definir_como is not None:
        campo_servidor = {"regras": "rules_channel_id", "atualizacoes": "public_updates_channel_id",
                          "sistema": "system_channel_id"}.get(_norm(definir_como).replace("canalde", ""))
        if not campo_servidor:
            raise ErroDiscord('definir_como aceita "regras", "atualizacoes" ou "sistema".')
        if canal["type"] != 0:
            raise ErroDiscord("Só um canal de texto pode ser usado para isso.")
    if not corpo and posicao is None and not campo_servidor:
        raise ErroDiscord("Nada para mudar: passe nome, topico, categoria_id, posicao, modo_lento_segundos, nsfw ou definir_como.")
    novo = canal
    if corpo:
        novo = await dc("PATCH", f'/channels/{canal["id"]}', corpo=corpo, motivo="Agente ECO PULSE")
    mudou = list(corpo)
    if posicao is not None:
        await _reposicionar(novo, posicao)
        mudou.append("position")
    if campo_servidor:
        await dc("PATCH", f"/guilds/{await servidor_id()}", corpo={campo_servidor: canal["id"]}, motivo="Agente ECO PULSE")
        mudou.append(campo_servidor)
    return {"ok": True, "id": novo["id"], "nome": novo["name"], "mudou": mudou}


def _grupo_ordem(c: dict) -> int:
    """No Discord, categorias se ordenam entre si; dentro de uma categoria, texto vem antes e voz depois."""
    return 2 if c["type"] == 4 else (1 if c["type"] in (2, 13) else 0)


async def _reposicionar(canal: dict, indice: int) -> None:
    g, pai = _grupo_ordem(canal), canal.get("parent_id") or None
    irmaos = sorted((c for c in await _canais() if c["id"] != canal["id"] and _grupo_ordem(c) == g
                     and (g == 2 or (c.get("parent_id") or None) == pai)),
                    key=lambda c: (c["position"], int(c["id"])))
    irmaos.insert(max(0, min(int(indice), len(irmaos))), canal)
    await dc("PATCH", f"/guilds/{await servidor_id()}/channels", motivo="Agente ECO PULSE",
             corpo=[{"id": c["id"], "position": i} for i, c in enumerate(irmaos)])


@mcp.tool(annotations=DESTRUTIVA)
async def apagar_canal(canal_id: str, confirmado: bool = False) -> str:
    """Apaga um canal ou categoria. Só chame com confirmado=true depois que o usuário confirmar."""
    canal = await achar_canal(canal_id)
    if canal["id"] == _cfg_estado.get("canal_id") or canal["name"] == NOME_CANAL_CONFIG:
        raise ErroDiscord("Esse canal guarda a memória das automações do agente; não vou apagá-lo.")
    rotulo = f'{"a categoria" if canal["type"] == 4 else "o canal"} #{canal["name"]} ({canal["id"]})'
    if not confirmado:
        return f"⚠️ Nada foi apagado. Confirme com o usuário que ele quer apagar {rotulo} — não tem volta. Depois chame de novo com confirmado=true."
    await dc("DELETE", f'/channels/{canal["id"]}', motivo="Agente ECO PULSE")
    await registrar(f'🗑️ O agente apagou {rotulo}.')
    extra = " Os canais que estavam dentro dela ficaram sem categoria." if canal["type"] == 4 else ""
    return f"✅ Apaguei {rotulo}.{extra}"


@mcp.tool()
async def permissoes_canal(canal_id: str, alvo: str, permitir: list[str] | None = None,
                           negar: list[str] | None = None, herdar: list[str] | None = None,
                           limpar_tudo: bool = False) -> dict:
    """Muda o que um cargo (ou @everyone, ou um membro) pode fazer em um canal.
    Permissões: ver_canal, enviar_mensagens, ler_historico, reagir, anexar_arquivos, inserir_links,
    mencionar_todos, gerenciar_mensagens, conectar, falar, criar_threads, enviar_em_threads, usar_comandos,
    criar_enquetes... herdar volta a permissão para o padrão do servidor. limpar_tudo remove a regra desse alvo."""
    canal = await achar_canal(canal_id)
    alvo_id, tipo, rotulo = await achar_alvo_permissao(alvo)
    if limpar_tudo:
        await dc("DELETE", f'/channels/{canal["id"]}/permissions/{alvo_id}', motivo="Agente ECO PULSE")
        return {"ok": True, "canal": canal["name"], "alvo": rotulo, "regra": "removida (volta ao padrão)"}
    p, n, h = _bits(permitir), _bits(negar), _bits(herdar)
    if not (p or n or h):
        raise ErroDiscord("Passe pelo menos uma permissão em permitir, negar ou herdar.")
    allow, deny = await _sobrescrever(canal, alvo_id, tipo, p, n, h, motivo="Agente ECO PULSE")
    return {"ok": True, "canal": canal["name"], "alvo": rotulo,
            "permitido": _nomes_perm(allow), "negado": _nomes_perm(deny)}


@mcp.tool()
async def trancar_canal(canal_id: str, trancar: bool = True, motivo: str | None = None) -> str:
    """Tranca (ninguém sem cargo especial escreve) ou destranca um canal de texto."""
    canal = await achar_canal(canal_id)
    gid = await servidor_id()
    bits = ENVIAR | PERMISSOES["enviar_em_threads"] | PERMISSOES["criar_threads"]
    if trancar:
        await _sobrescrever(canal, gid, 0, negar=bits, motivo=motivo or "Canal trancado pelo agente")
        await dc("POST", f'/channels/{canal["id"]}/messages', corpo={
            "embeds": [{"color": CORES["vermelho"], "description": f"🔒 Canal trancado.{' Motivo: ' + motivo if motivo else ''}"}]})
        return f'🔒 #{canal["name"]} trancado.'
    await _sobrescrever(canal, gid, 0, herdar=bits, motivo=motivo or "Canal destrancado pelo agente")
    await dc("POST", f'/channels/{canal["id"]}/messages', corpo={
        "embeds": [{"color": COR_PADRAO, "description": "🔓 Canal destrancado."}]})
    return f'🔓 #{canal["name"]} destrancado.'


# Importados no fim: estes módulos também usam este aqui (evita import circular).
from ..busca import _canais, _link_canal, _sobrescrever, achar_alvo_permissao, achar_canal, achar_cargo, achar_categoria
from ..config import COR_PADRAO, NOME_CANAL_CONFIG
from ..discord_api import ErroDiscord, dc
from ..memoria import _cfg_estado, registrar
from ..util import (
    CONECTAR,
    CORES,
    ENVIAR,
    FALAR,
    HISTORICO,
    PERMISSOES,
    TIPOS,
    TIPOS_CRIAR,
    VER,
    _bits,
    _nomes_perm,
    _norm,
    eu,
    servidor_id,
)
