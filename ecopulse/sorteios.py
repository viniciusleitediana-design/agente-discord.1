"""Sorteios: participar, sortear na hora certa, ressortear e cancelar."""

import asyncio
import random
from datetime import datetime, timedelta
from typing import Any

from .discord_api import _Resposta

# ── sorteios ──

def _embed_sorteio(s: dict) -> dict:
    fim = _ts(s["fim"])
    linhas = [s["descricao"], ""] if s.get("descricao") else []
    linhas.append(f'🏆 **Prêmio:** {s["premio"]}')
    linhas.append(f'🥇 **Vencedores:** {s["vencedores"]}')
    linhas.append(f'👥 **Participantes:** {len(s.get("participantes", []))}')
    if s.get("cargo_obrigatorio_id"):
        linhas.append(f'🔒 **Requisito:** ter o cargo <@&{s["cargo_obrigatorio_id"]}>')
    if s["status"] == "ativo":
        linhas.append(f"⏰ **Termina:** <t:{fim}:R> (<t:{fim}:f>)")
        rodape = "Clique em Participar para entrar • boa sorte!"
        cor = s.get("cor") or CORES["roxo"]
    elif s["status"] == "cancelado":
        linhas.append("❌ **Sorteio cancelado.**")
        rodape, cor = "Sorteio cancelado", CORES["cinza"]
    else:
        linhas.append(f"⏰ **Encerrado:** <t:{fim}:f>")
        ganh = s.get("ganhadores") or []
        linhas.append("🎊 **Ganhador(es):** " + (", ".join(f"<@{g}>" for g in ganh) if ganh else "ninguém participou"))
        rodape, cor = "Sorteio encerrado", CORES["cinza"]
    embed: dict[str, Any] = {"title": s.get("titulo") or f'🎉 SORTEIO • {s["premio"]}'[:256],
                             "description": "\n".join(linhas)[:4096], "color": cor, "footer": {"text": rodape}}
    if s.get("imagem_url"):
        embed["image"] = {"url": s["imagem_url"]}
    if s.get("miniatura_url"):
        embed["thumbnail"] = {"url": s["miniatura_url"]}
    return embed


def _botoes_sorteio(s: dict) -> dict:
    if s["status"] == "ativo":
        return _linha(_botao_painel(s.get("botao_texto") or "Participar", f'ecos:entrar:{s["id"]}', "verde", s.get("botao_emoji") or "🎉"))
    rotulo = "Sorteio cancelado" if s["status"] == "cancelado" else "Sorteio encerrado"
    return _linha({**_botao(rotulo, f'ecos:fim:{s["id"]}', 2, "🔒"), "disabled": True})


async def _editar_sorteio(s: dict, titulo: str | None, descricao: str | None, cor: str | None,
                          imagem_url: str | None, botao_link: str | None) -> dict:
    """editar_mensagem num sorteio: muda o que fica guardado no sorteio, para a mudança não sumir
    quando alguém clicar em Participar (o bot redesenha o embed a cada inscrição)."""
    if botao_link is not None:
        raise ErroDiscord("O botão do sorteio não pode ser trocado por um link.")
    if all(v is None for v in (titulo, descricao, cor, imagem_url)):
        raise ErroDiscord("Num sorteio, dá para mudar titulo, descricao, cor e imagem_url.")
    if titulo is not None:
        s["titulo"] = titulo[:256] or None
    if descricao is not None:
        if len(descricao) > 3500:
            raise ErroDiscord("A descrição do sorteio passou de 3500 caracteres.")
        s["descricao"] = descricao or None
    if cor is not None:
        s["cor"] = _cor(cor)
    if imagem_url is None:
        await _atualizar_mensagem_sorteio(s)
    else:
        s["imagem_url"] = imagem_url or None
        s.pop("image_arquivo", None)
        msg = await _postar(s["canal_id"], {"embeds": [_embed_sorteio(s)], "components": [_botoes_sorteio(s)], "attachments": []},
                            editar_id=s["mensagem_id"])
        nomes = {a["filename"] for a in msg.get("attachments", [])}
        url = ((msg.get("embeds") or [{}])[0].get("image") or {}).get("url") or ""
        arq = url.split("?")[0].rsplit("/", 1)[-1]
        if arq in nomes:
            s["image_arquivo"] = arq
    await salvar_config()
    mudou = [k for k, v in (("titulo", titulo), ("descricao", descricao), ("cor", cor), ("imagem", imagem_url)) if v is not None]
    return {"ok": True, "mensagem_id": s["mensagem_id"], "sorteio": s["id"], "mudou": mudou}


