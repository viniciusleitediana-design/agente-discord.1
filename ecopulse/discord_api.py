"""Acesso à API REST do Discord: erros em português, limite de requisições e respostas a interações."""

import asyncio
from typing import Any
from urllib.parse import quote

import httpx2 as httpx
from mcp.server.mcpserver.exceptions import ToolError

from . import estado

class ErroDiscord(ToolError):
    """Erro com mensagem em português que chega até o Claude."""

    def __init__(self, mensagem: str, status: int = 0, codigo: int = 0):
        super().__init__(mensagem)
        self.status = status
        self.codigo = codigo


ERROS = {
    10003: "Canal não encontrado (ID errado ou canal já apagado).",
    10007: "Essa pessoa não está no servidor.",
    10008: "Mensagem não encontrada (ID errado ou já apagada).",
    10011: "Cargo não encontrado.",
    10013: "Usuário não encontrado.",
    10014: "Emoji desconhecido.",
    10026: "Esse usuário não está banido.",
    30005: "O servidor chegou ao limite de 250 cargos.",
    30013: "O servidor chegou ao limite de 500 canais.",
    50005: "Essa mensagem é de outro usuário ou bot e não pode ser editada. Publique uma nova (dá para usar copiar_de).",
    50001: "O bot não tem acesso a isso (Missing Access). Confira se o cargo do bot consegue ver o canal.",
    50007: "Não deu para mandar DM: a pessoa bloqueou mensagens diretas.",
    50013: ("O bot não tem permissão para isso (Missing Permissions). Dê ao cargo do bot a permissão de "
            "Administrador e arraste o cargo do bot para cima dos cargos que ele vai gerenciar "
            "(Configurações do servidor → Cargos)."),
    50024: "Esse tipo de canal não pode ser usado assim (canal de anúncios exige servidor Comunidade).",
    50034: "Mensagens com mais de 14 dias não podem ser apagadas em massa.",
    50035: "O Discord recusou os dados enviados.",
}


def cliente_api() -> httpx.AsyncClient:
    if estado._api is None:
        estado._api = httpx.AsyncClient(
            base_url=API + "/",
            timeout=30,
            headers={
                "Authorization": f"Bot {TOKEN}",
                "User-Agent": f"DiscordBot (https://github.com/eco-pulse, {VERSAO})",
            },
        )
    return estado._api


def cliente_web() -> httpx.AsyncClient:
    """Cliente sem o token, para baixar anexos e cutucar o próprio serviço."""
    if estado._web is None:
        estado._web = httpx.AsyncClient(timeout=30, follow_redirects=True)
    return estado._web


def _resumir_erros(erros: Any, caminho: str = "") -> list[str]:
    saida: list[str] = []
    if isinstance(erros, dict):
        for chave, valor in erros.items():
            if chave == "_errors" and isinstance(valor, list):
                for item in valor:
                    saida.append(f"{caminho or 'dados'}: {item.get('message', item)}")
            else:
                saida += _resumir_erros(valor, f"{caminho}.{chave}" if caminho else str(chave))
    return saida


async def dc(metodo: str, caminho: str, *, corpo: Any = None, params: dict | None = None,
             dados: dict | None = None, arquivos: dict | None = None, motivo: str | None = None,
             autenticar: bool = True) -> Any:
    """Chama a API REST do Discord, respeitando o limite de requisições.
    autenticar=False é para as rotas de resposta a botões (/interactions e /webhooks), que usam o
    token da própria interação em vez do token do bot."""
    if not TOKEN:
        raise ErroDiscord("O token do bot não está configurado. No Render, crie a variável DISCORD_TOKEN "
                          "com o token do bot (Developer Portal → Bot → Reset Token).")
    headers = {"X-Audit-Log-Reason": quote(motivo[:400], safe="")} if motivo else {}
    resp = None
    for tentativa in range(5):
        try:
            if autenticar:
                resp = await cliente_api().request(metodo, caminho, json=corpo, params=params,
                                                   data=dados, files=arquivos, headers=headers)
            else:
                resp = await cliente_web().request(metodo, API + caminho, json=corpo, params=params,
                                                   data=dados, files=arquivos)
        except httpx.HTTPError as erro:
            if tentativa < 2:
                await asyncio.sleep(1.5)
                continue
            raise ErroDiscord(f"Não consegui falar com o Discord ({type(erro).__name__}). Tente de novo.")
        if resp.status_code == 429:
            try:
                espera = float(resp.json().get("retry_after", 1))
            except Exception:
                espera = 1.0
            await asyncio.sleep(min(espera, 15) + 0.25)
            continue
        if resp.status_code >= 500 and tentativa < 2:
            await asyncio.sleep(1.5)
            continue
        break
    assert resp is not None
    if resp.status_code >= 400:
        try:
            info = resp.json()
        except Exception:
            info = {}
        codigo = info.get("code", 0) if isinstance(info, dict) else 0
        texto_dc = info.get("message", "") if isinstance(info, dict) else ""
        if resp.status_code == 401:
            texto = "O token do bot é inválido. Gere outro no Developer Portal e atualize DISCORD_TOKEN no Render."
        else:
            texto = ERROS.get(codigo) or f"O Discord recusou o pedido ({resp.status_code}: {texto_dc or 'sem detalhes'})."
        if codigo == 50035 and isinstance(info, dict):
            detalhes = "; ".join(_resumir_erros(info.get("errors", {})))[:400]
            if detalhes:
                texto += f" Detalhes: {detalhes}"
        raise ErroDiscord(texto, resp.status_code, codigo)
    if resp.status_code == 204 or not resp.content:
        return None
    return resp.json()


class _Resposta:
    """Responde a um clique de botão/formulário pela API (o Discord dá 3 segundos para a 1ª resposta)."""

    def __init__(self, inter: Any):
        self.inter = inter
        self.feita = False
        self.adiada = False

    async def enviar(self, tipo: int, dados: dict | None = None) -> None:
        corpo: dict[str, Any] = {"type": tipo}
        if dados is not None:
            corpo["data"] = dados
        await dc("POST", f"/interactions/{self.inter.id}/{self.inter.token}/callback", corpo=corpo, autenticar=False)
        self.feita = True

    async def adiar(self) -> None:
        """'Pensando…' só para quem clicou (para tarefas que demoram mais de 3 segundos)."""
        await self.enviar(5, {"flags": 64})
        self.adiada = True

    async def editar_original(self, dados: dict) -> None:
        await dc("PATCH", f"/webhooks/{self.inter.application_id}/{self.inter.token}/messages/@original",
                 corpo=dados, autenticar=False)

    async def efemera(self, texto: str) -> None:
        dados = {"content": texto[:2000], "allowed_mentions": {"parse": []}}
        if self.adiada:
            self.adiada = False
            await self.editar_original(dados)
        elif self.feita:
            await dc("POST", f"/webhooks/{self.inter.application_id}/{self.inter.token}",
                     corpo={**dados, "flags": 64}, autenticar=False)
        else:
            await self.enviar(4, {**dados, "flags": 64})


# Importados no fim: estes módulos também usam este aqui (evita import circular).
from .config import API, TOKEN, VERSAO
