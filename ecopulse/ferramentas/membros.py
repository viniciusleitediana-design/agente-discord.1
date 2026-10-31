"""Ferramentas do conector: membros e moderação."""

from datetime import datetime, timedelta
from typing import Any

from ..conector import DESTRUTIVA, LEITURA, mcp

# ── membros e moderação ──

@mcp.tool(annotations=LEITURA)
async def listar_membros(limite: int = 100, cargo: str | None = None) -> dict:
    """Lista membros do servidor (até 1000), opcionalmente só os de um cargo."""
    gid = await servidor_id()
    cargos = {c["id"]: c["name"] for c in await _cargos()}
    filtro = (await achar_cargo(cargo))["id"] if cargo else None
    limite = max(1, min(1000, limite))
    membros: list[dict] = []
    depois = "0"
    try:
        while len(membros) < limite:
            lote = await dc("GET", f"/guilds/{gid}/members", params={"limit": 1000, "after": depois})
            if not lote:
                break
            for m in lote:
                if filtro and filtro not in m.get("roles", []):
                    continue
                membros.append(m)
            depois = lote[-1]["user"]["id"]
            if len(lote) < 1000:
                break
    except ErroDiscord as erro:
        if erro.codigo == 50001 or erro.status == 403:
            raise ErroDiscord("Para listar membros, ative SERVER MEMBERS INTENT no Developer Portal → Bot.")
        raise
    saida = [{"id": m["user"]["id"], "nome": _nome_membro(m), "usuario": m["user"]["username"],
              **({"bot": True} if m["user"].get("bot") else {}),
              "cargos": [cargos.get(r, r) for r in m.get("roles", [])], "entrou": _fmt(m.get("joined_at"))}
             for m in membros[:limite]]
    return {"quantidade": len(saida), "membros": saida}


@mcp.tool(annotations=LEITURA)
async def info_membro(membro: str) -> dict:
    """Mostra dados de um membro: nome, cargos, quando entrou, conta criada e se está de castigo."""
    m = await achar_membro(membro)
    cargos = {c["id"]: c["name"] for c in await _cargos()}
    u = m["user"]
    info: dict[str, Any] = {"id": u["id"], "usuario": u["username"], "nome_exibido": _nome_membro(m),
                            "apelido": m.get("nick"), "bot": u.get("bot", False),
                            "cargos": [cargos.get(r, r) for r in m.get("roles", [])],
                            "entrou_no_servidor": _fmt(m.get("joined_at")), "conta_criada": _fmt(_data_snowflake(u["id"]))}
    ate = m.get("communication_disabled_until")
    if ate and datetime.fromisoformat(ate.replace("Z", "+00:00")) > _agora():
        info["de_castigo_ate"] = _fmt(ate)
    return info


@mcp.tool()
async def mudar_apelido(membro: str, apelido: str | None = None) -> str:
    """Muda o apelido de um membro no servidor (vazio volta ao nome normal)."""
    gid = await servidor_id()
    m = await achar_membro(membro)
    await dc("PATCH", f'/guilds/{gid}/members/{m["user"]["id"]}', corpo={"nick": apelido or None}, motivo="Agente ECO PULSE")
    return f'✅ Apelido de @{m["user"]["username"]} {"agora é " + apelido if apelido else "removido"}.'


@mcp.tool()
async def castigar(membro: str, minutos: int, motivo: str | None = None) -> str:
    """Deixa um membro de castigo (timeout: não fala nem reage) por X minutos (máx. 40320 = 28 dias).
    minutos=0 tira o castigo."""
    gid = await servidor_id()
    m = await achar_membro(membro)
    minutos = max(0, min(40320, int(minutos)))
    ate = (_agora() + timedelta(minutes=minutos)).isoformat() if minutos else None
    await dc("PATCH", f'/guilds/{gid}/members/{m["user"]["id"]}', corpo={"communication_disabled_until": ate},
             motivo=motivo or "Agente ECO PULSE")
    if minutos:
        await registrar(f'🔇 O agente deixou <@{m["user"]["id"]}> de castigo por {minutos} min.{" Motivo: " + motivo if motivo else ""}')
        return f"🔇 {_nome_membro(m)} de castigo até {_fmt(ate)}."
    await registrar(f'🔈 O agente tirou o castigo de <@{m["user"]["id"]}>.')
    return f"🔈 Castigo de {_nome_membro(m)} removido."


