"""Ferramentas do conector: sorteios."""

import secrets
from datetime import timedelta, timezone
from typing import Any

from ..conector import DESTRUTIVA, mcp

# ── sorteios ──

@mcp.tool()
async def criar_sorteio(canal_id: str, premio: str, termina: str, vencedores: int = 1, descricao: str | None = None,
                        titulo: str | None = None, cor: str | None = None, imagem_url: str | None = None,
                        cargo_obrigatorio: str | None = None, mencionar_todos: bool = False,
                        botao_texto: str = "Participar", botao_emoji: str | None = "🎉",
                        copiar_de: str | None = None) -> dict:
    """Cria um sorteio com botão Participar. Quando chega a hora, o bot sorteia sozinho, anuncia e marca os ganhadores
    (mesmo com o Claude fechado). termina: "daqui a 3 dias", "30/10 20:00", "2026-11-05 18:00", "amanhã 20h"
    (horário de Brasília). cargo_obrigatorio = só quem tem o cargo participa. copiar_de = link/ID de outra mensagem
    (ex.: sorteio de outro bot) para reaproveitar título, texto e imagem."""
    await exigir_config()
    canal = await achar_canal(canal_id, tipos=TIPOS_MENSAGEM)
    fim = _ler_quando(termina)
    agora = _agora()
    if fim.astimezone(timezone.utc) <= agora + timedelta(minutes=1):
        raise ErroDiscord(f"O fim do sorteio ({_fmt(fim)}) precisa ser no futuro.")
    if fim.astimezone(timezone.utc) > agora + timedelta(days=60):
        raise ErroDiscord("O sorteio pode durar no máximo 60 dias.")
    vencedores = max(1, min(20, int(vencedores)))
    base: dict[str, Any] = {}
    if copiar_de:
        base, _ = await _montar_painel(copiar_de=copiar_de, titulo=None, descricao=None, cor=None, imagem_url=None,
                                       miniatura_url=None, rodape=None, titulo_padrao="", descricao_padrao="")
    sid = secrets.token_hex(3)
    s: dict[str, Any] = {
        "id": sid, "canal_id": canal["id"], "canal_nome": canal["name"], "premio": premio[:200],
        "titulo": (titulo or base.get("title") or None), "descricao": descricao if descricao is not None else (base.get("description") or None),
        "vencedores": vencedores, "fim": fim.astimezone(timezone.utc).isoformat(), "status": "ativo",
        "participantes": [], "ganhadores": [], "cor": _cor(cor) if cor else base.get("color"),
        "imagem_url": imagem_url or (base.get("image") or {}).get("url"),
        "miniatura_url": (base.get("thumbnail") or {}).get("url"),
        "botao_texto": botao_texto, "botao_emoji": botao_emoji, "criado": agora.isoformat(),
    }
    if s["descricao"] and len(s["descricao"]) > 3500:
        raise ErroDiscord("A descrição do sorteio passou de 3500 caracteres.")
    if cargo_obrigatorio:
        c = await achar_cargo(cargo_obrigatorio)
        s.update(cargo_obrigatorio_id=c["id"], cargo_obrigatorio_nome=c["name"])
    payload: dict[str, Any] = {"embeds": [_embed_sorteio(s)], "components": [_botoes_sorteio(s)],
                               "allowed_mentions": {"parse": ["everyone"] if mencionar_todos else []}}
    if mencionar_todos:
        payload["content"] = "@everyone"
    msg = await _postar(canal["id"], payload)
    s["mensagem_id"] = msg["id"]
    nomes = {a["filename"] for a in msg.get("attachments", [])}
    for k in ("image", "thumbnail"):
        url = ((msg.get("embeds") or [{}])[0].get(k) or {}).get("url") or ""
        arq = url.split("?")[0].rsplit("/", 1)[-1]
        if arq in nomes:
            s[f"{k}_arquivo"] = arq
    _cfg["sorteios"][sid] = s
    await salvar_config()
    return {"ok": True, "sorteio_id": sid, "canal": canal["name"], "premio": s["premio"], "termina": _fmt(fim),
            "vencedores": vencedores, "link": _link_canal(await servidor_id(), canal["id"], msg["id"])}


