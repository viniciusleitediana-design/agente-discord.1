"""Ferramentas do conector: leitura detalhada de mensagens e canais."""

from typing import Any

from ..conector import LEITURA, mcp

# ── leitura detalhada ──

@mcp.tool(annotations=LEITURA)
async def ver_mensagem(mensagem: str, canal_id: str | None = None) -> dict:
    """Mostra uma mensagem por completo: texto, embeds inteiros (título, descrição, campos, cor, imagens, rodapé),
    botões e menus (texto, emoji e cor de cada um) e anexos. Use para copiar painéis de outros bots.
    mensagem = link da mensagem, "canal_id/mensagem_id" ou só o ID (passando canal_id)."""
    m = await _buscar_mensagem(mensagem, canal_id)
    resultado: dict[str, Any] = {
        "id": m["id"], "canal_id": m["channel_id"], "autor": m["author"].get("global_name") or m["author"]["username"],
        "autor_id": m["author"]["id"], "autor_e_bot": bool(m["author"].get("bot")), "quando": _fmt(m["timestamp"]),
        "texto": m.get("content") or "",
        "embeds": [{**_limpar_embed(e), **({"cor_hex": f'#{e["color"]:06x}'} if e.get("color") is not None else {})}
                   for e in m.get("embeds", [])],
        "botoes_e_menus": _resumo_componentes(m.get("components", [])),
        "anexos": [{"nome": a["filename"], "url": a["url"], "tipo": a.get("content_type")} for a in m.get("attachments", [])],
    }
    if m.get("pinned"):
        resultado["fixada"] = True
    if m["author"]["id"] != (await eu())["id"] and resultado["botoes_e_menus"]:
        resultado["obs"] = ("Os botões desta mensagem pertencem a outro bot e param de funcionar quando ele sai. "
                            "Para trocar, publique um painel novo com copiar_de apontando para esta mensagem.")
    return resultado


@mcp.tool(annotations=LEITURA)
async def info_canal(canal_id: str) -> dict:
    """Detalhes de um canal: tópico, categoria, modo lento e quem pode ver/escrever (permissões por cargo e membro)."""
    canal = await achar_canal(canal_id)
    gid = await servidor_id()
    cargos = {c["id"]: c["name"] for c in await _cargos()}
    info: dict[str, Any] = {"id": canal["id"], "nome": canal["name"], "tipo": TIPOS.get(canal["type"], str(canal["type"]))}
    if canal.get("topic"):
        info["topico"] = canal["topic"]
    if canal.get("parent_id"):
        try:
            info["categoria"] = (await dc("GET", f'/channels/{canal["parent_id"]}'))["name"]
        except ErroDiscord:
            info["categoria"] = canal["parent_id"]
    if canal.get("rate_limit_per_user"):
        info["modo_lento_segundos"] = canal["rate_limit_per_user"]
    regras = []
    for o in canal.get("permission_overwrites", []):
        alvo = "@everyone" if o["id"] == gid else (f'@{cargos.get(o["id"], o["id"])}' if o["type"] == 0 else f'membro <@{o["id"]}>')
        regras.append({"alvo": alvo, "permitido": _nomes_perm(int(o["allow"])), "negado": _nomes_perm(int(o["deny"]))})
    info["permissoes"] = regras or "segue a categoria/servidor"
    return info


# Importados no fim: estes módulos também usam este aqui (evita import circular).
from ..busca import _cargos, achar_canal
from ..discord_api import ErroDiscord, dc
from ..paineis import _buscar_mensagem, _limpar_embed, _resumo_componentes
from ..util import TIPOS, _fmt, _nomes_perm, eu, servidor_id
