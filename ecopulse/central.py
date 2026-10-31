"""Central da equipe: fila de atendimento ao vivo e alertas num canal só."""

import asyncio
import hashlib
import json
import time
from datetime import datetime, timedelta
from typing import Any

from . import estado

# CENTRAL DA EQUIPE: fila de atendimento ao vivo + alertas num canal só
# O bot acha os canais pelo nome: "fila-de-atendimento" e "alertas". Sem eles, tudo funciona como antes
# (a equipe é mencionada dentro de cada canal).

_central: dict[str, Any] = {"fila": None, "alertas": None, "lido": 0.0, "msg": None, "msg_canal": None, "assinatura": None}
LIMITE_ITENS_SECAO = 10
TRAVADA_APOS = timedelta(minutes=3)


async def _canais_central(forcar: bool = False) -> tuple[str | None, str | None]:
    if forcar or time.time() - _central["lido"] > 300:
        try:
            canais = await _canais()
        except ErroDiscord:
            return _central["fila"], _central["alertas"]
        texto = [c for c in canais if c["type"] in (0, 5)]
        _central["fila"] = next((c["id"] for c in texto if "filadeatendimento" in _norm(c["name"])), None)
        _central["alertas"] = next((c["id"] for c in texto if _norm(c["name"]).endswith("alertas")), None)
        _central["lido"] = time.time()
    return _central["fila"], _central["alertas"]


async def tem_canal_alertas() -> bool:
    return bool((await _canais_central())[1])


async def alertar_equipe(texto: str, cargos: list[str] | None = None) -> bool:
    """Avisa a equipe no canal de alertas, mencionando o FUNDADOR (e os cargos passados).
    Devolve False se não há canal de alertas: aí quem chamou menciona a equipe no próprio canal, como antes."""
    _, canal = await _canais_central()
    if not canal:
        return False
    fund = _cfg_vendas("cargo_fundador_id") if estado._db is not None else None
    ids = list(dict.fromkeys(x for x in [fund, *(cargos or [])] if x))
    try:
        await dc("POST", f"/channels/{canal}/messages", corpo={
            "content": ((" ".join(f"<@&{x}>" for x in ids) + " ") if ids else "") + texto[:1800],
            "allowed_mentions": {"parse": [], "roles": ids}})
    except ErroDiscord as erro:
        log.warning("Não consegui mandar o alerta para a equipe: %s", erro)
        if erro.status == 404 or erro.codigo == 10003:
            _central["lido"] = 0
        return False
    _fila_depois()
    return True


def _rel(iso: str | None) -> str:
    if not iso:
        return "agora"
    try:
        return f"<t:{int(datetime.fromisoformat(iso).timestamp())}:R>"
    except ValueError:
        return "?"