async def _atualizar_mensagem_sorteio(s: dict) -> None:
    """Reescreve o embed do sorteio mantendo a imagem que foi enviada junto da mensagem."""
    embed = _embed_sorteio(s)
    corpo: dict[str, Any] = {"embeds": [embed], "components": [_botoes_sorteio(s)]}
    try:
        atual = await dc("GET", f'/channels/{s["canal_id"]}/messages/{s["mensagem_id"]}')
    except ErroDiscord as erro:
        log.warning("Mensagem do sorteio %s sumiu: %s", s["id"], erro)
        return
    anexos = atual.get("attachments") or []
    if anexos:
        corpo["attachments"] = [{"id": a["id"]} for a in anexos]
        for k in ("image", "thumbnail"):
            arq = s.get(f"{k}_arquivo")
            if arq and k in embed:
                embed[k] = {"url": f"attachment://{arq}"}
    await dc("PATCH", f'/channels/{s["canal_id"]}/messages/{s["mensagem_id"]}', corpo=corpo)


def _atualizar_sorteio_depois(sid: str, segundos: float = 3) -> None:
    tarefa = _tarefas_sorteio.get(sid)
    if tarefa and not tarefa.done():
        return

    async def _rodar():
        await asyncio.sleep(segundos)
        s = _cfg.get("sorteios", {}).get(sid)
        if s and s["status"] == "ativo":
            try:
                await _atualizar_mensagem_sorteio(s)
            except Exception:
                log.exception("Falha ao atualizar o sorteio %s", sid)

    _tarefas_sorteio[sid] = asyncio.create_task(_rodar())


async def _clique_sorteio(r: _Resposta, acao: str, sid: str) -> None:
    inter = r.inter
    if not _cfg_estado["carregada"]:
        asyncio.create_task(garantir_config())
        await r.efemera("O bot acabou de reiniciar. Tente de novo em alguns segundos.")
        return
    s = _cfg.get("sorteios", {}).get(sid)
    if not s or s["status"] != "ativo" or datetime.fromisoformat(s["fim"]) <= _agora():
        await r.efemera("Este sorteio já foi encerrado.")
        return
    uid = str(inter.user.id)
    participantes: list[str] = s.setdefault("participantes", [])
    if acao == "sair":
        if uid in participantes:
            participantes.remove(uid)
            await r.enviar(7, {"content": "Você saiu do sorteio.", "components": []})
            _atualizar_sorteio_depois(sid)
            _salvar_depois()
        else:
            await r.enviar(7, {"content": "Você não estava participando.", "components": []})
        return
    if uid in participantes:
        await r.enviar(4, {"content": "✅ Você já está participando deste sorteio. Boa sorte!", "flags": 64,
                           "components": [_linha(_botao("Sair do sorteio", f"ecos:sair:{sid}", 4, "🚪"))]})
        return
    req = s.get("cargo_obrigatorio_id")
    if req and req not in _ids_cargos(inter.user):
        await r.efemera(f'Para participar, você precisa ter o cargo **{s.get("cargo_obrigatorio_nome") or "exigido"}**.')
        return
    participantes.append(uid)
    await r.efemera(f'🎉 Você está participando do sorteio de **{s["premio"]}**! O resultado sai <t:{_ts(s["fim"])}:R>. Boa sorte!')
    _atualizar_sorteio_depois(sid)
    _salvar_depois()


