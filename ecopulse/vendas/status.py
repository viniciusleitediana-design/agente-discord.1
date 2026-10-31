"""Resumo das vendas para o diagnóstico e ferramentas do conector das vendas."""

from ..conector import LEITURA, mcp

def resumo_vendas_status() -> dict:
    if not _vendas["pronto"]:
        return {"pronto": False, "aviso": _vendas["aviso"]}
    return {
        "pronto": True,
        "paineis": {j["id"]: (f'publicado (mensagem {j["mensagem_id"]})' if j["mensagem_id"] else "não publicado")
                    for j in _q("SELECT * FROM jogos ORDER BY ordem")},
        "keys_no_cofre": _q1("SELECT COUNT(*) n FROM keys WHERE status = 'disponivel'")["n"],
        "pedidos_abertos": _q1(f"SELECT COUNT(*) n FROM pedidos WHERE status IN ({','.join('?' * len(STATUS_ABERTOS_VENDA))})",
                               STATUS_ABERTOS_VENDA)["n"],
        "aguardando_conferencia": _q1("SELECT COUNT(*) n FROM pedidos WHERE status = ?", (AG_CONFERENCIA,))["n"],
        "entregues": _q1("SELECT COUNT(*) n FROM pedidos WHERE status = ?", (ENTREGUE,))["n"],
        "cargo_fundador": _cfg_vendas("cargo_fundador_id") or "NÃO CONFIGURADO",
        "chave_cofre": "configurada" if _env("CHAVE_COFRE") else "derivada do token (configure CHAVE_COFRE)",
        "ultimo_backup": _vendas["backup_msg"] or _vendas["restaurado"],
    }


@mcp.tool(annotations=LEITURA)
async def vendas_status() -> dict:
    """Situação das vendas automáticas de keys: painéis, estoque, pedidos abertos e configuração (sem mostrar keys)."""
    res = resumo_vendas_status()
    if res.get("pronto"):
        res["estoque"] = {f'{x["jogo"]}/{x["plano"]}': x["n"] for x in
                          _q("SELECT jogo, plano, COUNT(*) n FROM keys WHERE status = 'disponivel' GROUP BY jogo, plano")}
        res["precos"] = {f'{x["jogo"]}/{x["plano"]}': f'{_reais_c(x["preco_centavos"])}{"" if x["ativo"] else " (fora de venda)"}'
                         for x in _q("SELECT * FROM produtos ORDER BY jogo")}
    return res


@mcp.tool()
async def vendas_publicar_paineis() -> dict:
    """Publica (ou atualiza, sem duplicar) os cinco painéis de venda de keys nos canais dos jogos."""
    if not _vendas["pronto"]:
        await iniciar_vendas()
    if not _vendas["pronto"]:
        raise ErroDiscord(f'Vendas ainda iniciando: {_vendas["aviso"]}')
    return {"paineis": await sincronizar_paineis(criar=True)}


# Importados no fim: estes módulos também usam este aqui (evita import circular).
from ..config import _env
from ..discord_api import ErroDiscord
from .backup import iniciar_vendas
from .banco import _cfg_vendas, _q, _q1, _reais_c
from .base import AG_CONFERENCIA, ENTREGUE, STATUS_ABERTOS_VENDA, _vendas
from .paineis import sincronizar_paineis