def _montar_fila() -> list[dict]:
    conferir, sem_dono, sem_estoque, travadas, em_atendimento = [], [], [], [], []
    esperando_pix = 0
    agora = _agora()
    if estado._db is not None and _vendas["pronto"]:
        for p in _q(f"SELECT * FROM pedidos WHERE status IN ({','.join('?' * 5)})",
                    (AG_CONFERENCIA, AG_ESTOQUE, APROVADO, ENTREGANDO, AG_PAGAMENTO)):
            if p["status"] == AG_PAGAMENTO:
                esperando_pix += 1
                continue
            j = _jogo(p["jogo"])
            base = (f'`{p["id"]}` {_rotulo_jogo(j)} • {p["produto_nome"]} • **{_reais_c(p["preco_centavos"])}** • '
                    f'<@{p["usuario_id"]}>')
            if p["status"] == AG_CONFERENCIA:
                quando = p["informado_em"] or p["criado_em"]
                conferir.append((quando, f'{base} • pagou {_rel(quando)} → <#{p["canal_pagamento_id"]}>'))
            elif p["status"] == AG_ESTOQUE:
                sem_estoque.append((p["aprovado_em"] or "", f'{base} • aprovado {_rel(p["aprovado_em"])} • `/key_adicionar`'))
            else:
                desde = p["entregando_desde"] or p["aprovado_em"]
                if desde and agora - datetime.fromisoformat(desde) > TRAVADA_APOS:
                    onde = f' → <#{p["canal_pagamento_id"]}>' if p["canal_pagamento_id"] and not p["pagamento_apagado"] else ""
                    travadas.append((desde, f'{base} • desde {_rel(desde)}{onde}'))
    for cid, c in _cfg.get("compras", {}).items():
        if c.get("status") == "aguardando":
            esperando_pix += 1
        elif c.get("status") == "analise":
            nome = (_cfg.get("produtos", {}).get(c.get("produto"), {}) or {}).get("nome") or c.get("produto")
            quando = c.get("informado") or c.get("criado")
            conferir.append((quando or "", f'{nome} • **{_reais(c.get("valor"))}** • <@{c["comprador"]}> • '
                                           f'pagou {_rel(quando)} → <#{cid}>'))
    for cid, t in _cfg.get("tickets", {}).items():
        if t.get("status") != "aberto":
            continue
        linha = (f'#{int(t.get("numero") or 0):04d} • <@{t["dono"]}>' + (f' • {t["motivo"]}' if t.get("motivo") else "")
                 + f' • aberto {_rel(t.get("aberto"))} → <#{cid}>')
        if t.get("assumido_por"):
            em_atendimento.append((t.get("aberto") or "", f'{linha} • 🙋 <@{t["assumido_por"]}>'))
        else:
            sem_dono.append((t.get("aberto") or "", linha))
    secoes = [("💰 PAGAMENTOS PARA CONFERIR", conferir, CORES["amarelo"],
               "Confira o Pix no banco e aprove ou rejeite no canal do pedido."),
              ("🎫 TICKETS SEM RESPONSÁVEL", sem_dono, CORES["azul"], "Abra o ticket e clique em 🙋 **Assumir**."),
              ("📦 APROVADOS SEM ESTOQUE", sem_estoque, CORES["laranja"],
               "Cadastre keys desse plano: a entrega sai sozinha."),
              ("⚠️ ENTREGAS TRAVADAS", travadas, CORES["vermelho"],
               "Abra o canal de pagamento e clique em 🔁 **Tentar entregar de novo**."),
              ("🙋 TICKETS EM ATENDIMENTO", em_atendimento, CORES["cinza"], None)]
    precisam = len(conferir) + len(sem_dono) + len(sem_estoque) + len(travadas)
    mais_antigo = min((q for lista in (conferir, sem_dono, sem_estoque, travadas) for q, _ in lista if q), default=None)
    atrasado = bool(mais_antigo) and agora - datetime.fromisoformat(mais_antigo) > timedelta(minutes=30)
    if precisam:
        topo = (f"🔴 **{precisam}** {'precisa' if precisam == 1 else 'precisam'} de resposta"
                + (f" • o mais antigo chegou {_rel(mais_antigo)}" if mais_antigo else "")
                + (f"\n💬 {len(em_atendimento)} ticket(s) em atendimento" if em_atendimento else "")
                + (f"\n🕐 {esperando_pix} pedido(s) esperando o cliente pagar" if esperando_pix else ""))
    else:
        topo = ("✅ **Tudo em dia!** Ninguém esperando resposta."
                + (f"\n💬 {len(em_atendimento)} ticket(s) em atendimento" if em_atendimento else "")
                + (f"\n🕐 {esperando_pix} pedido(s) esperando o cliente pagar" if esperando_pix else ""))
    embeds = [{"title": "📋 FILA DE ATENDIMENTO", "color": CORES["vermelho"] if atrasado else (CORES["amarelo"] if precisam else NEON),
               "description": topo + "\n\nOs mais antigos aparecem primeiro. Clique no canal para responder.",
               "footer": {"text": "Atualiza sozinho • os alertas novos chegam em 🔔・alertas"}}]
    blocos = []
    for titulo, itens, cor, dica in secoes:
        if not itens:
            continue
        itens = sorted(itens, key=lambda x: x[0])
        linhas = [f"**{i}.** {txt}" for i, (_, txt) in enumerate(itens[:LIMITE_ITENS_SECAO], 1)]
        resto = len(itens) - len(linhas)
        blocos.append([f"{titulo} ({len(itens)})", linhas, resto, cor, dica])
    # o Discord aceita no máximo 6000 caracteres somando todos os embeds de uma mensagem
    while sum(len(b[0]) + sum(len(x) + 1 for x in b[1]) + len(b[4] or "") + 40 for b in blocos) + len(topo) + 200 > 5800:
        maior = max(blocos, key=lambda b: len(b[1]))
        if len(maior[1]) <= 1:
            break
        maior[1].pop()
        maior[2] += 1
    for titulo, linhas, resto, cor, dica in blocos:
        texto = "\n".join(linhas) + (f"\n… e mais **{resto}**" if resto else "") + (f"\n\n💡 *{dica}*" if dica else "")
        embeds.append({"title": titulo, "color": cor, "description": texto[:4096]})
    return embeds


