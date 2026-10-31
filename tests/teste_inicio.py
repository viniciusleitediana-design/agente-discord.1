"""Sobe o bot do jeito do Render (só `import server`) e confere que tudo foi carregado.

Não usa o suporte.py de propósito: ele importa todos os módulos e esconderia um módulo esquecido.
"""
import asyncio
import os
import pkgutil
import sys

os.environ.update(DISCORD_TOKEN="x", CHAVE_SECRETA="chave-de-teste")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import server  # noqa: E402,F401
import ecopulse  # noqa: E402
from ecopulse.comandos import COMANDOS  # noqa: E402
from ecopulse.conector import mcp  # noqa: E402

faltando = [m.name for m in pkgutil.walk_packages(ecopulse.__path__, "ecopulse.") if m.name not in sys.modules]
assert not faltando, f"módulos que o server.py não carrega: {faltando}"


async def main():
    nomes = [t.name for t in await mcp.list_tools()]
    assert len(nomes) == 55, f"o conector deveria ter 55 ferramentas, tem {len(nomes)}"
    assert len(COMANDOS) == 16, f"deveriam ser 16 comandos de barra, são {len(COMANDOS)}"
    rotas = {getattr(r, "path", "") for r in server.app.routes}
    assert "/chave-de-teste/mcp" in rotas and "/saude" in rotas and "/midia/{nome}" in rotas, rotas
    print(f"INICIO OK — {len(nomes)} ferramentas, {len(COMANDOS)} comandos, todos os módulos carregados")


asyncio.run(main())