def _achar_sorteio(sorteio_id: str) -> dict:
    s = _cfg.get("sorteios", {}).get(str(sorteio_id).strip().strip("`"))
    if not s:
        raise ErroDiscord(f"Não achei o sorteio {sorteio_id}. Use listar_automacoes para ver os IDs.")
    return s


@mcp.tool()
async def encerrar_sorteio(sorteio_id: str) -> dict:
    """Termina um sorteio agora: sorteia os ganhadores, anuncia no canal e atualiza a mensagem."""
    await exigir_config()
    s = _achar_sorteio(sorteio_id)
    if s["status"] != "ativo":
        raise ErroDiscord("Esse sorteio não está mais ativo. Para escolher outro ganhador, use sortear_de_novo.")
    ganhadores = await finalizar_sorteio(s)
    return {"ok": True, "premio": s["premio"], "participantes": len(s.get("participantes", [])),
            "ganhadores": [f"<@{g}>" for g in ganhadores] or "ninguém participou"}


@mcp.tool()
async def sortear_de_novo(sorteio_id: str, vencedores: int = 1) -> dict:
    """Escolhe novo(s) ganhador(es) de um sorteio já encerrado (ex.: o ganhador não respondeu), sem repetir os anteriores."""
    await exigir_config()
    s = _achar_sorteio(sorteio_id)
    if s["status"] != "encerrado":
        raise ErroDiscord("Só dá para sortear de novo um sorteio já encerrado.")
    anteriores = set(s.get("ganhadores", [])) | set(s.get("ja_sorteados", []))
    novos = await _sortear(s, max(1, min(20, int(vencedores))), anteriores)
    s["ja_sorteados"] = sorted(anteriores)
    s["ganhadores"] = novos or s.get("ganhadores", [])
    await salvar_config()
    if novos:
        await _atualizar_mensagem_sorteio(s)
    await _anunciar_ganhadores(s, novos, novo_sorteio=True)
    return {"ok": True, "novos_ganhadores": [f"<@{g}>" for g in novos] or "não sobrou ninguém para sortear"}


@mcp.tool(annotations=DESTRUTIVA)
async def cancelar_sorteio(sorteio_id: str, confirmado: bool = False) -> str:
    """Cancela um sorteio ativo sem escolher ganhador. Só chame com confirmado=true depois que o usuário confirmar."""
    await exigir_config()
    s = _achar_sorteio(sorteio_id)
    if s["status"] != "ativo":
        raise ErroDiscord("Esse sorteio não está ativo.")
    if not confirmado:
        return f'⚠️ Nada foi cancelado. Confirme com o usuário que ele quer cancelar o sorteio de "{s["premio"]}" ({len(s.get("participantes", []))} participantes). Depois chame com confirmado=true.'
    s["status"] = "cancelado"
    await salvar_config()
    await _atualizar_mensagem_sorteio(s)
    return f'✅ Sorteio de "{s["premio"]}" cancelado.'


# Importados no fim: estes módulos também usam este aqui (evita import circular).
from ..agendamento import _ler_quando
from ..busca import _link_canal, achar_canal, achar_cargo
from ..discord_api import ErroDiscord
from ..memoria import _cfg, exigir_config, salvar_config
from ..paineis import _montar_painel, _postar
from ..sorteios import (
    _anunciar_ganhadores,
    _atualizar_mensagem_sorteio,
    _botoes_sorteio,
    _embed_sorteio,
    _sortear,
    finalizar_sorteio,
)
from ..util import TIPOS_MENSAGEM, _agora, _cor, _fmt, servidor_id