async def _sortear(s: dict, quantidade: int, excluir: set[str] | None = None) -> list[str]:
    """Escolhe ganhadores ao acaso entre quem ainda está no servidor."""
    gid = await servidor_id()
    candidatos = [u for u in s.get("participantes", []) if u not in (excluir or set())]
    random.SystemRandom().shuffle(candidatos)
    ganhadores: list[str] = []
    for uid in candidatos:
        if len(ganhadores) >= quantidade:
            break
        try:
            await dc("GET", f"/guilds/{gid}/members/{uid}")
        except ErroDiscord as erro:
            if erro.status == 404 or erro.codigo == 10007:
                continue  # saiu do servidor
            raise
        ganhadores.append(uid)
    return ganhadores


async def _anunciar_ganhadores(s: dict, ganhadores: list[str], novo_sorteio: bool = False) -> None:
    if ganhadores:
        mencoes = ", ".join(f"<@{g}>" for g in ganhadores)
        texto = (f'🎊 {"Novo sorteio! " if novo_sorteio else ""}Parabéns {mencoes}! '
                 f'Você{"s" if len(ganhadores) > 1 else ""} ganhou **{s["premio"]}**! Abra um ticket para receber o prêmio.')
    else:
        texto = f'😕 O sorteio de **{s["premio"]}** terminou sem participantes válidos.'
    await dc("POST", f'/channels/{s["canal_id"]}/messages', corpo={
        "content": texto, "allowed_mentions": {"parse": [], "users": ganhadores},
        "message_reference": {"message_id": s["mensagem_id"], "fail_if_not_exists": False}})


async def finalizar_sorteio(s: dict) -> list[str]:
    s["status"] = "sorteando"
    try:
        ganhadores = await _sortear(s, int(s["vencedores"]))
    except Exception:
        s["status"] = "ativo"
        raise
    s.update(status="encerrado", ganhadores=ganhadores, encerrado=_agora().isoformat())
    if datetime.fromisoformat(s["fim"]) > _agora():
        s["fim"] = _agora().isoformat()
    await salvar_config()
    try:
        await _atualizar_mensagem_sorteio(s)
    except ErroDiscord as erro:
        log.warning("Não consegui atualizar a mensagem do sorteio: %s", erro)
    await _anunciar_ganhadores(s, ganhadores)
    await registrar(f'🎉 Sorteio **{s["premio"]}** encerrado. Ganhador(es): '
                    + (", ".join(f"<@{g}>" for g in ganhadores) or "ninguém"))
    return ganhadores


async def rodar_sorteios() -> None:
    if not _cfg_estado["carregada"]:
        return
    agora = _agora()
    for s in list(_cfg.get("sorteios", {}).values()):
        if s["status"] == "ativo" and datetime.fromisoformat(s["fim"]) <= agora:
            try:
                await finalizar_sorteio(s)
            except Exception:
                log.exception("Falha ao encerrar o sorteio %s", s.get("id"))
    # esquece sorteios encerrados há mais de 30 dias
    velhos = [k for k, s in _cfg.get("sorteios", {}).items()
              if s["status"] in ("encerrado", "cancelado") and datetime.fromisoformat(s["fim"]) < agora - timedelta(days=30)]
    if velhos:
        for k in velhos:
            _cfg["sorteios"].pop(k, None)
        await salvar_config()


# Importados no fim: estes módulos também usam este aqui (evita import circular).
from .config import log
from .discord_api import ErroDiscord, dc
from .interface import _botao, _botao_painel, _linha
from .loja import _ids_cargos
from .memoria import _cfg, _cfg_estado, _salvar_depois, garantir_config, registrar, salvar_config
from .paineis import _postar, _tarefas_sorteio
from .util import CORES, _agora, _cor, _ts, servidor_id
