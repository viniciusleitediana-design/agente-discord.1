"""Agendador: mensagens programadas e as rotinas que rodam a cada 20 segundos."""

import asyncio
import math
import os
import re
from datetime import datetime, timedelta, timezone

REPETICOES = {"nao": "nao", "naorepetir": "nao", "nenhum": "nao", "nenhuma": "nao", "umavez": "nao", "": "nao",
              "diario": "diario", "diaria": "diario", "tododia": "diario", "todososdias": "diario",
              "semanal": "semanal", "todasemana": "semanal",
              "diasuteis": "dias_uteis", "segasex": "dias_uteis", "segundaasexta": "dias_uteis",
              "minutos": "minutos", "intervalo": "minutos", "acada": "minutos"}
NOMES_REPETICAO = {"nao": "uma vez", "diario": "todo dia", "semanal": "toda semana",
                   "dias_uteis": "de segunda a sexta", "minutos": "a cada {n} min"}


def _ler_quando(texto: str) -> datetime:
    """Entende 'AAAA-MM-DD HH:MM', 'DD/MM HH:MM', 'HH:MM', 'daqui a 30 min' (horário de Brasília)."""
    original = str(texto).strip()
    s = _norm_frase(original)
    agora = datetime.now(FUSO)
    if s in ("agora", "ja", "imediatamente"):
        return agora + timedelta(seconds=5)
    m = re.fullmatch(r"(?:daqui a|daqui|em|\+)?\s*(\d+)\s*(min|mins|minuto|minutos|m|h|hora|horas|d|dia|dias)", s)
    if m:
        n, u = int(m.group(1)), m.group(2)
        delta = timedelta(minutes=n) if u.startswith("m") else timedelta(hours=n) if u.startswith("h") else timedelta(days=n)
        return agora + delta
    m = re.fullmatch(r"(?:hoje\s+)?(?:as\s+)?(\d{1,2})(?::|h)(\d{2})?h?", s)
    if m:
        h, mi = int(m.group(1)), int(m.group(2) or 0)
        if h > 23 or mi > 59:
            raise ErroDiscord(f'Horário "{original}" inválido.')
        alvo = agora.replace(hour=h, minute=mi, second=0, microsecond=0)
        return alvo if alvo > agora else alvo + timedelta(days=1)
    m = re.fullmatch(r"amanha\s+(?:as\s+)?(\d{1,2})(?::|h)(\d{2})?h?", s)
    if m:
        h, mi = int(m.group(1)), int(m.group(2) or 0)
        return (agora + timedelta(days=1)).replace(hour=h, minute=mi, second=0, microsecond=0)
    m = re.fullmatch(r"(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\s+(?:as\s+)?(\d{1,2})(?::|h)(\d{2})?h?", s)
    if m:
        d, mes, ano = int(m.group(1)), int(m.group(2)), m.group(3)
        ano_n = int(ano) + (2000 if ano and len(ano) == 2 else 0) if ano else agora.year
        try:
            alvo = datetime(ano_n, mes, d, int(m.group(4)), int(m.group(5) or 0), tzinfo=FUSO)
        except ValueError:
            raise ErroDiscord(f'Data "{original}" inválida.')
        if not ano and alvo < agora - timedelta(minutes=1):
            alvo = alvo.replace(year=alvo.year + 1)
        return alvo
    try:
        dt = datetime.fromisoformat(original.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=FUSO)
    except ValueError:
        pass
    raise ErroDiscord(f'Não entendi o horário "{original}". Use "AAAA-MM-DD HH:MM", "DD/MM HH:MM", '
                      f'"HH:MM" ou "daqui a 30 min" (horário de Brasília).')


def _proxima(item: dict, depois: datetime) -> datetime | None:
    atual = datetime.fromisoformat(item["proxima"])
    rep = item.get("repetir", "nao")
    if rep == "nao":
        return None
    if rep == "minutos":
        passo = timedelta(minutes=int(item["intervalo_minutos"]))
        n = max(1, math.floor((depois - atual) / passo) + 1)
        return atual + passo * n
    local = atual.astimezone(FUSO)
    for _ in range(4000):
        local = local + timedelta(days=7 if rep == "semanal" else 1)
        if rep == "dias_uteis" and local.weekday() >= 5:
            continue
        if local.astimezone(timezone.utc) > depois:
            return local.astimezone(timezone.utc)
    return None


async def rodar_vencidas() -> None:
    await garantir_config()
    if not _cfg_estado["carregada"]:
        return
    agora = _agora()
    mudou = False
    for item in list(_cfg["agendadas"]):
        prox = datetime.fromisoformat(item["proxima"])
        if prox > agora:
            continue
        if agora - prox <= TOLERANCIA_ATRASO:
            try:
                await _postar(item["canal_id"], item["mensagem"])
                item["envios"] = item.get("envios", 0) + 1
                item["ultimo_envio"] = agora.isoformat()
                item.pop("ultimo_erro", None)
            except ErroDiscord as erro:
                if erro.status == 0 or erro.status >= 500:
                    continue  # falha passageira: tenta de novo na próxima volta
                item["ultimo_erro"] = str(erro)[:300]
                await registrar(f'⚠️ A mensagem agendada **{item.get("nome")}** (`{item["id"]}`) falhou: {erro}')
        else:
            item["puladas"] = item.get("puladas", 0) + 1
        nova = _proxima(item, agora)
        if nova is None:
            _cfg["agendadas"].remove(item)
        else:
            item["proxima"] = nova.isoformat()
        mudou = True
    if mudou:
        await salvar_config()


async def loop_agendador() -> None:
    await asyncio.sleep(3)
    while True:
        try:
            await rodar_vencidas()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Erro no agendador")
        for tarefa, rotulo in ((fechar_compras, "fechar chats de compra"), (rodar_sorteios, "encerrar sorteios"),
                               (limpar_tickets, "fechar tickets"), (fechar_entregas, "fechar canais de entrega"),
                               (rodar_vendas, "cuidar das vendas"), (atualizar_fila, "atualizar a fila da equipe")):
            try:
                await tarefa()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("Erro ao %s", rotulo)
        await asyncio.sleep(20)


async def manter_acordado() -> None:
    url = os.getenv("RENDER_EXTERNAL_URL")
    if not (MANTER_ACORDADO and url):
        return
    while True:
        await asyncio.sleep(600)
        try:
            await cliente_web().get(url.rstrip("/") + "/saude", timeout=20)
        except Exception:
            pass


# Importados no fim: estes módulos também usam este aqui (evita import circular).
from .central import atualizar_fila
from .config import FUSO, MANTER_ACORDADO, TOLERANCIA_ATRASO, log
from .discord_api import ErroDiscord, cliente_web
from .loja import fechar_compras, fechar_entregas
from .memoria import _cfg, _cfg_estado, garantir_config, registrar, salvar_config
from .paineis import _postar
from .sorteios import rodar_sorteios
from .tickets import limpar_tickets
from .util import _agora, _norm_frase
from .vendas.entrega import rodar_vendas