@mcp.tool(annotations=DESTRUTIVA)
async def expulsar(membro: str, motivo: str | None = None, confirmado: bool = False) -> str:
    """Expulsa um membro (ele pode voltar com convite). Só chame com confirmado=true depois que o usuário confirmar."""
    gid = await servidor_id()
    m = await achar_membro(membro)
    rotulo = f'{_nome_membro(m)} (@{m["user"]["username"]}, ID {m["user"]["id"]})'
    if not confirmado:
        return f"⚠️ Ninguém foi expulso. Confirme com o usuário que ele quer expulsar {rotulo}. Depois chame com confirmado=true."
    await dc("DELETE", f'/guilds/{gid}/members/{m["user"]["id"]}', motivo=motivo or "Agente ECO PULSE")
    await registrar(f"👢 O agente expulsou **{rotulo}**.{' Motivo: ' + motivo if motivo else ''}")
    return f"👢 {rotulo} expulso."


@mcp.tool(annotations=DESTRUTIVA)
async def banir(membro: str, motivo: str | None = None, apagar_mensagens_horas: int = 0, confirmado: bool = False) -> str:
    """Bane um membro (ou um ID de usuário). apagar_mensagens_horas apaga as mensagens dele das últimas X
    horas (máx. 168). Só chame com confirmado=true depois que o usuário confirmar."""
    gid = await servidor_id()
    uid = _id(membro)
    if uid:
        rotulo = f"o usuário {uid}"
        try:
            m = await dc("GET", f"/guilds/{gid}/members/{uid}")
            rotulo = f'{_nome_membro(m)} (@{m["user"]["username"]}, ID {uid})'
        except ErroDiscord:
            pass
    else:
        m = await achar_membro(membro)
        uid = m["user"]["id"]
        rotulo = f'{_nome_membro(m)} (@{m["user"]["username"]}, ID {uid})'
    if not confirmado:
        return f"⚠️ Ninguém foi banido. Confirme com o usuário que ele quer banir {rotulo}. Depois chame com confirmado=true."
    segundos = max(0, min(168, int(apagar_mensagens_horas))) * 3600
    await dc("PUT", f"/guilds/{gid}/bans/{uid}", corpo={"delete_message_seconds": segundos}, motivo=motivo or "Agente ECO PULSE")
    await registrar(f"🔨 O agente baniu **{rotulo}**.{' Motivo: ' + motivo if motivo else ''}")
    return f"🔨 {rotulo} banido."


@mcp.tool()
async def desbanir(usuario: str) -> str:
    """Tira o banimento de um usuário (ID ou nome de usuário)."""
    gid = await servidor_id()
    uid = _id(usuario)
    if not uid:
        bans = await dc("GET", f"/guilds/{gid}/bans", params={"limit": 1000})
        alvo = _norm(usuario.lstrip("@"))
        achados = [b for b in bans if alvo in (_norm(b["user"]["username"]), _norm(b["user"].get("global_name") or ""))]
        if len(achados) != 1:
            raise ErroDiscord("Não achei exatamente um banido com esse nome. Use o ID." if not achados else
                              "Vários banidos com esse nome: " + ", ".join(f'{b["user"]["username"]} ({b["user"]["id"]})' for b in achados))
        uid = achados[0]["user"]["id"]
    await dc("DELETE", f"/guilds/{gid}/bans/{uid}", motivo="Agente ECO PULSE")
    await registrar(f"♻️ O agente desbaniu <@{uid}>.")
    return f"✅ Usuário {uid} desbanido."


# Importados no fim: estes módulos também usam este aqui (evita import circular).
from ..busca import _cargos, achar_cargo, achar_membro
from ..discord_api import ErroDiscord, dc
from ..memoria import registrar
from ..util import _agora, _data_snowflake, _fmt, _id, _nome_membro, _norm, servidor_id
