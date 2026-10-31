"""Aplicação web: rotas, ciclo de vida (bot + agendador) e ponto de entrada."""

import asyncio
import os
import re
import secrets
from contextlib import asynccontextmanager

import uvicorn
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.responses import FileResponse, JSONResponse, PlainTextResponse
from starlette.routing import Route

from . import estado
from .comandos import COMANDOS, _NOMES_COMANDOS
from .conector import mcp
from .config import CHAVE, PORTA, RAIZ_PROJETO, log
from .vendas.comandos import COMANDOS_VENDAS, _NOMES_VENDAS

COMANDOS.extend(COMANDOS_VENDAS)
_NOMES_COMANDOS.update(_NOMES_VENDAS)


_SEGURANCA = TransportSecuritySettings(enable_dns_rebinding_protection=False)
if not CHAVE:  # sem a chave, o conector fica num endereço impossível de adivinhar (na prática, desligado)
    log.warning("CHAVE_SECRETA não configurada: o conector do Claude está desligado. Crie a variável no Render.")
_PREFIXO = f"/{CHAVE or secrets.token_urlsafe(32)}"
_app_http = mcp.streamable_http_app(streamable_http_path=f"{_PREFIXO}/mcp", stateless_http=True,
                                    transport_security=_SEGURANCA, host="0.0.0.0")
_app_sse = mcp.sse_app(sse_path=f"{_PREFIXO}/sse", message_path=f"{_PREFIXO}/messages/",
                       transport_security=_SEGURANCA, host="0.0.0.0")


async def saude(request):
    return JSONResponse({"ok": True, "agente": "ECO PULSE", "versao": VERSAO, "bot": _bot_estado["status"],
                         "memoria": "ok" if _cfg_estado["carregada"] else "pendente"})


@asynccontextmanager
async def ciclo_de_vida(app):
    async with mcp.session_manager.run():
        tarefas = [asyncio.create_task(loop_agendador()), asyncio.create_task(rodar_bot()),
                   asyncio.create_task(manter_acordado())]
        log.info("Agente ECO PULSE %s no ar (conector %s)", VERSAO, "ligado" if CHAVE else "DESLIGADO: falta CHAVE_SECRETA")
        try:
            yield
        finally:
            for t in tarefas:
                t.cancel()
            await _salvar_pendente()
            if _vendas.get("pronto") and (_vendas.get("sujo") or (estado._tarefa_backup and not estado._tarefa_backup.done())):
                if estado._tarefa_backup and not estado._tarefa_backup.done():
                    estado._tarefa_backup.cancel()
                try:
                    await backup_vendas("desligamento")
                except Exception:
                    log.exception("Backup de desligamento falhou")
            if estado._bot is not None:
                try:
                    await estado._bot.close()
                except Exception:
                    pass
            for c in (estado._api, estado._web):
                if c is not None:
                    await c.aclose()


PASTA_MIDIA = os.path.join(RAIZ_PROJETO, "midia")


async def midia(request):
    """Imagens públicas do servidor (banners), servidas da pasta midia/ do repositório."""
    nome = request.path_params["nome"]
    caminho = os.path.join(PASTA_MIDIA, nome)
    if not re.fullmatch(r"[A-Za-z0-9_-]+\.(png|jpe?g|gif|webp)", nome) or not os.path.isfile(caminho):
        return PlainTextResponse("não encontrado", status_code=404)
    return FileResponse(caminho, headers={"Cache-Control": "public, max-age=86400"})


app = Starlette(routes=[Route("/", saude), Route("/saude", saude), Route("/midia/{nome}", midia),
                        *_app_http.routes, *_app_sse.routes],
                lifespan=ciclo_de_vida)


def main() -> None:
    uvicorn.run(app, host="0.0.0.0", port=PORTA, proxy_headers=True, forwarded_allow_ips="*")


# Importados no fim: estes módulos também usam este aqui (evita import circular).
from .agendamento import loop_agendador, manter_acordado
from .config import VERSAO
from .gateway import _bot_estado, rodar_bot
from .memoria import _cfg_estado, _salvar_pendente
from .vendas.backup import backup_vendas
from .vendas.base import _vendas
