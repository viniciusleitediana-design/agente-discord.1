"""Encontrar canais, cargos e membros por ID, menção ou nome."""

from typing import Any

async def _canais() -> list[dict]:
    return await dc("GET", f"/guilds/{await servidor_id()}/channels")


async def _cargos() -> list[dict]:
    return await dc("GET", f"/guilds/{await servidor_id()}/roles")


def _escolher(ref: Any, itens: list[dict], rotulo: str, mostrar) -> dict:
    alvo = _norm(ref)
    if not alvo:
        raise ErroDiscord(f'Não entendi qual {rotulo} é "{ref}". Use o ID.')
    exatos = [i for i in itens if _norm(i["name"]) == alvo]
    if len(exatos) == 1:
        return exatos[0]
    if len(exatos) > 1:
        raise ErroDiscord(f'Há mais de um {rotulo} chamado "{ref}": ' + ", ".join(mostrar(i) for i in exatos[:10]) + ". Use o ID.")
    parciais = [i for i in itens if alvo in _norm(i["name"])]
    if len(parciais) == 1:
        return parciais[0]
    if parciais:
        raise ErroDiscord(f'"{ref}" combina com vários: ' + ", ".join(mostrar(i) for i in parciais[:10]) + ". Use o ID.")
    raise ErroDiscord(f'Não achei {rotulo} "{ref}".')


async def achar_canal(ref: Any, tipos: set[int] | None = None) -> dict:
    if ref is None or str(ref).strip() == "":
        raise ErroDiscord("Informe o canal (ID, #menção ou nome).")
    lista = await _canais()
    cid = _id(ref)
    if cid:
        for c in lista:
            if c["id"] == cid:
                return c
        return await dc("GET", f"/channels/{cid}")  # threads não aparecem na lista
    candidatos = [c for c in lista if tipos is None or c["type"] in tipos]
    try:
        return _escolher(ref, candidatos, "canal", lambda c: f'#{c["name"]} ({c["id"]})')
    except ErroDiscord as erro:
        if "Não achei" in str(erro):
            raise ErroDiscord(f'Não achei o canal "{ref}". Use listar_canais para ver nomes e IDs.')
        raise


async def achar_categoria(ref: Any) -> dict:
    return await achar_canal(ref, tipos={4})


async def achar_cargo(ref: Any) -> dict:
    gid = await servidor_id()
    lista = await _cargos()
    s = str(ref).strip()
    if s in ("@everyone", "everyone") or _norm(s) in ("everyone", "todos", "todomundo"):
        return next(c for c in lista if c["id"] == gid)
    rid = _id(s)
    if rid:
        for c in lista:
            if c["id"] == rid:
                return c
        raise ErroDiscord(f"Cargo com ID {rid} não existe.")
    try:
        return _escolher(s.lstrip("@"), lista, "cargo", lambda c: f'@{c["name"]} ({c["id"]})')
    except ErroDiscord as erro:
        if "Não achei" in str(erro):
            raise ErroDiscord(f'Não achei o cargo "{ref}". Use listar_cargos para ver nomes e IDs.')
        raise


async def achar_membro(ref: Any) -> dict:
    gid = await servidor_id()
    uid = _id(ref)
    if uid:
        return await dc("GET", f"/guilds/{gid}/members/{uid}")
    consulta = str(ref).strip().lstrip("@")
    if not consulta:
        raise ErroDiscord("Informe o membro (ID, @menção ou nome).")
    achados = await dc("GET", f"/guilds/{gid}/members/search", params={"query": consulta[:100], "limit": 10})
    if not achados:
        raise ErroDiscord(f'Não achei ninguém chamado "{consulta}" (a busca usa o começo do nome de usuário ou apelido). Tente o ID.')
    alvo = _norm(consulta)
    exatos = [m for m in achados if alvo in (_norm(m["user"]["username"]), _norm(m["user"].get("global_name") or ""), _norm(m.get("nick") or ""))]
    if len(exatos) == 1:
        return exatos[0]
    if len(achados) == 1:
        return achados[0]
    raise ErroDiscord("Encontrei várias pessoas: " + ", ".join(f'{_nome_membro(m)} (@{m["user"]["username"]}, ID {m["user"]["id"]})' for m in achados) + ". Diga qual pelo ID.")


async def achar_alvo_permissao(ref: Any) -> tuple[str, int, str]:
    """Cargo (tipo 0) ou membro (tipo 1)."""
    try:
        cargo = await achar_cargo(ref)
        return cargo["id"], 0, f'@{cargo["name"]}'
    except ErroDiscord:
        membro = await achar_membro(ref)
        return membro["user"]["id"], 1, _nome_membro(membro)


async def _sobrescrever(canal: dict, alvo_id: str, tipo: int, permitir: int = 0, negar: int = 0,
                        herdar: int = 0, motivo: str | None = None) -> tuple[int, int]:
    atual = next((o for o in canal.get("permission_overwrites", []) if o["id"] == alvo_id), None)
    allow = int(atual["allow"]) if atual else 0
    deny = int(atual["deny"]) if atual else 0
    allow = (allow | permitir) & ~negar & ~herdar
    deny = (deny | negar) & ~permitir & ~herdar
    if allow == 0 and deny == 0:
        if atual:
            await dc("DELETE", f'/channels/{canal["id"]}/permissions/{alvo_id}', motivo=motivo)
    else:
        await dc("PUT", f'/channels/{canal["id"]}/permissions/{alvo_id}',
                 corpo={"allow": str(allow), "deny": str(deny), "type": tipo}, motivo=motivo)
    return allow, deny


def _link_canal(gid: str, cid: str, mid: str | None = None) -> str:
    return f"https://discord.com/channels/{gid}/{cid}" + (f"/{mid}" if mid else "")


async def _canal_existe(canal_id: str) -> bool:
    try:
        await dc("GET", f"/channels/{canal_id}")
        return True
    except ErroDiscord as erro:
        if erro.status == 404 or erro.codigo == 10003:
            return False
        return True


# Importados no fim: estes módulos também usam este aqui (evita import circular).
from .discord_api import ErroDiscord, dc
from .util import _id, _nome_membro, _norm, servidor_id
