"""Ferramentas do conector: servidor e diagnóstico."""

import os
import time
from typing import Any

from .. import estado
from ..conector import LEITURA, mcp

# ── servidor ──

@mcp.tool(annotations=LEITURA)
async def info_servidor() -> dict:
    """Resumo do servidor: nome, membros, online, impulsos, quantidade de canais e cargos."""
    gid = await servidor_id()
    g = await dc("GET", f"/guilds/{gid}", params={"with_counts": "true"})
    canais = await _canais()
    return {"id": g["id"], "nome": g["name"], "membros": g.get("approximate_member_count"),
            "online": g.get("approximate_presence_count"), "impulsos": g.get("premium_subscription_count"),
            "nivel_impulso": g.get("premium_tier"), "canais": len([c for c in canais if c["type"] != 4]),
            "categorias": len([c for c in canais if c["type"] == 4]), "cargos": len(g.get("roles", [])),
            "comunidade": "COMMUNITY" in g.get("features", []), "descricao": g.get("description"),
            "canal_regras": g.get("rules_channel_id"), "canal_atualizacoes_comunidade": g.get("public_updates_channel_id"),
            "canal_sistema": g.get("system_channel_id")}


@mcp.tool()
async def criar_convite(canal_id: str | None = None, horas: int = 24, usos: int = 0) -> str:
    """Cria um link de convite. horas=0 nunca expira (máx. 168). usos=0 é ilimitado."""
    if canal_id:
        canal = await achar_canal(canal_id)
    else:
        canal = next((c for c in sorted(await _canais(), key=lambda c: c["position"]) if c["type"] == 0), None)
        if not canal:
            raise ErroDiscord("Não achei canal de texto para o convite.")
    horas = max(0, min(168, int(horas)))
    conv = await dc("POST", f'/channels/{canal["id"]}/invites', corpo={"max_age": horas * 3600, "max_uses": max(0, int(usos)), "unique": True})
    validade = "nunca expira" if horas == 0 else f"vale {horas}h"
    return f'🔗 https://discord.gg/{conv["code"]} (#{canal["name"]}, {validade}, {"usos ilimitados" if not usos else f"{usos} usos"})'


@mcp.tool(annotations=LEITURA)
async def status_agente() -> dict:
    """Diagnóstico do agente: bot em tempo real, memória das automações e avisos de configuração."""
    await garantir_config()
    minutos = int((time.time() - INICIO) / 60)
    status: dict[str, Any] = {
        "versao": VERSAO, "ligado_ha": f"{minutos // 60}h{minutos % 60:02d}min",
        "bot_tempo_real": _bot_estado["status"],
        "eventos_completos": bool(_bot_estado.get("intents_privilegiadas")),
        "memoria_automacoes": "ok" if _cfg_estado["carregada"] else (_cfg_estado["aviso"] or "carregando"),
        "agendadas": len(_cfg["agendadas"]), "respostas_automaticas": len(_cfg["respostas"]),
        "cargos_por_reacao": len(_cfg["cargos_reacao"]),
        "manter_acordado": bool(MANTER_ACORDADO and os.getenv("RENDER_EXTERNAL_URL")),
        "protegido_por_chave": bool(CHAVE),
        "loja": {"pix": "configurado" if (PIX_CHAVE or PIX_COPIA_COLA) else "não configurado",
                 "produtos": len(_cfg.get("produtos", {})), "compras_em_andamento": len(_cfg.get("compras", {})),
                 "canais_de_entrega": len(_cfg.get("entregas", {}))},
        "comunidade": {
            "paineis_ticket": len([p for p in _cfg.get("paineis", {}).values() if p["tipo"] == "ticket"]),
            "tickets_abertos": len(_cfg.get("tickets", {})),
            "paineis_verificacao": len([p for p in _cfg.get("paineis", {}).values() if p["tipo"] == "verificacao"]),
            "sorteios_ativos": len([x for x in _cfg.get("sorteios", {}).values() if x["status"] == "ativo"])},
        "comandos_de_barra": "registrados (" + ", ".join("/" + c["name"] for c in COMANDOS) + ")" if estado._comandos_registrados
                             else "ainda não registrados",
        "vendas_keys": resumo_vendas_status(),
    }
    if _bot_estado.get("servidores"):
        status["servidores_do_bot"] = _bot_estado["servidores"]
    if _bot_estado.get("aviso"):
        status["aviso"] = _bot_estado["aviso"]
    try:
        status["servidor"] = (await dc("GET", f"/guilds/{await servidor_id()}"))["name"]
    except ErroDiscord as erro:
        status["servidor"] = f"erro: {erro}"
    return status


# Importados no fim: estes módulos também usam este aqui (evita import circular).
from ..busca import _canais, achar_canal
from ..comandos import COMANDOS
from ..config import CHAVE, INICIO, MANTER_ACORDADO, PIX_CHAVE, PIX_COPIA_COLA, VERSAO
from ..discord_api import ErroDiscord, dc
from ..gateway import _bot_estado
from ..memoria import _cfg, _cfg_estado, garantir_config
from ..util import servidor_id
from ..vendas.status import resumo_vendas_status
