"""Canais privados de pagamento e de entrega (com categorias que giram ao encher)."""

from typing import Any

# ── canais privados (pagamento e entrega) ──

async def _categoria_rotativa(prefixo: str) -> str | None:
    """Categoria privada com espaço (o Discord limita 50 canais por categoria); cria 'PREFIXO 2', 'PREFIXO 3'…"""
    canais = await _canais()
    cats = sorted([c for c in canais if c["type"] == 4 and c["name"].startswith(prefixo)], key=lambda c: c["position"])
    for cat in cats:
        if sum(1 for c in canais if c.get("parent_id") == cat["id"]) < 48:
            return cat["id"]
    gid, bot = await servidor_id(), await eu()
    perms = [{"id": gid, "type": 0, "allow": "0", "deny": str(VER)},
             {"id": bot["id"], "type": 1, "allow": str(VER | ENVIAR | HISTORICO), "deny": "0"}]
    fund = _cfg_vendas("cargo_fundador_id")
    if fund:
        perms.append({"id": fund, "type": 0, "allow": str(VER | HISTORICO), "deny": "0"})
    nome = prefixo if not cats else f"{prefixo} {len(cats) + 1}"
    return (await dc("POST", f"/guilds/{gid}/channels", corpo={"name": nome, "type": 4, "permission_overwrites": perms},
                     motivo="Vendas ECO CHEATS"))["id"]


async def _canal_privado_venda(prefixo_nome: str, usuario_id: str, nome_pessoa: str, pedido_id: str, categoria_prefixo: str,
                               topico: str, cliente_escreve: bool = True) -> dict:
    gid, bot = await servidor_id(), await eu()
    fund = _cfg_vendas("cargo_fundador_id")
    acesso_cliente = VER | HISTORICO | (ENVIAR | ANEXAR if cliente_escreve else 0)
    perms: list[dict[str, Any]] = [
        {"id": gid, "type": 0, "allow": "0", "deny": str(VER)},
        {"id": usuario_id, "type": 1, "allow": str(acesso_cliente), "deny": "0" if cliente_escreve else str(ENVIAR)},
        {"id": bot["id"], "type": 1, "allow": str(VER | ENVIAR | HISTORICO | ANEXAR | EMBED_LINKS | GERENCIAR_MSG), "deny": "0"},
    ]
    if fund:
        perms.append({"id": fund, "type": 0, "allow": str(VER | ENVIAR | HISTORICO | ANEXAR | GERENCIAR_MSG), "deny": "0"})
    base = f'{prefixo_nome}-{_slug(nome_pessoa, 28) or "cliente"}'[:90].strip("-")
    existentes = {c["name"] for c in await _canais()}
    nome = base if base not in existentes else f"{base}-{pedido_id[-4:].lower()}"
    return await _criar_canal_privado(nome, perms, await _categoria_rotativa(categoria_prefixo), topico, f"Pedido {pedido_id}")


# Importados no fim: estes módulos também usam este aqui (evita import circular).
from ..busca import _canais
from ..discord_api import dc
from ..loja import EMBED_LINKS, GERENCIAR_MSG
from ..paineis import _criar_canal_privado
from ..util import ANEXAR, ENVIAR, HISTORICO, VER, _slug, eu, servidor_id
from .banco import _cfg_vendas
