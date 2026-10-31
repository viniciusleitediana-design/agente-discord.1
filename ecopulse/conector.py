"""Servidor MCP (o conector que o Claude usa) e anotações das ferramentas."""

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from .config import VERSAO

mcp = MCPServer(
    name="ECO PULSE",
    instructions=(
        "Agente do servidor de Discord ECO PULSE. Canais, cargos e membros aceitam ID, menção ou nome. "
        "Horários são de Brasília. Antes de qualquer ação que apaga, expulsa ou bane, confirme com o usuário "
        "e só então chame de novo com confirmado=true. Em boas-vindas e respostas automáticas, os textos "
        "aceitam {usuario} (menciona a pessoa), {nome}, {servidor} e {membros}. "
        "As vendas automáticas de keys (painéis nos 5 canais de jogo, Pix, aprovação só do FUNDADOR, entrega em canal "
        "privado) são operadas pelos comandos de barra no Discord; vendas_status mostra a situação sem expor keys. "
        "As automações rodam no próprio bot, mesmo com o Claude fechado. Para trocar painéis de outro bot "
        "(ticket, verificação, sorteio), leia com ver_mensagem e publique de novo com copiar_de apontando para a mensagem antiga."
    ),
    version=VERSAO,
)

LEITURA = ToolAnnotations(readOnlyHint=True, destructiveHint=False)
DESTRUTIVA = ToolAnnotations(readOnlyHint=False, destructiveHint=True)
