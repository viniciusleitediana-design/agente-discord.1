"""Ferramentas do conector: cargos."""

from typing import Any

from ..conector import DESTRUTIVA, LEITURA, mcp

# ── cargos ──

@mcp.tool(annotations=LEITURA)
async def listar_cargos() -> dict:
    """Lista os cargos do servidor (do mais alto para o mais baixo) com id, cor e principais permissões."""
    gid = await servidor_id()
    saida = []
    for c in sorted(await _cargos(), key=lambda c: -c["position"]):
        perms = int(c["permissions"])
        item: dict[str, Any] = {"id": c["id"], "nome": c["name"], "cor": f'#{c["color"]:06x}' if c["color"] else None,
                                "posicao": c["position"]}
        if perms & PERMISSOES["administrador"]:
            item["administrador"] = True
        if c.get("hoist"):
            item["separado"] = True
        if c.get("mentionable"):
            item["mencionavel"] = True
        if c.get("managed"):
            item["de_bot_ou_integracao"] = True
        if c["id"] == gid:
            item["nome"] = "@everyone"
        saida.append(item)
    return {"cargos": saida}


@mcp.tool()
async def criar_cargo(nome: str, cor: str | None = None, separado: bool = False, mencionavel: bool = False,
                      permissoes: list[str] | None = None) -> dict:
    """Cria um cargo. separado=true mostra os membros separados na lista lateral. permissoes: lista
    (ex.: ["gerenciar_mensagens", "castigar"]); sem passar, usa as permissões padrão."""
    gid = await servidor_id()
    corpo: dict[str, Any] = {"name": nome, "hoist": separado, "mentionable": mencionavel}
    if cor:
        corpo["color"] = _cor(cor)
    if permissoes is not None:
        corpo["permissions"] = str(_bits(permissoes))
    c = await dc("POST", f"/guilds/{gid}/roles", corpo=corpo, motivo="Agente ECO PULSE")
    return {"ok": True, "id": c["id"], "nome": c["name"]}


@mcp.tool()
async def editar_cargo(cargo: str, nome: str | None = None, cor: str | None = None, separado: bool | None = None,
                       mencionavel: bool | None = None, permissoes: list[str] | None = None,
                       adicionar_permissoes: list[str] | None = None, remover_permissoes: list[str] | None = None,
                       posicao: int | None = None) -> dict:
    """Edita um cargo: nome, cor, separado, mencionável, permissões (permissoes substitui todas;
    adicionar_permissoes/remover_permissoes mexem só nas citadas) e posição (maior = mais alto)."""
    gid = await servidor_id()
    c = await achar_cargo(cargo)
    corpo: dict[str, Any] = {}
    if nome is not None:
        corpo["name"] = nome
    if cor is not None:
        corpo["color"] = _cor(cor) or 0
    if separado is not None:
        corpo["hoist"] = separado
    if mencionavel is not None:
        corpo["mentionable"] = mencionavel
    if permissoes is not None or adicionar_permissoes or remover_permissoes:
        base = _bits(permissoes) if permissoes is not None else int(c["permissions"])
        corpo["permissions"] = str((base | _bits(adicionar_permissoes)) & ~_bits(remover_permissoes))
    if corpo:
        c = await dc("PATCH", f'/guilds/{gid}/roles/{c["id"]}', corpo=corpo, motivo="Agente ECO PULSE")
    if posicao is not None:
        await dc("PATCH", f"/guilds/{gid}/roles", corpo=[{"id": c["id"], "position": posicao}], motivo="Agente ECO PULSE")
    if not corpo and posicao is None:
        raise ErroDiscord("Nada para mudar.")
    return {"ok": True, "id": c["id"], "nome": c["name"], "permissoes": _nomes_perm(int(c["permissions"]))}


@mcp.tool(annotations=DESTRUTIVA)
async def apagar_cargo(cargo: str, confirmado: bool = False) -> str:
    """Apaga um cargo. Só chame com confirmado=true depois que o usuário confirmar."""
    gid = await servidor_id()
    c = await achar_cargo(cargo)
    if c["id"] == gid or c.get("managed"):
        raise ErroDiscord("Esse cargo não pode ser apagado.")
    if not confirmado:
        return f'⚠️ Nada foi apagado. Confirme com o usuário que ele quer apagar o cargo @{c["name"]} ({c["id"]}). Depois chame com confirmado=true.'
    await dc("DELETE", f'/guilds/{gid}/roles/{c["id"]}', motivo="Agente ECO PULSE")
    await registrar(f'🗑️ O agente apagou o cargo **@{c["name"]}**.')
    return f'✅ Cargo @{c["name"]} apagado.'


@mcp.tool()
async def dar_cargo(membro: str, cargo: str) -> str:
    """Dá um cargo a um membro."""
    gid = await servidor_id()
    m, c = await achar_membro(membro), await achar_cargo(cargo)
    await dc("PUT", f'/guilds/{gid}/members/{m["user"]["id"]}/roles/{c["id"]}', motivo="Agente ECO PULSE")
    return f'✅ {_nome_membro(m)} agora tem o cargo @{c["name"]}.'


@mcp.tool()
async def tirar_cargo(membro: str, cargo: str) -> str:
    """Tira um cargo de um membro."""
    gid = await servidor_id()
    m, c = await achar_membro(membro), await achar_cargo(cargo)
    await dc("DELETE", f'/guilds/{gid}/members/{m["user"]["id"]}/roles/{c["id"]}', motivo="Agente ECO PULSE")
    return f'✅ Tirei o cargo @{c["name"]} de {_nome_membro(m)}.'


# Importados no fim: estes módulos também usam este aqui (evita import circular).
from ..busca import _cargos, achar_cargo, achar_membro
from ..discord_api import ErroDiscord, dc
from ..memoria import registrar
from ..util import PERMISSOES, _bits, _cor, _nome_membro, _nomes_perm, servidor_id