async def atualizar_fila(forcar: bool = False) -> None:
    fila, _ = await _canais_central()
    if not fila:
        return
    payload = {"embeds": _montar_fila(), "allowed_mentions": {"parse": []}}
    assinatura = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    if not forcar and assinatura == _central["assinatura"] and _central["msg_canal"] == fila:
        return
    for tentativa in range(2):
        msg_id = _central["msg"] if _central["msg_canal"] == fila else None
        if not msg_id:
            bot = (await eu())["id"]
            recentes = await dc("GET", f"/channels/{fila}/messages", params={"limit": 30})
            achada = next((m for m in recentes if m["author"]["id"] == bot and m.get("embeds")
                           and (m["embeds"][0].get("title") or "").startswith("📋 FILA")), None)
            msg_id = achada["id"] if achada else None
        try:
            if msg_id:
                await dc("PATCH", f"/channels/{fila}/messages/{msg_id}", corpo=payload)
            else:
                msg_id = (await dc("POST", f"/channels/{fila}/messages", corpo=payload))["id"]
            break
        except ErroDiscord as erro:
            _central.update(msg=None, msg_canal=None, assinatura=None)
            if erro.codigo == 10008 and tentativa == 0:
                continue  # apagaram a mensagem da fila: publica de novo agora
            if erro.status == 404 or erro.codigo in (10003, 10008):
                if erro.codigo == 10003:
                    _central["lido"] = 0
                return
            raise
    _central.update(msg=msg_id, msg_canal=fila, assinatura=assinatura)


def _fila_depois(segundos: float = 2) -> None:
    """Atualiza a fila logo depois de uma mudança (agrupa várias mudanças seguidas numa edição só)."""
    if estado._tarefa_fila and not estado._tarefa_fila.done():
        return

    async def _rodar():
        await asyncio.sleep(segundos)
        try:
            await atualizar_fila()
        except Exception:
            log.exception("Falha ao atualizar a fila de atendimento")

    try:
        estado._tarefa_fila = asyncio.get_running_loop().create_task(_rodar())
    except RuntimeError:
        pass


# Importados no fim: estes módulos também usam este aqui (evita import circular).
from .busca import _canais
from .config import log
from .discord_api import ErroDiscord, dc
from .memoria import _cfg
from .util import CORES, _agora, _norm, _reais, eu
from .vendas.banco import _cfg_vendas, _jogo, _q, _reais_c, _rotulo_jogo
from .vendas.base import AG_CONFERENCIA, AG_ESTOQUE, AG_PAGAMENTO, APROVADO, ENTREGANDO, NEON, _vendas
