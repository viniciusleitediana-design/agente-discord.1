"""
ECO PULSE — Agente do Discord
=============================
Conector MCP que deixa o Claude controlar o servidor ECO PULSE e mantém
automações rodando no próprio bot, 24 horas, mesmo com o Claude fechado.

O que o agente faz
- Canais: listar, criar, editar, apagar, permissões, trancar/destrancar
- Mensagens: enviar (texto, embed e botão de link), editar, apagar, ler,
  limpar em massa, fixar, reagir, enquete e DM
- Automações: mensagens agendadas e repetidas, boas-vindas, despedida,
  respostas automáticas, cargos por reação, canal de registros e filtro de
  palavras/convites (AutoMod nativo do Discord)
- Cargos, membros e moderação: criar/editar/apagar cargos, dar/tirar cargo,
  apelido, castigo, expulsar, banir e desbanir

Variáveis de ambiente (Render → Environment)
- DISCORD_TOKEN    obrigatória: token do bot
- GUILD_ID         opcional: ID do servidor (se o bot só estiver em um, é detectado sozinho)
- CHAVE_SECRETA    opcional: troca o caminho secreto do endereço do conector
                   (https://SEU-APP.onrender.com/CHAVE/mcp). Sem ela, vale o caminho antigo.
- FUSO             opcional: padrão America/Sao_Paulo
- MANTER_ACORDADO  opcional: 1 (padrão) faz o serviço se cutucar a cada 10 min
                   para o plano grátis do Render não dormir
- CONFIG_CANAL_ID  opcional: canal onde as automações ficam salvas
                   (padrão: cria o canal privado #agente-config)

Loja (compra em chat privado com Pix)
- PIX_CHAVE        chave Pix que recebe os pagamentos (e-mail, celular no formato
                   +5511999999999, CPF/CNPJ só números ou chave aleatória). Com ela o
                   bot gera o QR Code e o "copia e cola" com o valor de cada produto.
- PIX_NOME         opcional: nome que aparece no Pix (padrão ECO PULSE, até 25 letras)
- PIX_CIDADE       opcional: cidade do Pix (padrão SAO PAULO, até 15 letras)
- PIX_COPIA_COLA   opcional: código Pix fixo pronto (usado no lugar da PIX_CHAVE;
                   o valor dele não muda com o preço do produto)

Comando de início no Render: python server.py
"""

import asyncio
import io
import json
import logging
import math
import os
import random
import re
import secrets
import time
import unicodedata
from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote
from zoneinfo import ZoneInfo

import httpx2 as httpx
import uvicorn
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

try:  # o gateway (eventos em tempo real) é opcional: sem ele o resto continua funcionando
    import discord
except Exception:  # pragma: no cover
    discord = None

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("eco-pulse")

VERSAO = "2.4"
INICIO = time.time()


# ───────────────────────── configuração ─────────────────────────

def _env(*nomes: str, padrao: str | None = None) -> str | None:
    for nome in nomes:
        valor = os.getenv(nome)
        if valor and valor.strip():
            return valor.strip()
    return padrao


TOKEN = (_env("DISCORD_TOKEN", "DISCORD_BOT_TOKEN", "BOT_TOKEN", "TOKEN", "TOKEN_DISCORD",
                "TOKEN_BOT", "DISCORD_KEY", "DISCORD") or "").removeprefix("Bot ").strip()
GUILD_ID = _env("GUILD_ID", "DISCORD_GUILD_ID", "SERVIDOR_ID", "SERVER_ID", "ID_SERVIDOR",
                "DISCORD_SERVER_ID", "GUILD")
# Mesmo caminho secreto do conector antigo, para o endereço no Claude não mudar.
# Para trocar, crie a variável CHAVE_SECRETA no Render (e atualize o endereço do conector).
CAMINHO_SECRETO_ANTIGO = ""
CHAVE = (_env("CHAVE_SECRETA") or CAMINHO_SECRETO_ANTIGO).strip().strip("/")
FUSO = ZoneInfo(_env("FUSO", padrao="America/Sao_Paulo"))
API = (_env("DISCORD_API", padrao="https://discord.com/api/v10")).rstrip("/")
PORTA = int(_env("PORT", padrao="10000"))
MANTER_ACORDADO = (_env("MANTER_ACORDADO", padrao="1") or "1").lower() not in ("0", "false", "nao", "não", "off")
CONFIG_CANAL_ID = _env("CONFIG_CANAL_ID")
PIX_CHAVE = _env("PIX_CHAVE", "CHAVE_PIX")
PIX_NOME = _env("PIX_NOME", padrao="ECO PULSE")
PIX_CIDADE = _env("PIX_CIDADE", padrao="SAO PAULO")
PIX_COPIA_COLA = _env("PIX_COPIA_COLA")

NOME_CANAL_CONFIG = "agente-config"
ARQUIVO_CONFIG = "agente-config.json"
TOLERANCIA_ATRASO = timedelta(hours=6)   # mensagem agendada atrasada mais que isso é pulada
COR_PADRAO = 0x22C55E                     # verde ECO PULSE


# ───────────────────────── erros e acesso à API ─────────────────────────

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

_api: httpx.AsyncClient | None = None
_web: httpx.AsyncClient | None = None


def cliente_api() -> httpx.AsyncClient:
    global _api
    if _api is None:
        _api = httpx.AsyncClient(
            base_url=API + "/",
            timeout=30,
            headers={
                "Authorization": f"Bot {TOKEN}",
                "User-Agent": f"DiscordBot (https://github.com/eco-pulse, {VERSAO})",
            },
        )
    return _api


def cliente_web() -> httpx.AsyncClient:
    """Cliente sem o token, para baixar anexos e cutucar o próprio serviço."""
    global _web
    if _web is None:
        _web = httpx.AsyncClient(timeout=30, follow_redirects=True)
    return _web


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


# ───────────────────────── utilidades ─────────────────────────

def _norm(texto: Any) -> str:
    """'📢・Anúncios' → 'anuncios' (para achar canais/cargos pelo nome)."""
    s = unicodedata.normalize("NFKD", str(texto)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]", "", s)


def _norm_frase(texto: Any) -> str:
    s = unicodedata.normalize("NFKD", str(texto)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", s).strip()


def _id(ref: Any) -> str | None:
    if ref is None:
        return None
    m = re.fullmatch(r"\s*(?:<(?:#|@!?|@&)(\d{15,22})>|(\d{15,22}))\s*", str(ref))
    return (m.group(1) or m.group(2)) if m else None


def _agora() -> datetime:
    return datetime.now(timezone.utc)


def _data_snowflake(snowflake: str) -> datetime:
    return datetime.fromtimestamp(((int(snowflake) >> 22) + 1420070400000) / 1000, tz=timezone.utc)


DIAS = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"]


def _fmt(dt: datetime | str | None) -> str:
    if not dt:
        return "-"
    if isinstance(dt, str):
        dt = datetime.fromisoformat(dt.replace("Z", "+00:00"))
    local = dt.astimezone(FUSO)
    return f"{DIAS[local.weekday()]} {local:%d/%m/%Y %H:%M}"


def _nome_membro(m: dict) -> str:
    u = m.get("user", m)
    return m.get("nick") or u.get("global_name") or u.get("username") or "?"


_servidor: str | None = GUILD_ID
_servidor_ok = False
_eu: dict | None = None


async def _servidores_do_bot() -> str:
    try:
        lista = await dc("GET", "/users/@me/guilds")
    except ErroDiscord:
        return "não consegui listar"
    return ", ".join(f'{s["name"]} (ID {s["id"]})' for s in lista) or "nenhum"


async def servidor_id() -> str:
    global _servidor, _servidor_ok
    if _servidor and not _servidor_ok:
        try:
            await dc("GET", f"/guilds/{_servidor}")
            _servidor_ok = True
        except ErroDiscord as erro:
            if erro.status in (403, 404):
                raise ErroDiscord(
                    f"O bot não está no servidor {_servidor} (variável GUILD_ID no Render). "
                    f"Servidores em que ele está: {await _servidores_do_bot()}. Convide o bot para o "
                    f"ECO PULSE (Developer Portal → OAuth2 → URL Generator → bot + Administrator) "
                    f"ou corrija GUILD_ID.", erro.status, erro.codigo)
            raise
    if _servidor:
        return _servidor
    servidores = await dc("GET", "/users/@me/guilds")
    if not servidores:
        raise ErroDiscord("O bot não está em nenhum servidor. Convide-o pelo Developer Portal → OAuth2 → URL Generator.")
    if len(servidores) == 1:
        _servidor = servidores[0]["id"]
        return _servidor
    for s in servidores:
        if "ecopulse" in _norm(s["name"]):
            _servidor = s["id"]
            return _servidor
    nomes = ", ".join(f'{s["name"]} ({s["id"]})' for s in servidores)
    raise ErroDiscord(f"O bot está em vários servidores: {nomes}. Coloque o ID do ECO PULSE na variável GUILD_ID no Render.")


async def eu() -> dict:
    global _eu
    if _eu is None:
        _eu = await dc("GET", "/users/@me")
    return _eu


# tipos de canal
TIPOS = {0: "texto", 2: "voz", 4: "categoria", 5: "anuncios", 10: "thread", 11: "thread",
         12: "thread privada", 13: "palco", 15: "forum", 16: "midia"}
TIPOS_CRIAR = {"texto": 0, "text": 0, "voz": 2, "voice": 2, "categoria": 4, "category": 4,
               "anuncios": 5, "anuncio": 5, "news": 5, "palco": 13, "stage": 13,
               "forum": 15, "midia": 16, "media": 16}
TIPOS_MENSAGEM = {0, 2, 5, 10, 11, 12, 13}

# permissões (nome em português → bit do Discord)
PERMISSOES = {
    "criar_convite": 1 << 0, "expulsar": 1 << 1, "banir": 1 << 2, "administrador": 1 << 3,
    "gerenciar_canais": 1 << 4, "gerenciar_servidor": 1 << 5, "reagir": 1 << 6,
    "ver_registro": 1 << 7, "voz_prioritaria": 1 << 8, "transmitir": 1 << 9, "ver_canal": 1 << 10,
    "enviar_mensagens": 1 << 11, "tts": 1 << 12, "gerenciar_mensagens": 1 << 13,
    "inserir_links": 1 << 14, "anexar_arquivos": 1 << 15, "ler_historico": 1 << 16,
    "mencionar_todos": 1 << 17, "emojis_externos": 1 << 18, "conectar": 1 << 20, "falar": 1 << 21,
    "silenciar_membros": 1 << 22, "ensurdecer_membros": 1 << 23, "mover_membros": 1 << 24,
    "usar_deteccao_de_voz": 1 << 25, "mudar_apelido": 1 << 26, "gerenciar_apelidos": 1 << 27,
    "gerenciar_cargos": 1 << 28, "gerenciar_webhooks": 1 << 29, "gerenciar_emojis": 1 << 30,
    "usar_comandos": 1 << 31, "gerenciar_eventos": 1 << 33, "gerenciar_threads": 1 << 34,
    "criar_threads": 1 << 35, "criar_threads_privadas": 1 << 36, "figurinhas_externas": 1 << 37,
    "enviar_em_threads": 1 << 38, "castigar": 1 << 40, "enviar_audio": 1 << 46, "criar_enquetes": 1 << 49,
}
APELIDOS_PERM = {"ver": "ver_canal", "enviar": "enviar_mensagens", "escrever": "enviar_mensagens",
                 "historico": "ler_historico", "admin": "administrador", "links": "inserir_links",
                 "arquivos": "anexar_arquivos", "reacoes": "reagir", "timeout": "castigar"}
VER, ENVIAR, HISTORICO, ANEXAR = PERMISSOES["ver_canal"], PERMISSOES["enviar_mensagens"], PERMISSOES["ler_historico"], PERMISSOES["anexar_arquivos"]
CONECTAR, FALAR = PERMISSOES["conectar"], PERMISSOES["falar"]


def _bits(nomes: list[str] | str | None) -> int:
    if not nomes:
        return 0
    if isinstance(nomes, str):
        nomes = [n for n in re.split(r"[,;]", nomes)]
    total = 0
    for nome in nomes:
        chave = re.sub(r"[\s\-]+", "_", unicodedata.normalize("NFKD", nome).encode("ascii", "ignore").decode().lower().strip())
        if not chave:
            continue
        chave = APELIDOS_PERM.get(chave, chave)
        if chave not in PERMISSOES:
            raise ErroDiscord(f'Permissão "{nome}" desconhecida. Use: {", ".join(PERMISSOES)}.')
        total |= PERMISSOES[chave]
    return total


def _nomes_perm(valor: int) -> list[str]:
    return [n for n, b in PERMISSOES.items() if valor & b]


CORES = {"verde": 0x22C55E, "azul": 0x3B82F6, "vermelho": 0xEF4444, "amarelo": 0xEAB308,
         "laranja": 0xF97316, "roxo": 0x8B5CF6, "rosa": 0xEC4899, "ciano": 0x06B6D4,
         "preto": 0x111111, "branco": 0xFFFFFF, "cinza": 0x6B7280, "dourado": 0xD4AF37}


def _cor(valor: str | int | None) -> int | None:
    if valor is None or valor == "":
        return None
    if isinstance(valor, int):
        return valor
    s = str(valor).strip().lower()
    if _norm(s) in CORES:
        return CORES[_norm(s)]
    m = re.fullmatch(r"#?([0-9a-f]{6})", s)
    if m:
        return int(m.group(1), 16)
    raise ErroDiscord(f'Cor "{valor}" inválida. Use #RRGGBB ou: {", ".join(CORES)}.')


def montar_mensagem(texto: str | None = None, titulo: str | None = None, descricao: str | None = None,
                    cor: str | None = None, imagem_url: str | None = None, miniatura_url: str | None = None,
                    rodape: str | None = None, botao_texto: str | None = None, botao_link: str | None = None,
                    mencionar_todos: bool = False) -> dict:
    """Monta o JSON de mensagem do Discord (texto + embed + botão de link)."""
    payload: dict[str, Any] = {}
    if texto:
        if len(texto) > 2000:
            raise ErroDiscord(f"O texto tem {len(texto)} caracteres; o limite do Discord é 2000. Use descricao (até 4096) ou divida em duas mensagens.")
        payload["content"] = texto
    if any([titulo, descricao, imagem_url, miniatura_url, rodape]):
        embed: dict[str, Any] = {"color": _cor(cor) if cor else COR_PADRAO}
        if titulo:
            embed["title"] = titulo[:256]
        if descricao:
            if len(descricao) > 4096:
                raise ErroDiscord("A descrição passou de 4096 caracteres.")
            embed["description"] = descricao
        if imagem_url:
            embed["image"] = {"url": imagem_url}
        if miniatura_url:
            embed["thumbnail"] = {"url": miniatura_url}
        if rodape:
            embed["footer"] = {"text": rodape[:2048]}
        payload["embeds"] = [embed]
    if botao_link:
        if not re.match(r"https?://", botao_link):
            raise ErroDiscord("botao_link precisa começar com http:// ou https://")
        payload["components"] = [{"type": 1, "components": [
            {"type": 2, "style": 5, "label": (botao_texto or "Abrir")[:80], "url": botao_link}]}]
    if not payload.get("content") and not payload.get("embeds"):
        raise ErroDiscord("A mensagem está vazia: passe texto, ou titulo/descricao para um embed.")
    payload["allowed_mentions"] = {"parse": ["users", "roles"] + (["everyone"] if mencionar_todos else [])}
    return payload


def _preencher(valor: Any, campos: dict[str, str]) -> Any:
    """Troca {usuario}, {nome}, {servidor}, {membros} dentro de textos (inclusive no embed)."""
    if isinstance(valor, str):
        for chave, troca in campos.items():
            valor = valor.replace("{" + chave + "}", troca)
        return valor
    if isinstance(valor, list):
        return [_preencher(v, campos) for v in valor]
    if isinstance(valor, dict):
        return {k: (_preencher(v, campos) if k != "url" else v) for k, v in valor.items()}
    return valor


def _emoji_chave(emoji: str) -> str:
    s = str(emoji).strip()
    m = re.fullmatch(r"<a?:\w+:(\d+)>|\w+:(\d+)", s)
    if m:
        return f"id:{m.group(1) or m.group(2)}"
    return s.replace("️", "")


def _emoji_url(emoji: str) -> str:
    s = str(emoji).strip()
    m = re.fullmatch(r"<a?:(\w+):(\d+)>|(\w+):(\d+)", s)
    if m:
        return quote(f"{m.group(1) or m.group(3)}:{m.group(2) or m.group(4)}", safe="")
    return quote(s, safe="")


# ───────────────────────── encontrar canais, cargos e membros ─────────────────────────

async def _canais() -> list[dict]:
    return await dc("GET", f"/guilds/{await servidor_id()}/channels")


async def _cargos() -> list[dict]:
    return await dc("GET", f"/guilds/{await servidor_id()}/roles")


def _escolher(ref: Any, itens: list[dict], rotulo: str, mostrar) -> dict:
    alvo = _norm(ref)
    if not alvo:
        raise ErroDiscord(f'Não entendi qual {rotulo} é "{ref}". Use o ID.')
    exatos = [i for i in itens if _norm(i["name"]) == alvo]
    if len(exatos) == 1:
        return exatos[0]
    if len(exatos) > 1:
        raise ErroDiscord(f'Há mais de um {rotulo} chamado "{ref}": ' + ", ".join(mostrar(i) for i in exatos[:10]) + ". Use o ID.")
    parciais = [i for i in itens if alvo in _norm(i["name"])]
    if len(parciais) == 1:
        return parciais[0]
    if parciais:
        raise ErroDiscord(f'"{ref}" combina com vários: ' + ", ".join(mostrar(i) for i in parciais[:10]) + ". Use o ID.")
    raise ErroDiscord(f'Não achei {rotulo} "{ref}".')


async def achar_canal(ref: Any, tipos: set[int] | None = None) -> dict:
    if ref is None or str(ref).strip() == "":
        raise ErroDiscord("Informe o canal (ID, #menção ou nome).")
    lista = await _canais()
    cid = _id(ref)
    if cid:
        for c in lista:
            if c["id"] == cid:
                return c
        return await dc("GET", f"/channels/{cid}")  # threads não aparecem na lista
    candidatos = [c for c in lista if tipos is None or c["type"] in tipos]
    try:
        return _escolher(ref, candidatos, "canal", lambda c: f'#{c["name"]} ({c["id"]})')
    except ErroDiscord as erro:
        if "Não achei" in str(erro):
            raise ErroDiscord(f'Não achei o canal "{ref}". Use listar_canais para ver nomes e IDs.')
        raise


async def achar_categoria(ref: Any) -> dict:
    return await achar_canal(ref, tipos={4})


async def achar_cargo(ref: Any) -> dict:
    gid = await servidor_id()
    lista = await _cargos()
    s = str(ref).strip()
    if s in ("@everyone", "everyone") or _norm(s) in ("everyone", "todos", "todomundo"):
        return next(c for c in lista if c["id"] == gid)
    rid = _id(s)
    if rid:
        for c in lista:
            if c["id"] == rid:
                return c
        raise ErroDiscord(f"Cargo com ID {rid} não existe.")
    try:
        return _escolher(s.lstrip("@"), lista, "cargo", lambda c: f'@{c["name"]} ({c["id"]})')
    except ErroDiscord as erro:
        if "Não achei" in str(erro):
            raise ErroDiscord(f'Não achei o cargo "{ref}". Use listar_cargos para ver nomes e IDs.')
        raise


async def achar_membro(ref: Any) -> dict:
    gid = await servidor_id()
    uid = _id(ref)
    if uid:
        return await dc("GET", f"/guilds/{gid}/members/{uid}")
    consulta = str(ref).strip().lstrip("@")
    if not consulta:
        raise ErroDiscord("Informe o membro (ID, @menção ou nome).")
    achados = await dc("GET", f"/guilds/{gid}/members/search", params={"query": consulta[:100], "limit": 10})
    if not achados:
        raise ErroDiscord(f'Não achei ninguém chamado "{consulta}" (a busca usa o começo do nome de usuário ou apelido). Tente o ID.')
    alvo = _norm(consulta)
    exatos = [m for m in achados if alvo in (_norm(m["user"]["username"]), _norm(m["user"].get("global_name") or ""), _norm(m.get("nick") or ""))]
    if len(exatos) == 1:
        return exatos[0]
    if len(achados) == 1:
        return achados[0]
    raise ErroDiscord("Encontrei várias pessoas: " + ", ".join(f'{_nome_membro(m)} (@{m["user"]["username"]}, ID {m["user"]["id"]})' for m in achados) + ". Diga qual pelo ID.")


async def achar_alvo_permissao(ref: Any) -> tuple[str, int, str]:
    """Cargo (tipo 0) ou membro (tipo 1)."""
    try:
        cargo = await achar_cargo(ref)
        return cargo["id"], 0, f'@{cargo["name"]}'
    except ErroDiscord:
        membro = await achar_membro(ref)
        return membro["user"]["id"], 1, _nome_membro(membro)


async def _sobrescrever(canal: dict, alvo_id: str, tipo: int, permitir: int = 0, negar: int = 0,
                        herdar: int = 0, motivo: str | None = None) -> tuple[int, int]:
    atual = next((o for o in canal.get("permission_overwrites", []) if o["id"] == alvo_id), None)
    allow = int(atual["allow"]) if atual else 0
    deny = int(atual["deny"]) if atual else 0
    allow = (allow | permitir) & ~negar & ~herdar
    deny = (deny | negar) & ~permitir & ~herdar
    if allow == 0 and deny == 0:
        if atual:
            await dc("DELETE", f'/channels/{canal["id"]}/permissions/{alvo_id}', motivo=motivo)
    else:
        await dc("PUT", f'/channels/{canal["id"]}/permissions/{alvo_id}',
                 corpo={"allow": str(allow), "deny": str(deny), "type": tipo}, motivo=motivo)
    return allow, deny


def _link_canal(gid: str, cid: str, mid: str | None = None) -> str:
    return f"https://discord.com/channels/{gid}/{cid}" + (f"/{mid}" if mid else "")


# ───────────────────────── memória das automações (salva no próprio Discord) ─────────────────────────

CONFIG_PADRAO: dict[str, Any] = {"versao": 1, "agendadas": [], "boas_vindas": {}, "despedida": {},
                                 "respostas": [], "cargos_reacao": [], "logs": {},
                                 "produtos": {}, "compras": {}, "paineis": {}, "tickets": {}, "sorteios": {}, "vendas": [], "entregas": {}}
_cfg: dict[str, Any] = deepcopy(CONFIG_PADRAO)
_cfg_estado: dict[str, Any] = {"carregada": False, "canal_id": None, "msg_id": None, "aviso": None, "tentativa": 0.0}
_cfg_lock = asyncio.Lock()


async def _canal_config() -> str:
    if CONFIG_CANAL_ID:
        return CONFIG_CANAL_ID
    canais = await _canais()
    for c in canais:
        if c["type"] == 0 and c["name"] == NOME_CANAL_CONFIG:
            return c["id"]
    gid, bot = await servidor_id(), await eu()
    corpo: dict[str, Any] = {
        "name": NOME_CANAL_CONFIG, "type": 0,
        "topic": "Memória do agente ECO PULSE (automações). Não apague as mensagens deste canal.",
        "permission_overwrites": [
            {"id": gid, "type": 0, "allow": "0", "deny": str(VER)},
            {"id": bot["id"], "type": 1, "allow": str(VER | ENVIAR | ANEXAR | HISTORICO), "deny": "0"},
        ],
    }
    staff = next((c for c in canais if c["type"] == 4 and "staff" in _norm(c["name"])), None)
    if staff:
        corpo["parent_id"] = staff["id"]
    novo = await dc("POST", f"/guilds/{gid}/channels", corpo=corpo, motivo="Memória do agente ECO PULSE")
    log.info("Canal de memória criado: %s", novo["id"])
    return novo["id"]


async def carregar_config(forcar: bool = False) -> None:
    async with _cfg_lock:
        if _cfg_estado["carregada"] and not forcar:
            return
        _cfg_estado["tentativa"] = time.time()
        try:
            canal = await _canal_config()
            _cfg_estado["canal_id"] = canal
            bot = await eu()
            mensagens = await dc("GET", f"/channels/{canal}/messages", params={"limit": 50})
            for msg in mensagens:  # da mais nova para a mais antiga
                if msg["author"]["id"] != bot["id"]:
                    continue
                anexo = next((a for a in msg.get("attachments", []) if a["filename"] == ARQUIVO_CONFIG), None)
                if not anexo:
                    continue
                resp = await cliente_web().get(anexo["url"])
                resp.raise_for_status()
                novo = deepcopy(CONFIG_PADRAO)
                novo.update(resp.json())
                _cfg.clear()
                _cfg.update(novo)
                _cfg_estado["msg_id"] = msg["id"]
                break
            _cfg_estado["carregada"] = True
            _cfg_estado["aviso"] = None
            log.info("Memória carregada: %d agendadas, %d respostas, %d cargos por reação",
                     len(_cfg["agendadas"]), len(_cfg["respostas"]), len(_cfg["cargos_reacao"]))
        except Exception as erro:
            _cfg_estado["aviso"] = f"Não consegui ler a memória das automações: {erro}"
            log.warning(_cfg_estado["aviso"])


async def garantir_config() -> None:
    if not _cfg_estado["carregada"] and time.time() - _cfg_estado["tentativa"] > 30:
        await carregar_config()


async def exigir_config() -> None:
    """Antes de mudar automações: sem ler a memória, mudar poderia apagar o que já existe."""
    if not _cfg_estado["carregada"]:
        await carregar_config()
    if not _cfg_estado["carregada"]:
        raise ErroDiscord((_cfg_estado["aviso"] or "Não consegui ler a memória das automações.") +
                          " Confira se o bot tem permissão de Administrador e tente de novo.")


async def salvar_config() -> None:
    async with _cfg_lock:
        canal = _cfg_estado["canal_id"] or await _canal_config()
        _cfg_estado["canal_id"] = canal
        conteudo = json.dumps(_cfg, ensure_ascii=False, indent=1).encode()
        payload = {"content": f"🧠 Memória do agente ECO PULSE — atualizada {_fmt(_agora())}. Não apague.",
                   "attachments": [{"id": 0, "filename": ARQUIVO_CONFIG}]}
        msg = await dc("POST", f"/channels/{canal}/messages", dados={"payload_json": json.dumps(payload)},
                       arquivos={"files[0]": (ARQUIVO_CONFIG, conteudo, "application/json")})
        antiga, _cfg_estado["msg_id"] = _cfg_estado["msg_id"], msg["id"]
        if antiga:
            try:
                await dc("DELETE", f"/channels/{canal}/messages/{antiga}")
            except ErroDiscord:
                pass


async def registrar(texto: str) -> None:
    """Manda uma linha para o canal de registros, se estiver configurado."""
    logs = _cfg.get("logs") or {}
    if not logs.get("ativo") or not logs.get("canal_id"):
        return
    try:
        await dc("POST", f'/channels/{logs["canal_id"]}/messages',
                 corpo={"content": texto[:2000], "allowed_mentions": {"parse": []}})
    except ErroDiscord as erro:
        log.warning("Falha ao registrar no canal de logs: %s", erro)


# ───────────────────────── agendamento ─────────────────────────

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
                               (limpar_tickets, "fechar tickets"), (fechar_entregas, "fechar canais de entrega")):
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


# ───────────────────────── eventos em tempo real (gateway) ─────────────────────────

_bot = None
_bot_estado: dict[str, Any] = {"status": "desligado", "intents_privilegiadas": None, "aviso": None}
_ultimas_respostas: dict[tuple[str, str], float] = {}


def _campos_membro(uid: str, nome: str, servidor: str, membros: Any) -> dict[str, str]:
    return {"usuario": f"<@{uid}>", "usuário": f"<@{uid}>", "mencao": f"<@{uid}>", "nome": nome,
            "servidor": servidor, "membros": str(membros if membros is not None else "?")}


async def _mandar_config_mensagem(conf: dict, campos: dict[str, str], canal_id: str) -> None:
    payload = montar_mensagem(texto=conf.get("texto"), titulo=conf.get("titulo"), descricao=conf.get("descricao"),
                              cor=conf.get("cor"), imagem_url=conf.get("imagem_url"))
    await _postar(canal_id, _preencher(payload, campos))


async def ao_entrar(uid: str, nome: str, servidor: str, membros: Any, bot: bool) -> None:
    await garantir_config()
    campos = _campos_membro(uid, nome, servidor, membros)
    bv = _cfg.get("boas_vindas") or {}
    if bv.get("ativo") and not bot:
        if bv.get("cargo_id"):
            try:
                await dc("PUT", f'/guilds/{await servidor_id()}/members/{uid}/roles/{bv["cargo_id"]}', motivo="Cargo automático de entrada")
            except ErroDiscord as erro:
                await registrar(f"⚠️ Não consegui dar o cargo automático para <@{uid}>: {erro}")
        if bv.get("canal_id"):
            try:
                await _mandar_config_mensagem(bv, campos, bv["canal_id"])
            except ErroDiscord as erro:
                await registrar(f"⚠️ Falha na mensagem de boas-vindas: {erro}")
        if bv.get("mandar_dm"):
            try:
                dm = await dc("POST", "/users/@me/channels", corpo={"recipient_id": uid})
                await _mandar_config_mensagem(bv, campos, dm["id"])
            except ErroDiscord:
                pass
    await registrar(f"📥 **{nome}** (<@{uid}>) entrou{' (bot)' if bot else ''} — agora são {campos['membros']} membros.")


async def ao_sair(uid: str, nome: str, servidor: str, membros: Any) -> None:
    await garantir_config()
    campos = _campos_membro(uid, nome, servidor, membros)
    dp = _cfg.get("despedida") or {}
    if dp.get("ativo") and dp.get("canal_id"):
        try:
            await _mandar_config_mensagem(dp, campos, dp["canal_id"])
        except ErroDiscord as erro:
            await registrar(f"⚠️ Falha na mensagem de despedida: {erro}")
    await registrar(f"📤 **{nome}** (<@{uid}>) saiu do servidor.")


def achar_resposta(conteudo: str, canal_id: str) -> dict | None:
    texto = _norm_frase(conteudo)
    if not texto:
        return None
    for regra in _cfg.get("respostas", []):
        if regra.get("canal_id") and regra["canal_id"] != canal_id:
            continue
        gatilho = _norm_frase(regra["gatilho"])
        modo = regra.get("modo", "contem")
        if modo == "exata":
            ok = texto == gatilho
        elif modo == "comeca":
            ok = texto.startswith(gatilho)
        else:
            ok = re.search(rf"(?<!\w){re.escape(gatilho)}(?!\w)", texto) is not None
        if ok:
            return regra
    return None


async def ao_mensagem(conteudo: str, canal_id: str, mensagem_id: str, autor_id: str, autor_nome: str) -> None:
    regra = achar_resposta(conteudo, canal_id)
    if not regra:
        return
    chave = (regra["id"], canal_id)
    if time.time() - _ultimas_respostas.get(chave, 0) < 10:
        return  # evita flood
    _ultimas_respostas[chave] = time.time()
    texto = _preencher(regra["resposta"], {"usuario": f"<@{autor_id}>", "usuário": f"<@{autor_id}>", "nome": autor_nome})
    await dc("POST", f"/channels/{canal_id}/messages", corpo={
        "content": texto[:2000], "message_reference": {"message_id": mensagem_id, "fail_if_not_exists": False},
        "allowed_mentions": {"parse": ["users"], "replied_user": True}})


async def ao_reagir(mensagem_id: str, emoji_chave: str, uid: str, adicionou: bool) -> None:
    for regra in _cfg.get("cargos_reacao", []):
        if regra["mensagem_id"] == mensagem_id and regra["emoji"] == emoji_chave:
            metodo = "PUT" if adicionou else "DELETE"
            try:
                await dc(metodo, f'/guilds/{await servidor_id()}/members/{uid}/roles/{regra["cargo_id"]}', motivo="Cargo por reação")
            except ErroDiscord as erro:
                await registrar(f"⚠️ Cargo por reação falhou para <@{uid}>: {erro}")


# ───────────────────────── loja: compra em chat privado com Pix ─────────────────────────
#
# Fluxo: botão "Comprar agora" no painel → o bot cria um chat privado (comprador + cargo aprovador)
# com o QR Code e o "copia e cola" do Pix → o comprador clica em "Confirmar pagamento" e digita o
# nome completo → o aprovador (Fundador) confirma ou recusa → confirmado: o produto vai por DM
# automaticamente; recusado: o chat é fechado. Tudo fica salvo na memória (#agente-config), então
# os botões continuam funcionando depois que o Render reinicia.

ESPERA_PAGAMENTO = timedelta(hours=24)        # chat sem pagamento informado fecha sozinho
FECHAR_APOS_ENTREGA = timedelta(minutes=5)
FECHAR_APOS_RECUSA = timedelta(minutes=1)
FECHAR_APOS_CANCELAR = timedelta(seconds=10)
GERENCIAR_MSG, EMBED_LINKS = PERMISSOES["gerenciar_mensagens"], PERMISSOES["inserir_links"]
STATUS_ABERTOS = ("aguardando", "analise", "entregando")
_loja_lock = asyncio.Lock()
_estoque_lock = asyncio.Lock()


def _slug(texto: Any, limite: int = 40) -> str:
    s = unicodedata.normalize("NFKD", str(texto)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")[:limite].strip("-")


def _ler_preco(valor: Any) -> float:
    s = str(valor).lower().replace("r$", "").replace(" ", "").strip()
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    try:
        n = round(float(s), 2)
    except ValueError:
        raise ErroDiscord(f'Preço "{valor}" inválido. Use algo como 19,90.')
    if n <= 0 or n > 100000:
        raise ErroDiscord(f'Preço "{valor}" fora do normal.')
    return n


def _reais(valor: float | None) -> str:
    if not valor:
        return "a combinar"
    return "R$ " + f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _campo_emv(id_: str, valor: str) -> str:
    return f"{id_}{len(valor):02d}{valor}"


def _crc16(texto: str) -> str:
    """CRC16-CCITT (0x1021, início 0xFFFF), o mesmo que o Banco Central usa no Pix."""
    crc = 0xFFFF
    for byte in texto.encode("utf-8"):
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) if crc & 0x8000 else (crc << 1)
            crc &= 0xFFFF
    return f"{crc:04X}"


def _ascii_pix(texto: str, limite: int, padrao: str) -> str:
    s = unicodedata.normalize("NFKD", str(texto)).encode("ascii", "ignore").decode()
    s = re.sub(r"[^A-Za-z0-9 ]", "", s).strip().upper()
    return s[:limite].strip() or padrao


def gerar_pix(valor: float | None, txid: str) -> str | None:
    """Monta o Pix "copia e cola" (BR Code estático) com a chave do Render e o valor do produto."""
    if PIX_COPIA_COLA:
        return PIX_COPIA_COLA
    if not PIX_CHAVE:
        return None
    chave = PIX_CHAVE.strip()
    if "@" in chave:
        chave = chave.lower()
    conta = _campo_emv("00", "br.gov.bcb.pix") + _campo_emv("01", chave)
    corpo = _campo_emv("00", "01") + _campo_emv("01", "11") + _campo_emv("26", conta) + _campo_emv("52", "0000") + _campo_emv("53", "986")
    if valor:
        corpo += _campo_emv("54", f"{valor:.2f}")
    corpo += _campo_emv("58", "BR") + _campo_emv("59", _ascii_pix(PIX_NOME, 25, "ECO PULSE"))
    corpo += _campo_emv("60", _ascii_pix(PIX_CIDADE, 15, "SAO PAULO"))
    corpo += _campo_emv("62", _campo_emv("05", re.sub(r"[^A-Za-z0-9]", "", txid)[:25] or "***"))
    corpo += "6304"
    return corpo + _crc16(corpo)


def _qr_png(texto: str) -> bytes | None:
    try:
        import segno
        buf = io.BytesIO()
        segno.make_qr(texto, error="m").save(buf, kind="png", scale=8, border=3)
        return buf.getvalue()
    except Exception as erro:
        log.warning("Não consegui gerar o QR Code localmente (%s); usando gerador online.", erro)
        return None


def _qr_url_online(texto: str) -> str:
    return "https://api.qrserver.com/v1/create-qr-code/?size=420x420&margin=12&data=" + quote(texto, safe="")


def _botao(rotulo: str, custom_id: str, estilo: int = 1, emoji: str | None = None) -> dict:
    b: dict[str, Any] = {"type": 2, "style": estilo, "label": rotulo[:80], "custom_id": custom_id[:100]}
    if emoji:
        b["emoji"] = {"name": emoji}
    return b


def _linha(*botoes: dict) -> dict:
    return {"type": 1, "components": list(botoes)[:5]}


def _botoes_decisao() -> dict:
    return _linha(_botao("Confirmar", "ecop:aprovar", 3, "✅"), _botao("Recusar", "ecop:recusar", 4, "❌"))


def _valor_modal(no: Any, custom_id: str) -> str | None:
    if isinstance(no, dict):
        if no.get("custom_id") == custom_id and "value" in no:
            return str(no["value"])
        for v in no.values():
            achado = _valor_modal(v, custom_id)
            if achado is not None:
                return achado
    elif isinstance(no, list):
        for v in no:
            achado = _valor_modal(v, custom_id)
            if achado is not None:
                return achado
    return None


def _ids_cargos(membro: Any) -> set[str]:
    ids: set[str] = set()
    for r in getattr(membro, "roles", None) or []:
        ids.add(str(getattr(r, "id", r)))
    for r in getattr(membro, "_roles", None) or []:
        ids.add(str(r))
    return ids


def _pode_aprovar(inter: Any, prod: dict) -> bool:
    guild = getattr(inter, "guild", None)
    if guild is not None and getattr(guild, "owner_id", None) == inter.user.id:
        return True
    aprov = prod.get("cargo_aprovador_id")
    return bool(aprov) and aprov in _ids_cargos(inter.user)


def _partes(texto: str, tamanho: int = 1900) -> list[str]:
    return [texto[i:i + tamanho] for i in range(0, len(texto), tamanho)] or [""]


def _com_rodape(embed: dict, texto: str, cor: int | None = None) -> dict:
    novo = deepcopy(embed)
    novo["footer"] = {"text": texto[:2048]}
    if cor is not None:
        novo["color"] = cor
    return novo


def _embed_da_mensagem(inter: Any) -> dict:
    try:
        return inter.message.embeds[0].to_dict()
    except Exception:
        return {"title": "🧾 Pagamento informado", "color": CORES["amarelo"]}


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


async def _canal_existe(canal_id: str) -> bool:
    try:
        await dc("GET", f"/channels/{canal_id}")
        return True
    except ErroDiscord as erro:
        if erro.status == 404 or erro.codigo == 10003:
            return False
        return True


async def _registrar_venda(prod: dict, texto: str) -> None:
    canal = prod.get("canal_vendas_id")
    if canal:
        try:
            await dc("POST", f"/channels/{canal}/messages", corpo={"content": texto[:2000], "allowed_mentions": {"parse": []}})
        except ErroDiscord as erro:
            log.warning("Falha ao registrar venda: %s", erro)
    if (_cfg.get("logs") or {}).get("canal_id") != canal:
        await registrar(texto)


async def _criar_canal_compra(prod: dict, uid: str, nome_exibicao: str, usuario: str) -> dict:
    gid, bot = await servidor_id(), await eu()
    base = prod.get("prefixo_canal") or f'compra-{prod["id"]}'
    sufixo = _slug(nome_exibicao, 30) or _slug(usuario, 30) or uid[-6:]
    nome = f"{base}-{sufixo}"[:100]
    perms: list[dict[str, Any]] = [
        {"id": gid, "type": 0, "allow": "0", "deny": str(VER)},
        {"id": uid, "type": 1, "allow": str(VER | ENVIAR | HISTORICO | ANEXAR), "deny": "0"},
        {"id": bot["id"], "type": 1, "allow": str(VER | ENVIAR | HISTORICO | ANEXAR | EMBED_LINKS | GERENCIAR_MSG), "deny": "0"},
    ]
    if prod.get("cargo_aprovador_id"):
        perms.append({"id": prod["cargo_aprovador_id"], "type": 0,
                      "allow": str(VER | ENVIAR | HISTORICO | ANEXAR | GERENCIAR_MSG), "deny": "0"})
    corpo: dict[str, Any] = {"name": nome, "type": 0, "permission_overwrites": perms,
                             "topic": f'Compra de {prod["nome"]} • comprador <@{uid}> • chat privado: só você e a equipe veem'}
    if prod.get("categoria_id"):
        corpo["parent_id"] = prod["categoria_id"]
    motivo = f'Compra de {prod["nome"]}'
    try:
        return await dc("POST", f"/guilds/{gid}/channels", corpo=corpo, motivo=motivo)
    except ErroDiscord as erro:
        if erro.codigo != 50035:
            raise
    # nome recusado (ex.: caractere não aceito) ou categoria cheia: tenta de novo mais simples
    corpo["name"] = re.sub(r"[^a-z0-9_-]+", "-", nome.lower()).strip("-")[:100] or f"compra-{uid[-6:]}"
    try:
        return await dc("POST", f"/guilds/{gid}/channels", corpo=corpo, motivo=motivo)
    except ErroDiscord as erro:
        if erro.codigo != 50035 or "parent_id" not in corpo:
            raise
    corpo.pop("parent_id", None)
    return await dc("POST", f"/guilds/{gid}/channels", corpo=corpo, motivo=motivo)


async def _mandar_pagamento(canal_id: str, prod: dict, compra: dict) -> None:
    uid = compra["comprador"]
    pix = gerar_pix(prod.get("preco"), compra["txid"])
    link = prod.get("link_pagamento")
    qr_url = prod.get("qr_imagem_url")
    passos = []
    if pix:
        passos.append("Escaneie o **QR Code** abaixo no app do seu banco **ou** copie o código Pix da próxima "
                      "mensagem (no celular: segure a mensagem → **Copiar texto**).")
    elif qr_url:
        passos.append("Escaneie o **QR Code** abaixo no app do seu banco.")
    if link:
        passos.append("Se preferir, pague pelo botão **💳 Pagar pelo link**." if passos else
                      "Pague pelo botão **💳 Pagar pelo link** lá embaixo.")
    sem_pagamento = not (pix or qr_url or link)
    if sem_pagamento:
        passos.append("Aguarde: a equipe vai mandar os dados de pagamento aqui neste chat.")
    passos.append("Depois de pagar, clique em **✅ Confirmar pagamento** e digite seu **nome completo**.")
    passos.append(f"A equipe confere o pagamento e o produto chega {_onde_entrega(prod)} automaticamente.")
    lista = "\n".join(f"**{i}.** {p}" for i, p in enumerate(passos, 1))
    embed: dict[str, Any] = {
        "title": f'🛒 Compra • {prod["nome"]}',
        "description": (f"Olá, <@{uid}>! Este chat é **privado**: só você e a equipe conseguem ver.\n\n"
                        f'💰 **Valor:** {_reais(prod.get("preco"))}\n🧾 **Código da compra:** `{compra["txid"]}`\n\n'
                        f"**Como pagar**\n{lista}\n\n"
                        "⚠️ Pague **somente** pelos dados deste chat. Se o pagamento não for informado em 24 horas, "
                        "este chat fecha sozinho."),
        "color": prod.get("cor") or CORES["roxo"],
        "footer": {"text": "ECO PULSE • Compra segura"},
    }
    mencoes: dict[str, Any] = {"parse": [], "users": [uid]}
    conteudo = f"<@{uid}>"
    aprov = prod.get("cargo_aprovador_id")
    if sem_pagamento and aprov:
        conteudo += f" <@&{aprov}>"
        mencoes["roles"] = [aprov]
    payload: dict[str, Any] = {"content": conteudo, "embeds": [embed], "allowed_mentions": mencoes}
    png = _qr_png(pix) if pix else None
    if png:
        embed["image"] = {"url": "attachment://pix.png"}
        payload["attachments"] = [{"id": 0, "filename": "pix.png"}]
        await dc("POST", f"/channels/{canal_id}/messages", dados={"payload_json": json.dumps(payload)},
                 arquivos={"files[0]": ("pix.png", png, "image/png")})
    else:
        if pix:
            embed["image"] = {"url": _qr_url_online(pix)}
        elif qr_url:
            embed["image"] = {"url": qr_url}
        await dc("POST", f"/channels/{canal_id}/messages", corpo=payload)
    botoes = [_botao("Confirmar pagamento", "ecop:pago", 3, "✅")]
    if link:
        botoes.append({"type": 2, "style": 5, "label": "Pagar pelo link", "url": link, "emoji": {"name": "💳"}})
    botoes.append(_botao("Cancelar compra", "ecop:cancelar", 4, "❌"))
    msg = await dc("POST", f"/channels/{canal_id}/messages", corpo={
        "content": pix or "Quando terminar de pagar, clique no botão abaixo 👇",
        "components": [_linha(*botoes)], "allowed_mentions": {"parse": []}})
    compra["msg_botoes"] = msg["id"]


async def _clicou_comprar(r: _Resposta, produto: str) -> None:
    inter = r.inter
    await r.adiar()
    await exigir_config()
    prod = _cfg["produtos"].get(produto)
    if not prod or not prod.get("ativo", True):
        await r.efemera("Este produto não está disponível no momento.")
        return
    uid = str(inter.user.id)
    async with _loja_lock:
        for canal_id, c in list(_cfg["compras"].items()):
            if c["comprador"] == uid and c["produto"] == produto and c["status"] in STATUS_ABERTOS:
                if await _canal_existe(canal_id):
                    await r.efemera(f"Você já tem uma compra aberta deste produto: <#{canal_id}>")
                    return
                _cfg["compras"].pop(canal_id, None)
        nome = getattr(inter.user, "display_name", None) or inter.user.name
        canal = await _criar_canal_compra(prod, uid, nome, inter.user.name)
        agora = _agora()
        compra: dict[str, Any] = {
            "produto": produto, "comprador": uid, "comprador_nome": nome, "status": "aguardando",
            "valor": prod.get("preco"), "txid": "ECOP" + secrets.token_hex(4).upper(),
            "criado": agora.isoformat(), "fechar_em": (agora + ESPERA_PAGAMENTO).isoformat(),
        }
        _cfg["compras"][canal["id"]] = compra
    try:
        await _mandar_pagamento(canal["id"], prod, compra)
    finally:
        await salvar_config()
    await r.efemera(f'✅ Seu chat de compra foi criado: <#{canal["id"]}>\nO pagamento por Pix já está lá.')
    await registrar(f'🛒 <@{uid}> abriu uma compra de **{prod["nome"]}** em <#{canal["id"]}>.')


async def _clicou_pago(r: _Resposta) -> None:
    inter = r.inter
    if not _cfg_estado["carregada"]:
        asyncio.create_task(garantir_config())
        await r.efemera("O bot acabou de reiniciar. Tente de novo em alguns segundos.")
        return
    c = _cfg["compras"].get(str(inter.channel_id))
    if not c:
        await r.efemera("Esta compra já foi encerrada.")
        return
    if str(inter.user.id) != c["comprador"]:
        await r.efemera("Só quem está comprando pode confirmar o pagamento.")
        return
    if c["status"] != "aguardando":
        await r.efemera("Você já informou o pagamento. Agora é só aguardar a equipe conferir.")
        return
    await r.enviar(9, {
        "custom_id": "ecop:modal_pago", "title": "Confirmar pagamento",
        "components": [_linha({"type": 4, "custom_id": "nome", "style": 1, "label": "Seu nome completo",
                               "placeholder": "Ex.: Maria da Silva Souza", "min_length": 5, "max_length": 100,
                               "required": True})],
    })


async def _modal_pago(r: _Resposta) -> None:
    inter = r.inter
    canal = str(inter.channel_id)
    c = _cfg["compras"].get(canal)
    if not c or str(inter.user.id) != c["comprador"]:
        await r.efemera("Esta compra já foi encerrada.")
        return
    if c["status"] != "aguardando":
        await r.efemera("Você já informou o pagamento. Agora é só aguardar a equipe conferir.")
        return
    nome = re.sub(r"[`*_~|<>@#\\]", "", _valor_modal(inter.data, "nome") or "")
    nome = re.sub(r"\s+", " ", nome).strip()
    if len(nome) < 5 or len(nome.split()) < 2:
        await r.efemera("Digite seu **nome completo** (nome e sobrenome). Clique em ✅ Confirmar pagamento de novo.")
        return
    prod = _cfg["produtos"].get(c["produto"], {})
    c.update(status="analise", nome_completo=nome, informado=_agora().isoformat(), fechar_em=None)
    aprov = prod.get("cargo_aprovador_id")
    embed = {
        "title": "🧾 Pagamento informado",
        "description": (f'<@{c["comprador"]}> disse que já pagou **{prod.get("nome", c["produto"])}**.\n\n'
                        f"👤 **Nome completo:** {nome}\n💰 **Valor:** {_reais(c.get('valor'))}\n"
                        f'🧾 **Código da compra:** `{c["txid"]}`\n\n'
                        "Confira no extrato do banco e escolha abaixo.\n"
                        f'<@{c["comprador"]}>, agora é só aguardar a equipe conferir. 🙏'),
        "color": CORES["amarelo"],
        "footer": {"text": f'Só o cargo {prod.get("cargo_aprovador_nome") or "Fundador"} pode confirmar ou recusar'},
    }
    dados: dict[str, Any] = {"embeds": [embed], "components": [_botoes_decisao()],
                             "allowed_mentions": {"parse": [], "roles": [aprov] if aprov else []}}
    if aprov:
        dados["content"] = f"<@&{aprov}>"
    await r.enviar(4, dados)
    await salvar_config()


async def _pegar_item(prod: dict) -> tuple[str | None, tuple[str, str] | None]:
    """Pega o próximo produto do estoque (mensagem mais antiga do canal; fixadas são ignoradas)."""
    canal = prod.get("canal_estoque_id")
    if canal:
        msgs = await dc("GET", f"/channels/{canal}/messages", params={"limit": 100})
        validas = [m for m in msgs if not m.get("pinned") and (m.get("content") or m.get("attachments"))]
        if validas:
            m = validas[-1]  # a API devolve da mais nova para a mais antiga
            partes = [m.get("content") or ""] + [a["url"] for a in m.get("attachments", [])]
            return "\n".join(p for p in partes if p).strip(), (canal, m["id"])
    if prod.get("entrega_texto"):
        return prod["entrega_texto"], None
    return None, None


async def _contar_estoque(prod: dict) -> str:
    try:
        msgs = await dc("GET", f'/channels/{prod["canal_estoque_id"]}/messages', params={"limit": 100})
    except ErroDiscord as erro:
        return f"erro: {erro}"
    n = len([m for m in msgs if not m.get("pinned") and (m.get("content") or m.get("attachments"))])
    return "100 ou mais" if n >= 100 else str(n)


async def _entregar_dm(c: dict, prod: dict, item: str) -> bool:
    try:
        dm = await dc("POST", "/users/@me/channels", corpo={"recipient_id": c["comprador"]})
        await dc("POST", f'/channels/{dm["id"]}/messages', corpo={"embeds": [{
            "title": "✅ Compra confirmada!",
            "description": (f'Seu pagamento de **{prod["nome"]}** foi confirmado. Seu produto está logo abaixo 👇\n\n'
                            f'Guarde esta mensagem. Código da compra: `{c["txid"]}`'),
            "color": CORES["verde"], "footer": {"text": "ECO PULSE • Obrigado pela compra!"}}]})
        for parte in _partes(item):
            await dc("POST", f'/channels/{dm["id"]}/messages', corpo={"content": parte, "allowed_mentions": {"parse": []}})
        return True
    except ErroDiscord as erro:
        log.warning("Não consegui entregar por DM para %s: %s", c["comprador"], erro)
        return False


DIAS_ENTREGA_PADRAO = 7
_MODOS_ENTREGA = {"canal": "canal", "canalprivado": "canal", "privado": "canal", "dm": "dm", "mensagemdireta": "dm",
                  "canaledm": "canal_e_dm", "canalmaisdm": "canal_e_dm", "ambos": "canal_e_dm", "osdois": "canal_e_dm"}


def _modo_entrega(prod: dict) -> str:
    return prod.get("entrega_modo") or "canal"


def _onde_entrega(prod: dict) -> str:
    return {"canal": "num **canal privado** só seu", "dm": "na sua **DM**",
            "canal_e_dm": "num **canal privado** só seu e na sua **DM**"}[_modo_entrega(prod)]


async def _criar_canal_entrega(c: dict, prod: dict) -> dict:
    gid, bot = await servidor_id(), await eu()
    uid = c["comprador"]
    perms: list[dict[str, Any]] = [
        {"id": gid, "type": 0, "allow": "0", "deny": str(VER)},
        {"id": uid, "type": 1, "allow": str(VER | HISTORICO | ENVIAR | ANEXAR), "deny": "0"},
        {"id": bot["id"], "type": 1, "allow": str(VER | ENVIAR | HISTORICO | ANEXAR | EMBED_LINKS | GERENCIAR_MSG), "deny": "0"},
    ]
    if prod.get("cargo_aprovador_id"):
        perms.append({"id": prod["cargo_aprovador_id"], "type": 0, "allow": str(VER | ENVIAR | HISTORICO | GERENCIAR_MSG), "deny": "0"})
    nome = f'{prod.get("prefixo_entrega") or "📦・entrega"}-{_slug(c.get("comprador_nome"), 30) or uid[-6:]}'
    dias = int(prod.get("dias_entrega") or DIAS_ENTREGA_PADRAO)
    return await _criar_canal_privado(
        nome, perms, prod.get("categoria_entrega_id") or prod.get("categoria_id"),
        f'Entrega de {prod["nome"]} para <@{uid}> • código {c["txid"]} • disponível por {dias} dias',
        f'Entrega de {prod["nome"]}')


async def _entregar(c: dict, prod: dict, item: str) -> dict:
    """Entrega o produto conforme o modo do produto: canal privado só do comprador (padrão), DM ou os dois.
    Se o canal não puder ser criado, cai para a DM."""
    modo = _modo_entrega(prod)
    uid = c["comprador"]
    res: dict[str, Any] = {"canal": None, "dm": False}
    if modo in ("canal", "canal_e_dm"):
        ch = None
        try:
            ch = await _criar_canal_entrega(c, prod)
            dias = int(prod.get("dias_entrega") or DIAS_ENTREGA_PADRAO)
            fim = _agora() + timedelta(days=dias)
            await dc("POST", f'/channels/{ch["id"]}/messages', corpo={
                "content": f"<@{uid}>", "allowed_mentions": {"parse": [], "users": [uid]},
                "embeds": [{"title": f'✅ Compra confirmada • {prod["nome"]}', "color": CORES["verde"],
                            "description": (f"Seu pagamento foi confirmado! Seu produto está **logo abaixo** 👇\n\n"
                                            f'🧾 **Código da compra:** `{c["txid"]}`\n'
                                            f"⚠️ **Copie e guarde o conteúdo:** este canal é apagado <t:{int(fim.timestamp())}:R> "
                                            f"(<t:{int(fim.timestamp())}:f>)."),
                            "footer": {"text": "ECO PULSE • Obrigado pela compra! Este canal é só seu."}}]})
            for parte in _partes(item):
                await dc("POST", f'/channels/{ch["id"]}/messages', corpo={"content": parte, "allowed_mentions": {"parse": []}})
            await dc("POST", f'/channels/{ch["id"]}/messages', corpo={
                "content": "Já copiou e guardou tudo? Pode fechar este canal quando quiser.",
                "components": [_linha(_botao("Já salvei, fechar canal", "ecop:fechar_entrega", 2, "🔒"))]})
            _cfg.setdefault("entregas", {})[ch["id"]] = {
                "comprador": uid, "produto": c["produto"], "txid": c["txid"],
                "criado": _agora().isoformat(), "fechar_em": fim.isoformat()}
            res["canal"] = ch["id"]
        except ErroDiscord as erro:
            log.warning("Não consegui entregar no canal privado (%s); tentando a DM.", erro)
            if ch:
                try:
                    await dc("DELETE", f'/channels/{ch["id"]}', motivo="Entrega falhou")
                except ErroDiscord:
                    pass
    if modo in ("dm", "canal_e_dm") or not res["canal"]:
        res["dm"] = await _entregar_dm(c, prod, item)
    else:
        try:  # só um aviso na DM, sem o conteúdo
            dm = await dc("POST", "/users/@me/channels", corpo={"recipient_id": uid})
            await dc("POST", f'/channels/{dm["id"]}/messages', corpo={"embeds": [{
                "title": "✅ Compra confirmada!", "color": CORES["verde"],
                "description": f'Seu pagamento de **{prod["nome"]}** foi confirmado. Seu produto está no canal privado <#{res["canal"]}>.'}]})
        except ErroDiscord:
            pass
    return res


async def _clicou_fechar_entrega(r: _Resposta, confirmado: bool) -> None:
    inter = r.inter
    if not _cfg_estado["carregada"]:
        asyncio.create_task(garantir_config())
        await r.efemera("O bot acabou de reiniciar. Tente de novo em alguns segundos.")
        return
    canal = str(inter.channel_id)
    e = _cfg.get("entregas", {}).get(canal)
    if not e:
        await r.efemera("Este canal já está sendo fechado.")
        return
    prod = _cfg.get("produtos", {}).get(e["produto"], {})
    if str(inter.user.id) != e["comprador"] and not _pode_aprovar(inter, prod):
        await r.efemera("Só quem comprou pode fechar este canal.")
        return
    if not confirmado:
        await r.enviar(4, {"content": "Tem certeza? Depois de fechar, o conteúdo some. Confira se você copiou e guardou tudo.",
                           "flags": 64, "components": [_linha(_botao("Sim, fechar", "ecop:fechar_entrega_ok", 4, "🔒"))]})
        return
    e["fechar_em"] = (_agora() + timedelta(seconds=3)).isoformat()
    await r.enviar(7, {"content": "🔒 Fechando o canal…", "components": []})
    await salvar_config()


async def fechar_entregas() -> None:
    """Apaga canais de entrega vencidos (avisa o comprador 1 dia antes)."""
    if not _cfg_estado["carregada"] or not _cfg.get("entregas"):
        return
    agora = _agora()
    mudou = False
    for canal_id, e in list(_cfg["entregas"].items()):
        fim = datetime.fromisoformat(e["fechar_em"])
        if fim <= agora:
            try:
                await dc("DELETE", f"/channels/{canal_id}", motivo="Entrega encerrada")
            except ErroDiscord as erro:
                if erro.status != 404 and erro.codigo != 10003:
                    log.warning("Não consegui apagar o canal de entrega %s: %s", canal_id, erro)
                    continue
            _cfg["entregas"].pop(canal_id, None)
            mudou = True
        elif not e.get("avisado") and fim - agora <= timedelta(hours=24) and fim - datetime.fromisoformat(e["criado"]) > timedelta(hours=25):
            e["avisado"] = True
            mudou = True
            try:
                await dc("POST", f"/channels/{canal_id}/messages", corpo={
                    "content": f'⏰ <@{e["comprador"]}>, este canal será apagado <t:{int(fim.timestamp())}:R>. Copie e guarde o seu produto!',
                    "allowed_mentions": {"parse": [], "users": [e["comprador"]]}})
            except ErroDiscord as erro:
                if erro.status == 404 or erro.codigo == 10003:
                    _cfg["entregas"].pop(canal_id, None)
    if mudou:
        await salvar_config()


async def _aprovar(r: _Resposta, canal: str, c: dict, prod: dict, quem: str, embed: dict) -> None:
    nome_quem = getattr(r.inter.user, "display_name", None) or r.inter.user.name
    async with _estoque_lock:
        item, origem = await _pegar_item(prod)
        if item is None:
            c["status"] = "analise"
            await r.editar_original({"embeds": [_com_rodape(embed, "⚠️ Sem produto para entregar: abasteça e clique em Confirmar de novo")],
                                     "components": [_botoes_decisao()]})
            onde = (f'Mande o produto em <#{prod["canal_estoque_id"]}> (1 mensagem = 1 entrega)'
                    if prod.get("canal_estoque_id") else "Configure a entrega do produto")
            await dc("POST", f"/channels/{canal}/messages", corpo={
                "content": (f"⚠️ <@{quem}>, acabou o estoque de **{prod['nome']}**. {onde} e clique em **✅ Confirmar** de novo.\n"
                            f'<@{c["comprador"]}>, seu pagamento já foi visto. Só aguarde um pouquinho.'),
                "allowed_mentions": {"parse": [], "users": [quem, c["comprador"]]}})
            return
        entrega = await _entregar(c, prod, item)
        na_dm = entrega["dm"]
        if not entrega["canal"] and not na_dm:
            await dc("POST", f"/channels/{canal}/messages", corpo={"embeds": [{
                "title": "📦 Seu produto", "color": CORES["verde"],
                "description": "Não consegui te mandar DM (ela está fechada), então o produto vai aqui embaixo. "
                               "Copie e guarde antes de fechar o chat."}]})
            for parte in _partes(item):
                await dc("POST", f"/channels/{canal}/messages", corpo={"content": parte, "allowed_mentions": {"parse": []}})
        if origem:
            try:
                await dc("DELETE", f"/channels/{origem[0]}/messages/{origem[1]}", motivo="Produto entregue")
            except ErroDiscord as erro:
                log.warning("Não consegui tirar o item entregue do estoque: %s", erro)
    agora = _agora()
    c.update(status="entregue", aprovado_por=quem, entregue=agora.isoformat())
    _cfg.setdefault("vendas", []).append({
        "txid": c["txid"], "produto": c["produto"], "produto_nome": prod.get("nome"), "valor": c.get("valor"),
        "comprador": c["comprador"], "comprador_nome": c.get("comprador_nome"), "nome_completo": c.get("nome_completo"),
        "aprovado_por": quem, "quando": agora.isoformat()})
    del _cfg["vendas"][:-3000]
    if prod.get("cargo_cliente_id"):
        try:
            await dc("PUT", f'/guilds/{await servidor_id()}/members/{c["comprador"]}/roles/{prod["cargo_cliente_id"]}',
                     motivo=f'Comprou {prod["nome"]}')
        except ErroDiscord as erro:
            log.warning("Não consegui dar o cargo de cliente: %s", erro)
    if entrega["canal"]:
        c["fechar_em"] = (agora + FECHAR_APOS_ENTREGA).isoformat()
        c["canal_entrega"] = entrega["canal"]
        texto = (f'<@{c["comprador"]}> ✅ Pagamento confirmado! Seu produto está no canal privado <#{entrega["canal"]}>'
                 + (" e na sua **DM**" if na_dm else "") + ". Este chat fecha sozinho em 5 minutos.")
        componentes: list[dict] = []
        onde_curto, onde = "num canal privado", f'no canal <#{entrega["canal"]}>'
    elif na_dm:
        c["fechar_em"] = (agora + FECHAR_APOS_ENTREGA).isoformat()
        texto = (f'<@{c["comprador"]}> ✅ Pagamento confirmado! Seu produto foi enviado na sua **DM**. '
                 "Este chat fecha sozinho em 5 minutos.")
        componentes = []
        onde_curto = onde = "na DM"
    else:
        onde_curto = onde = "no chat"
        c["fechar_em"] = (agora + ESPERA_PAGAMENTO).isoformat()
        texto = (f'<@{c["comprador"]}> ✅ Pagamento confirmado! O produto está **logo acima**. '
                 "Depois de copiar, clique em **Fechar chat**.")
        componentes = [_linha(_botao("Fechar chat", "ecop:fechar", 2, "🔒"))]
    await dc("POST", f"/channels/{canal}/messages", corpo={"content": texto, "components": componentes,
                                                           "allowed_mentions": {"parse": [], "users": [c["comprador"]]}})
    await r.editar_original({"embeds": [_com_rodape(embed, f"✅ Confirmado por {nome_quem} • entregue {onde_curto}",
                                                    CORES["verde"])], "components": []})
    await _registrar_venda(prod, (f'🧾 **Venda confirmada** — {prod["nome"]} • {_reais(c.get("valor"))}\n'
                                  f'Comprador: <@{c["comprador"]}> ({c.get("nome_completo")}) • Código `{c["txid"]}` • '
                                  f"Confirmado por <@{quem}> • entregue {onde} • {_fmt(agora)}"))
    await salvar_config()


async def _decidir(r: _Resposta, aprovar: bool) -> None:
    inter = r.inter
    canal = str(inter.channel_id)
    c = _cfg["compras"].get(canal)
    if not c:
        await r.efemera("Esta compra já foi encerrada.")
        return
    prod = _cfg["produtos"].get(c["produto"], {"nome": c["produto"]})
    if not _pode_aprovar(inter, prod):
        await r.efemera(f'Só quem tem o cargo {prod.get("cargo_aprovador_nome") or "Fundador"} pode confirmar ou recusar.')
        return
    if c["status"] != "analise":
        await r.efemera("Essa compra já foi decidida.")
        return
    quem = str(inter.user.id)
    nome_quem = getattr(inter.user, "display_name", None) or inter.user.name
    embed = _embed_da_mensagem(inter)
    if aprovar:
        c["status"] = "entregando"   # trava na hora: dois cliques ao mesmo tempo não entregam duas vezes
        await r.enviar(7, {"embeds": [_com_rodape(embed, f"⏳ Confirmando… ({nome_quem})")], "components": []})
        try:
            await _aprovar(r, canal, c, prod, quem, embed)
        except Exception:
            if c.get("status") == "entregando":
                c["status"] = "analise"
                try:
                    await r.editar_original({"embeds": [_com_rodape(embed, "⚠️ Deu erro na entrega. Tente Confirmar de novo.")],
                                             "components": [_botoes_decisao()]})
                except Exception:
                    pass
            raise
        return
    agora = _agora()
    c.update(status="recusado", recusado_por=quem, fechar_em=(agora + FECHAR_APOS_RECUSA).isoformat())
    await r.enviar(7, {"embeds": [_com_rodape(embed, f"❌ Recusado por {nome_quem}", CORES["vermelho"])], "components": []})
    await dc("POST", f"/channels/{canal}/messages", corpo={
        "content": (f'<@{c["comprador"]}> ❌ A equipe **não confirmou** o seu pagamento. Este chat fecha em 1 minuto.\n'
                    "Se você pagou de verdade, fale com a equipe e mande o comprovante."),
        "allowed_mentions": {"parse": [], "users": [c["comprador"]]}})
    try:
        dm = await dc("POST", "/users/@me/channels", corpo={"recipient_id": c["comprador"]})
        await dc("POST", f'/channels/{dm["id"]}/messages', corpo={"embeds": [{
            "title": "❌ Pagamento não confirmado", "color": CORES["vermelho"],
            "description": (f'Seu pagamento de **{prod["nome"]}** não foi confirmado e o chat de compra foi fechado.\n'
                            f'Se você pagou de verdade, fale com a equipe do servidor e mande o comprovante. '
                            f'Código da compra: `{c["txid"]}`')}]})
    except ErroDiscord:
        pass
    await _registrar_venda(prod, (f'❌ **Pagamento recusado** — {prod["nome"]} • {_reais(c.get("valor"))}\n'
                                  f'Comprador: <@{c["comprador"]}> ({c.get("nome_completo")}) • Código `{c["txid"]}` • '
                                  f"Recusado por <@{quem}> • {_fmt(agora)}"))
    await salvar_config()


async def _clicou_fechar(r: _Resposta, acao: str) -> None:
    inter = r.inter
    if not _cfg_estado["carregada"]:
        asyncio.create_task(garantir_config())
        await r.efemera("O bot acabou de reiniciar. Tente de novo em alguns segundos.")
        return
    canal = str(inter.channel_id)
    c = _cfg["compras"].get(canal)
    if not c:
        await r.efemera("Esta compra já foi encerrada.")
        return
    prod = _cfg["produtos"].get(c["produto"], {"nome": c["produto"]})
    eh_comprador = str(inter.user.id) == c["comprador"]
    eh_equipe = _pode_aprovar(inter, prod)
    if not (eh_comprador or eh_equipe):
        await r.efemera("Você não pode fechar este chat.")
        return
    agora = _agora()
    if acao == "cancelar":
        if c["status"] not in ("aguardando", "analise"):
            await r.efemera("Essa compra não pode mais ser cancelada.")
            return
        if c["status"] == "analise" and not eh_equipe:
            await r.efemera("Você já informou o pagamento. Agora só a equipe pode encerrar esta compra.")
            return
        c.update(status="cancelado", fechar_em=(agora + FECHAR_APOS_CANCELAR).isoformat())
        await r.enviar(4, {"content": f"🗑️ Compra cancelada por <@{inter.user.id}>. Este chat fecha em alguns segundos.",
                           "allowed_mentions": {"parse": []}})
        await registrar(f'🗑️ Compra de **{prod["nome"]}** de <@{c["comprador"]}> cancelada por <@{inter.user.id}>.')
    else:
        c["fechar_em"] = (agora + timedelta(seconds=3)).isoformat()
        await r.enviar(4, {"content": "🔒 Fechando o chat em alguns segundos…", "allowed_mentions": {"parse": []}})
    await salvar_config()


async def fechar_compras() -> None:
    """Apaga os chats de compra encerrados (e os abandonados sem pagamento informado)."""
    if not _cfg_estado["carregada"] or not _cfg.get("compras"):
        return
    agora = _agora()
    mudou = False
    for canal_id, c in list(_cfg["compras"].items()):
        quando = c.get("fechar_em")
        if not quando or datetime.fromisoformat(quando) > agora:
            continue
        try:
            await dc("DELETE", f"/channels/{canal_id}", motivo="Compra encerrada")
        except ErroDiscord as erro:
            if erro.status != 404 and erro.codigo != 10003:
                log.warning("Não consegui fechar o chat de compra %s: %s", canal_id, erro)
                continue
        if c["status"] == "aguardando":
            await registrar(f'⌛ A compra de <@{c["comprador"]}> (código `{c["txid"]}`) expirou sem pagamento informado.')
        _cfg["compras"].pop(canal_id, None)
        mudou = True
    if mudou:
        await salvar_config()


# ───────────────────────── comunidade: tickets, verificação e sorteios ─────────────────────────

FECHAR_TICKET_EM = 5                       # segundos entre "Fechar" e o canal sumir
_CDN_ANEXO = re.compile(r"^https://(?:cdn\.discordapp\.com|media\.discordapp\.net)/(?:ephemeral-)?attachments/", re.I)
_ESTILOS_BOTAO = {"azul": 1, "roxo": 1, "primario": 1, "cinza": 2, "secundario": 2, "verde": 3, "vermelho": 4}
_ticket_lock = asyncio.Lock()
_salvar_tarefa: asyncio.Task | None = None
_tarefas_sorteio: dict[str, asyncio.Task] = {}


def _salvar_depois(segundos: float = 15) -> None:
    """Junta várias mudanças pequenas (ex.: cliques em sorteio) em um salvamento só."""
    global _salvar_tarefa
    if _salvar_tarefa and not _salvar_tarefa.done():
        return

    async def _rodar():
        await asyncio.sleep(segundos)
        try:
            await salvar_config()
        except Exception:
            log.exception("Falha ao salvar a memória")

    _salvar_tarefa = asyncio.create_task(_rodar())


async def _salvar_pendente() -> None:
    """No desligamento: salva na hora o que estava esperando para ser salvo."""
    if _salvar_tarefa and not _salvar_tarefa.done():
        _salvar_tarefa.cancel()
        try:
            await salvar_config()
        except Exception:
            log.exception("Falha ao salvar a memória no desligamento")


def _ts(dt: datetime | str) -> int:
    if isinstance(dt, str):
        dt = datetime.fromisoformat(dt)
    return int(dt.timestamp())


def _emoji_botao(emoji: str | None) -> dict | None:
    if not emoji:
        return None
    s = str(emoji).strip()
    m = re.fullmatch(r"<(a?):(\w+):(\d+)>", s)
    if m:
        return {"name": m.group(2), "id": m.group(3), "animated": bool(m.group(1))}
    return {"name": s}


def _botao_painel(texto: str, custom_id: str, cor: str | None, emoji: str | None) -> dict:
    estilo = _ESTILOS_BOTAO.get(_norm(cor or "azul"), 1)
    b: dict[str, Any] = {"type": 2, "style": estilo, "label": (texto or "Clique aqui")[:80], "custom_id": custom_id[:100]}
    e = _emoji_botao(emoji)
    if e:
        b["emoji"] = e
    return b


def _ref_mensagem(ref: str, canal_padrao: str | None = None) -> tuple[str, str]:
    """Aceita link da mensagem, 'canal_id/mensagem_id' ou só o ID da mensagem (com canal_padrao)."""
    s = str(ref).strip()
    m = re.search(r"channels/(?:\d+|@me)/(\d+)/(\d+)", s) or re.fullmatch(r"(\d{15,22})\D+(\d{15,22})", s)
    if m:
        return m.group(1), m.group(2)
    if re.fullmatch(r"\d{15,22}", s) and canal_padrao:
        return canal_padrao, s
    raise ErroDiscord(f'Não entendi a mensagem "{ref}". Use o link da mensagem (Copiar link) ou "canal_id/mensagem_id".')


async def _buscar_mensagem(ref: str, canal_padrao: str | None = None) -> dict:
    canal_ref = None
    if canal_padrao:
        canal_ref = (await achar_canal(canal_padrao))["id"]
    canal, msg = _ref_mensagem(ref, canal_ref)
    return await dc("GET", f"/channels/{canal}/messages/{msg}")


def _limpar_embed(e: dict) -> dict:
    """Embed recebido da API → embed pronto para reenviar (só os campos que o Discord aceita)."""
    novo: dict[str, Any] = {}
    for k in ("title", "description", "url", "color"):
        if e.get(k) not in (None, ""):
            novo[k] = e[k]
    if e.get("fields"):
        novo["fields"] = [{"name": f.get("name") or "​", "value": f.get("value") or "​",
                           "inline": bool(f.get("inline"))} for f in e["fields"]][:25]
    for k in ("image", "thumbnail"):
        if (e.get(k) or {}).get("url"):
            novo[k] = {"url": e[k]["url"]}
    if (e.get("author") or {}).get("name"):
        a = {"name": e["author"]["name"]}
        for k in ("icon_url", "url"):
            if e["author"].get(k):
                a[k] = e["author"][k]
        novo["author"] = a
    if (e.get("footer") or {}).get("text"):
        f = {"text": e["footer"]["text"]}
        if e["footer"].get("icon_url"):
            f["icon_url"] = e["footer"]["icon_url"]
        novo["footer"] = f
    return novo


def _resumo_componentes(linhas: list[dict]) -> list[dict]:
    saida: list[dict] = []
    for linha in linhas or []:
        for c in linha.get("components", []):
            emoji = c.get("emoji") or {}
            emoji_txt = (f'<{"a" if emoji.get("animated") else ""}:{emoji["name"]}:{emoji["id"]}>' if emoji.get("id")
                         else emoji.get("name"))
            if c.get("type") == 2:
                item = {"tipo": "botão", "texto": c.get("label"), "emoji": emoji_txt,
                        "cor": {1: "azul", 2: "cinza", 3: "verde", 4: "vermelho", 5: "link"}.get(c.get("style"), "?")}
                if c.get("url"):
                    item["link"] = c["url"]
                else:
                    item["custom_id"] = c.get("custom_id")
            elif c.get("type") in (3, 5, 6, 7, 8):
                item = {"tipo": "menu", "texto": c.get("placeholder"), "custom_id": c.get("custom_id"),
                        "opcoes": [{"texto": o.get("label"), "descricao": o.get("description"),
                                    "emoji": (o.get("emoji") or {}).get("name")} for o in c.get("options", [])]}
            else:
                item = {"tipo": f"componente {c.get('type')}"}
            saida.append({k: v for k, v in item.items() if v not in (None, "", [])})
    return saida


async def _refrescar_url(url: str) -> str:
    """Links de anexo do Discord expiram em ~24 h; esta rota devolve um link novo."""
    try:
        r = await dc("POST", "/attachments/refresh-urls", corpo={"attachment_urls": [url]})
        return r["refreshed_urls"][0]["refreshed"] or url
    except Exception:
        return url


async def _baixar_imagem(url: str) -> tuple[bytes, str] | None:
    try:
        r = await cliente_web().get(await _refrescar_url(url))
        r.raise_for_status()
        if not r.content or len(r.content) > 9_500_000:
            return None
        nome = url.split("?")[0].rsplit("/", 1)[-1]
        nome = re.sub(r"[^A-Za-z0-9._-]+", "_", nome)[-60:].strip("._") or "imagem.png"
        if "." not in nome:
            nome += ".png"
        return r.content, nome
    except Exception as erro:
        log.warning("Não consegui baixar a imagem %s: %s", url[:80], erro)
        return None


async def _postar(canal_id: str, payload: dict, editar_id: str | None = None) -> dict:
    """Envia (ou edita) uma mensagem. Imagens que são anexos do Discord (links que expiram) são
    baixadas e reenviadas junto, para nunca quebrarem."""
    payload = deepcopy(payload)
    arquivos: dict[str, tuple[str, bytes, str]] = {}
    anexos: list[dict] = []

    async def trocar(url: str | None) -> str | None:
        if not url or not _CDN_ANEXO.match(url):
            return url
        baixado = await _baixar_imagem(url)
        if not baixado:
            return url
        conteudo, nome = baixado
        nome = f"{len(anexos)}_{nome}"
        anexos.append({"id": len(anexos), "filename": nome})
        tipo = "image/gif" if nome.lower().endswith(".gif") else "image/jpeg" if nome.lower().endswith((".jpg", ".jpeg")) \
            else "image/webp" if nome.lower().endswith(".webp") else "image/png"
        arquivos[f"files[{len(anexos) - 1}]"] = (nome, conteudo, tipo)
        return f"attachment://{nome}"

    for e in payload.get("embeds") or []:
        for k in ("image", "thumbnail"):
            if (e.get(k) or {}).get("url"):
                e[k]["url"] = await trocar(e[k]["url"])
        for k in ("author", "footer"):
            if (e.get(k) or {}).get("icon_url"):
                e[k]["icon_url"] = await trocar(e[k]["icon_url"])
    metodo, rota = ("PATCH", f"/channels/{canal_id}/messages/{editar_id}") if editar_id else ("POST", f"/channels/{canal_id}/messages")
    if arquivos:
        payload["attachments"] = anexos
        return await dc(metodo, rota, dados={"payload_json": json.dumps(payload)}, arquivos=arquivos)
    return await dc(metodo, rota, corpo=payload)


async def _guardar_imagem(url: str | None) -> str | None:
    """Para mensagens que repetem (boas-vindas, agendadas): copia a imagem de um anexo do Discord para o
    canal de memória do agente, assim ela continua existindo mesmo se a mensagem original for apagada."""
    if not url or not _CDN_ANEXO.match(url):
        return url
    baixado = await _baixar_imagem(url)
    if not baixado:
        return url
    conteudo, nome = baixado
    canal = _cfg_estado.get("canal_id") or await _canal_config()
    msg = await dc("POST", f"/channels/{canal}/messages",
                   dados={"payload_json": json.dumps({"content": "🖼️ Imagem usada pelo agente. Não apague.",
                                                      "attachments": [{"id": 0, "filename": nome}]})},
                   arquivos={"files[0]": (nome, conteudo, "application/octet-stream")})
    return msg["attachments"][0]["url"].split("?")[0]


async def _montar_painel(*, copiar_de: str | None, titulo: str | None, descricao: str | None, cor: str | None,
                         imagem_url: str | None, miniatura_url: str | None, rodape: str | None,
                         titulo_padrao: str, descricao_padrao: str) -> tuple[dict, str | None]:
    """Monta o embed do painel: copia o visual de outra mensagem (se pedido) e aplica por cima o que foi passado."""
    embed: dict[str, Any] = {}
    texto: str | None = None
    if copiar_de:
        origem = await _buscar_mensagem(copiar_de)
        if origem.get("embeds"):
            embed = _limpar_embed(origem["embeds"][0])
        texto = (origem.get("content") or "").strip() or None
        if not embed.get("image"):
            img = next((a for a in origem.get("attachments", [])
                        if str(a.get("content_type", "")).startswith("image/")
                        or a.get("filename", "").lower().endswith((".png", ".jpg", ".jpeg", ".gif", ".webp"))), None)
            if img:
                embed["image"] = {"url": img["url"]}
    if titulo is not None:
        embed["title"] = titulo[:256]
    if descricao is not None:
        if len(descricao) > 4096:
            raise ErroDiscord("A descrição passou de 4096 caracteres.")
        embed["description"] = descricao
    if cor:
        embed["color"] = _cor(cor)
    if imagem_url is not None:
        if imagem_url:
            embed["image"] = {"url": imagem_url}
        else:
            embed.pop("image", None)
    if miniatura_url is not None:
        if miniatura_url:
            embed["thumbnail"] = {"url": miniatura_url}
        else:
            embed.pop("thumbnail", None)
    if rodape is not None:
        if rodape:
            embed["footer"] = {"text": rodape[:2048]}
        else:
            embed.pop("footer", None)
    if not embed.get("title") and not embed.get("description"):
        embed["title"], embed["description"] = titulo_padrao, descricao_padrao
    embed.setdefault("color", COR_PADRAO)
    return embed, texto


def _eh_admin(inter: Any) -> bool:
    guild = getattr(inter, "guild", None)
    if guild is not None and getattr(guild, "owner_id", None) == getattr(inter.user, "id", None):
        return True
    return bool(getattr(getattr(inter, "permissions", None), "administrator", False))


def _eh_equipe(inter: Any, painel: dict) -> bool:
    if _eh_admin(inter):
        return True
    equipe = {c["id"] for c in painel.get("cargos_equipe", [])}
    return bool(equipe & _ids_cargos(inter.user))


async def _criar_canal_privado(nome: str, perms: list[dict], categoria_id: str | None, topico: str, motivo: str) -> dict:
    gid = await servidor_id()
    corpo: dict[str, Any] = {"name": nome[:100], "type": 0, "permission_overwrites": perms, "topic": topico[:1024]}
    if categoria_id:
        corpo["parent_id"] = categoria_id
    try:
        return await dc("POST", f"/guilds/{gid}/channels", corpo=corpo, motivo=motivo)
    except ErroDiscord as erro:
        if erro.codigo != 50035:
            raise
    corpo["name"] = re.sub(r"[^a-z0-9_-]+", "-", _slug(nome, 90)).strip("-") or "ticket"
    try:
        return await dc("POST", f"/guilds/{gid}/channels", corpo=corpo, motivo=motivo)
    except ErroDiscord as erro:
        if erro.codigo != 50035 or "parent_id" not in corpo:
            raise
    corpo.pop("parent_id", None)  # categoria cheia (50 canais): cria fora dela
    return await dc("POST", f"/guilds/{gid}/channels", corpo=corpo, motivo=motivo)


# ── tickets ──

def _botoes_ticket(assumido: bool) -> dict:
    botoes = [_botao("Fechar ticket", "ecot:fechar", 4, "🔒")]
    if not assumido:
        botoes.append(_botao("Assumir", "ecot:assumir", 2, "🙋"))
    return _linha(*botoes)


async def _abrir_ticket(r: _Resposta, pid: str, escolha: str | None) -> None:
    inter = r.inter
    await r.adiar()
    await exigir_config()
    painel = _cfg["paineis"].get(pid)
    if not painel or painel.get("tipo") != "ticket":
        await r.efemera("Este painel não está mais ativo. Avise a equipe.")
        return
    motivo = None
    if escolha is not None:
        try:
            motivo = (painel.get("motivos") or [])[int(escolha)]
        except (ValueError, IndexError):
            motivo = str(escolha)
    uid = str(inter.user.id)
    nome = getattr(inter.user, "display_name", None) or inter.user.name
    async with _ticket_lock:
        for canal_id, t in list(_cfg["tickets"].items()):
            if t["dono"] == uid and t.get("painel") == pid and t.get("status") == "aberto":
                if await _canal_existe(canal_id):
                    await r.efemera(f"Você já tem um ticket aberto: <#{canal_id}>")
                    return
                _cfg["tickets"].pop(canal_id, None)
        _cfg["contador_tickets"] = int(_cfg.get("contador_tickets") or 0) + 1
        numero = _cfg["contador_tickets"]
        gid, bot = await servidor_id(), await eu()
        acesso = VER | ENVIAR | HISTORICO | ANEXAR | EMBED_LINKS
        perms: list[dict[str, Any]] = [
            {"id": gid, "type": 0, "allow": "0", "deny": str(VER)},
            {"id": uid, "type": 1, "allow": str(acesso), "deny": "0"},
            {"id": bot["id"], "type": 1, "allow": str(acesso | GERENCIAR_MSG), "deny": "0"},
        ] + [{"id": c["id"], "type": 0, "allow": str(acesso | GERENCIAR_MSG), "deny": "0"} for c in painel.get("cargos_equipe", [])]
        prefixo = painel.get("prefixo") or "🎫・ticket"
        canal = await _criar_canal_privado(
            f"{prefixo}-{_slug(nome, 30) or _slug(inter.user.name, 30) or numero}", perms, painel.get("categoria_id"),
            f"Ticket #{numero:04d} de <@{uid}>" + (f" • {motivo}" if motivo else "") + " • só você e a equipe veem",
            f"Ticket de {inter.user.name}")
        _cfg["tickets"][canal["id"]] = {"painel": pid, "dono": uid, "dono_nome": nome, "numero": numero,
                                        "motivo": motivo, "aberto": _agora().isoformat(), "status": "aberto"}
    abertura = painel.get("mensagem_abertura") or (
        "Olá, {usuario}! Este canal é **privado**: só você e a equipe conseguem ver.\n\n"
        "Explique com detalhes o que você precisa que a equipe já vem te atender.")
    descricao = _preencher(abertura, {"usuario": f"<@{uid}>", "usuário": f"<@{uid}>", "nome": nome})
    if motivo:
        descricao += f"\n\n📌 **Assunto:** {motivo}"
    equipe = [c["id"] for c in painel.get("cargos_equipe", [])] if painel.get("avisar_equipe", True) else []
    try:
        await dc("POST", f'/channels/{canal["id"]}/messages', corpo={
            "content": " ".join([f"<@{uid}>"] + [f"<@&{c}>" for c in equipe]),
            "embeds": [{"title": f"🎫 Ticket #{numero:04d}", "description": descricao, "color": painel.get("cor") or COR_PADRAO,
                        "footer": {"text": "Para encerrar, clique em 🔒 Fechar ticket"}}],
            "components": [_botoes_ticket(False)],
            "allowed_mentions": {"parse": [], "users": [uid], "roles": equipe}})
    finally:
        await salvar_config()
    await r.efemera(f'✅ Seu ticket foi aberto: <#{canal["id"]}>')
    await registrar(f'🎫 <@{uid}> abriu o ticket #{numero:04d} em <#{canal["id"]}>' + (f" ({motivo})." if motivo else "."))


async def _assumir_ticket(r: _Resposta) -> None:
    inter = r.inter
    t = _cfg["tickets"].get(str(inter.channel_id))
    if not t or t.get("status") != "aberto":
        await r.efemera("Este ticket já foi encerrado.")
        return
    painel = _cfg["paineis"].get(t.get("painel"), {})
    if not _eh_equipe(inter, painel):
        await r.efemera("Só a equipe pode assumir tickets.")
        return
    if t.get("assumido_por"):
        await r.efemera(f'Este ticket já está com <@{t["assumido_por"]}>.')
        return
    quem = str(inter.user.id)
    nome_quem = getattr(inter.user, "display_name", None) or inter.user.name
    t["assumido_por"], t["assumido_nome"] = quem, nome_quem
    embed = _com_rodape(_embed_da_mensagem(inter), f"🙋 Atendido por {nome_quem} • para encerrar, clique em 🔒 Fechar ticket")
    await r.enviar(7, {"embeds": [embed], "components": [_botoes_ticket(True)]})
    await dc("POST", f"/channels/{inter.channel_id}/messages", corpo={
        "content": f'🙋 <@{quem}> assumiu o seu atendimento, <@{t["dono"]}>.',
        "allowed_mentions": {"parse": [], "users": [t["dono"]]}})
    await salvar_config()


async def _pedir_confirmacao_fechar(r: _Resposta) -> None:
    inter = r.inter
    t = _cfg["tickets"].get(str(inter.channel_id))
    if not t or t.get("status") != "aberto":
        await r.efemera("Este ticket já está sendo encerrado.")
        return
    painel = _cfg["paineis"].get(t.get("painel"), {})
    if str(inter.user.id) != t["dono"] and not _eh_equipe(inter, painel):
        await r.efemera("Só quem abriu o ticket ou a equipe pode fechar.")
        return
    await r.enviar(4, {"content": "Tem certeza que quer **fechar** este ticket? O canal será apagado e o histórico fica salvo.",
                       "flags": 64, "components": [_linha(_botao("Sim, fechar", "ecot:confirmar", 4, "🔒"))]})


async def _historico_ticket(canal_id: str) -> tuple[bytes, int]:
    msgs: list[dict] = []
    antes = None
    for _ in range(30):  # até 3000 mensagens
        params: dict[str, Any] = {"limit": 100}
        if antes:
            params["before"] = antes
        lote = await dc("GET", f"/channels/{canal_id}/messages", params=params)
        if not lote:
            break
        msgs.extend(lote)
        antes = lote[-1]["id"]
        if len(lote) < 100:
            break
    linhas = []
    for m in reversed(msgs):
        autor = m["author"].get("global_name") or m["author"]["username"]
        partes = [m.get("content") or ""]
        for e in m.get("embeds", []):
            partes.append(" | ".join(x for x in (e.get("title"), e.get("description")) if x))
        partes += [a["url"].split("?")[0] for a in m.get("attachments", [])]
        texto = "\n    ".join(p for p in partes if p) or "(sem texto)"
        linhas.append(f"[{_fmt(m['timestamp'])}] {autor} (@{m['author']['username']}): {texto}")
    return ("\n".join(linhas) + "\n").encode(), len(msgs)


async def encerrar_ticket(canal_id: str, quem: str | None, quem_nome: str) -> None:
    """Salva o histórico, avisa o dono e apaga o canal do ticket."""
    t = _cfg["tickets"].get(canal_id)
    if not t or t.get("status") == "fechando":
        return
    t["status"] = "fechando"
    t["fechar_em"] = (_agora() + timedelta(seconds=FECHAR_TICKET_EM)).isoformat()
    t["fechado_por"] = quem
    await salvar_config()
    painel = _cfg["paineis"].get(t.get("painel"), {})
    try:
        historico, total = await _historico_ticket(canal_id)
    except ErroDiscord as erro:
        log.warning("Não consegui ler o histórico do ticket %s: %s", canal_id, erro)
        historico, total = b"", 0
    nome_arquivo = f'ticket-{int(t.get("numero") or 0):04d}-{_slug(t.get("dono_nome"), 20) or t["dono"]}.txt'
    resumo = {"title": f'🎫 Ticket #{int(t.get("numero") or 0):04d} fechado', "color": CORES["cinza"], "description": (
        f'👤 **Aberto por:** <@{t["dono"]}>\n' + (f'📌 **Assunto:** {t["motivo"]}\n' if t.get("motivo") else "")
        + (f'🙋 **Atendido por:** <@{t["assumido_por"]}>\n' if t.get("assumido_por") else "")
        + f"🔒 **Fechado por:** {f'<@{quem}>' if quem else quem_nome}\n"
        + f'🕐 **Aberto em:** {_fmt(t.get("aberto"))} • **Fechado em:** {_fmt(_agora())}\n💬 **Mensagens:** {total}')}
    destino = painel.get("canal_historico_id") or ((_cfg.get("logs") or {}).get("canal_id") if (_cfg.get("logs") or {}).get("ativo") else None)
    if destino and historico:
        try:
            await dc("POST", f"/channels/{destino}/messages", dados={"payload_json": json.dumps({
                "embeds": [resumo], "allowed_mentions": {"parse": []}, "attachments": [{"id": 0, "filename": nome_arquivo}]})},
                arquivos={"files[0]": (nome_arquivo, historico, "text/plain")})
        except ErroDiscord as erro:
            log.warning("Não consegui salvar o histórico do ticket: %s", erro)
    try:
        dm = await dc("POST", "/users/@me/channels", corpo={"recipient_id": t["dono"]})
        aviso = {"title": "🎫 Seu ticket foi fechado", "color": CORES["cinza"],
                 "description": "Obrigado pelo contato! Se precisar de novo, é só abrir outro ticket no servidor."}
        if historico:
            await dc("POST", f'/channels/{dm["id"]}/messages', dados={"payload_json": json.dumps({
                "embeds": [aviso], "attachments": [{"id": 0, "filename": nome_arquivo}]})},
                arquivos={"files[0]": (nome_arquivo, historico, "text/plain")})
        else:
            await dc("POST", f'/channels/{dm["id"]}/messages', corpo={"embeds": [aviso]})
    except ErroDiscord:
        pass
    await asyncio.sleep(max(0.0, (datetime.fromisoformat(t["fechar_em"]) - _agora()).total_seconds()))
    await _apagar_ticket(canal_id)


async def _apagar_ticket(canal_id: str) -> None:
    t = _cfg["tickets"].get(canal_id)
    try:
        await dc("DELETE", f"/channels/{canal_id}", motivo="Ticket fechado")
    except ErroDiscord as erro:
        if erro.status != 404 and erro.codigo != 10003:
            log.warning("Não consegui apagar o ticket %s: %s", canal_id, erro)
            return
    if t:
        _cfg["tickets"].pop(canal_id, None)
        await registrar(f'🔒 Ticket #{int(t.get("numero") or 0):04d} de <@{t["dono"]}> fechado.')
        await salvar_config()


async def _confirmar_fechar(r: _Resposta) -> None:
    inter = r.inter
    canal_id = str(inter.channel_id)
    t = _cfg["tickets"].get(canal_id)
    if not t or t.get("status") != "aberto":
        await r.efemera("Este ticket já está sendo encerrado.")
        return
    painel = _cfg["paineis"].get(t.get("painel"), {})
    if str(inter.user.id) != t["dono"] and not _eh_equipe(inter, painel):
        await r.efemera("Só quem abriu o ticket ou a equipe pode fechar.")
        return
    await r.enviar(7, {"content": "🔒 Fechando…", "components": []})
    nome = getattr(inter.user, "display_name", None) or inter.user.name
    await dc("POST", f"/channels/{canal_id}/messages", corpo={
        "content": f"🔒 Ticket fechado por <@{inter.user.id}>. O histórico foi salvo e este canal some em {FECHAR_TICKET_EM} segundos.",
        "allowed_mentions": {"parse": []}})
    await encerrar_ticket(canal_id, str(inter.user.id), nome)


async def limpar_tickets() -> None:
    """Termina de fechar tickets que ficaram pela metade (ex.: o bot reiniciou) e esquece canais apagados à mão."""
    if not _cfg_estado["carregada"] or not _cfg.get("tickets"):
        return
    agora = _agora()
    for canal_id, t in list(_cfg["tickets"].items()):
        if t.get("status") == "fechando" and t.get("fechar_em") and datetime.fromisoformat(t["fechar_em"]) <= agora - timedelta(seconds=30):
            await _apagar_ticket(canal_id)


# ── verificação ──

async def _verificar(r: _Resposta, pid: str) -> None:
    inter = r.inter
    await r.adiar()
    await exigir_config()
    painel = _cfg["paineis"].get(pid)
    if not painel or painel.get("tipo") != "verificacao":
        await r.efemera("Este painel não está mais ativo. Avise a equipe.")
        return
    uid = str(inter.user.id)
    gid = await servidor_id()
    cargos = _ids_cargos(inter.user)
    if painel["cargo_id"] in cargos and not (painel.get("tirar_cargo_id") and painel["tirar_cargo_id"] in cargos):
        await r.efemera("✅ Você já está verificado!")
        return
    await dc("PUT", f'/guilds/{gid}/members/{uid}/roles/{painel["cargo_id"]}', motivo="Verificação")
    if painel.get("tirar_cargo_id") and painel["tirar_cargo_id"] in cargos:
        try:
            await dc("DELETE", f'/guilds/{gid}/members/{uid}/roles/{painel["tirar_cargo_id"]}', motivo="Verificação")
        except ErroDiscord as erro:
            log.warning("Não consegui tirar o cargo de não verificado: %s", erro)
    await r.efemera(painel.get("mensagem_sucesso") or "✅ Verificado! Agora você tem acesso ao servidor. Seja bem-vindo(a)!")
    await registrar(f'✅ <@{uid}> se verificou e ganhou o cargo **{painel.get("cargo_nome")}**.')


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


async def _clique_loja(r: _Resposta, tipo: int, acao: str, partes: list[str]) -> None:
    if tipo == 5:
        if acao == "modal_pago":
            await _modal_pago(r)
    elif acao == "comprar":
        await _clicou_comprar(r, partes[2] if len(partes) > 2 else "")
    elif acao == "pago":
        await _clicou_pago(r)
    elif acao in ("aprovar", "recusar"):
        await _decidir(r, acao == "aprovar")
    elif acao in ("cancelar", "fechar"):
        await _clicou_fechar(r, acao)
    elif acao in ("fechar_entrega", "fechar_entrega_ok"):
        await _clicou_fechar_entrega(r, acao == "fechar_entrega_ok")


async def _clique_ticket(r: _Resposta, acao: str, partes: list[str], dados: dict) -> None:
    if acao == "abrir":
        valores = dados.get("values") or []
        await _abrir_ticket(r, partes[2] if len(partes) > 2 else "", valores[0] if valores else None)
        return
    if not _cfg_estado["carregada"]:
        asyncio.create_task(garantir_config())
        await r.efemera("O bot acabou de reiniciar. Tente de novo em alguns segundos.")
        return
    if acao == "assumir":
        await _assumir_ticket(r)
    elif acao == "fechar":
        await _pedir_confirmacao_fechar(r)
    elif acao == "confirmar":
        await _confirmar_fechar(r)


async def ao_interagir(inter: Any) -> None:
    dados = inter.data or {}
    if getattr(inter.type, "value", inter.type) in (2, 4):   # comando de barra / autocompletar
        await ao_comando(inter, getattr(inter.type, "value", inter.type), dados)
        return
    cid = str(dados.get("custom_id") or "")
    partes = cid.split(":")
    prefixo = partes[0]
    if prefixo not in ("ecop", "ecot", "ecov", "ecos"):
        return
    acao = partes[1] if len(partes) > 1 else ""
    tipo = getattr(inter.type, "value", inter.type)   # 3 = botão/menu, 5 = formulário
    r = _Resposta(inter)
    try:
        if prefixo == "ecop":
            await _clique_loja(r, tipo, acao, partes)
        elif prefixo == "ecot":
            await _clique_ticket(r, acao, partes, dados)
        elif prefixo == "ecov":
            await _verificar(r, acao)
        elif prefixo == "ecos" and acao in ("entrar", "sair"):
            await _clique_sorteio(r, acao, partes[2] if len(partes) > 2 else "")
    except Exception as erro:
        log.exception("Falha no botão %s", cid)
        texto = str(erro) if isinstance(erro, ErroDiscord) else "Deu um erro aqui. Tente de novo ou chame a equipe."
        try:
            await r.efemera(f"⚠️ {texto}")
        except Exception:
            pass


def _novo_cliente(privilegiadas: bool):
    intents = discord.Intents.none()
    intents.guilds = True
    intents.guild_messages = True
    intents.guild_reactions = True
    if privilegiadas:
        intents.members = True
        intents.message_content = True
    cliente = discord.Client(intents=intents, max_messages=None, chunk_guilds_at_startup=False,
                             member_cache_flags=discord.MemberCacheFlags.none())

    def _do_servidor(guild) -> bool:
        return guild is not None and (not _servidor or str(guild.id) == _servidor)

    @cliente.event
    async def on_ready():
        servidores = ", ".join(f"{g.name} (ID {g.id})" for g in cliente.guilds) or "nenhum"
        _bot_estado["status"] = f"conectado como {cliente.user}"
        _bot_estado["servidores"] = servidores
        log.info("Gateway conectado como %s. Servidores do bot: %s", cliente.user, servidores)
        if _servidor and not any(str(g.id) == _servidor for g in cliente.guilds):
            log.warning("O bot NÃO está no servidor GUILD_ID=%s. Convide o bot para o ECO PULSE ou corrija GUILD_ID.", _servidor)
        asyncio.create_task(registrar_comandos(str(getattr(cliente, "application_id", None) or cliente.user.id)))

    @cliente.event
    async def on_member_join(member):
        if _do_servidor(member.guild):
            await ao_entrar(str(member.id), member.display_name, member.guild.name, member.guild.member_count, member.bot)

    @cliente.event
    async def on_member_remove(member):
        if _do_servidor(member.guild):
            await ao_sair(str(member.id), member.display_name, member.guild.name, member.guild.member_count)

    @cliente.event
    async def on_message(message):
        if message.author.bot or not _do_servidor(message.guild) or not message.content:
            return
        try:
            await ao_mensagem(message.content, str(message.channel.id), str(message.id),
                              str(message.author.id), message.author.display_name)
        except ErroDiscord as erro:
            log.warning("Resposta automática falhou: %s", erro)

    async def _reacao(payload, adicionou: bool):
        if payload.guild_id is None or (cliente.user and payload.user_id == cliente.user.id):
            return
        if _servidor and str(payload.guild_id) != _servidor:
            return
        e = payload.emoji
        chave = f"id:{e.id}" if e.id else (e.name or "").replace("️", "")
        await ao_reagir(str(payload.message_id), chave, str(payload.user_id), adicionou)

    @cliente.event
    async def on_raw_reaction_add(payload):
        await _reacao(payload, True)

    @cliente.event
    async def on_raw_reaction_remove(payload):
        await _reacao(payload, False)

    @cliente.event
    async def on_interaction(interaction):
        if interaction.guild_id is None or (_servidor and str(interaction.guild_id) != _servidor):
            return
        if interaction.type not in (discord.InteractionType.component, discord.InteractionType.modal_submit,
                                    discord.InteractionType.application_command, discord.InteractionType.autocomplete):
            return
        await ao_interagir(interaction)

    return cliente


async def rodar_bot() -> None:
    global _bot
    if discord is None:
        _bot_estado["status"] = "desligado: biblioteca discord.py não instalada (confira o requirements.txt)"
        return
    if not TOKEN:
        _bot_estado["status"] = "desligado: falta DISCORD_TOKEN"
        return
    for privilegiadas in (True, False):
        _bot = _novo_cliente(privilegiadas)
        _bot_estado["intents_privilegiadas"] = privilegiadas
        _bot_estado["status"] = "conectando"
        try:
            await _bot.start(TOKEN)
            return
        except discord.PrivilegedIntentsRequired:
            _bot_estado["aviso"] = ("Ative SERVER MEMBERS INTENT e MESSAGE CONTENT INTENT no Developer Portal → Bot. "
                                    "Sem elas, boas-vindas, despedida e respostas automáticas não funcionam.")
            log.warning(_bot_estado["aviso"])
            try:
                await _bot.close()
            except Exception:
                pass
        except discord.LoginFailure:
            _bot_estado["status"] = "desligado: token inválido"
            return
        except asyncio.CancelledError:
            raise
        except Exception as erro:
            _bot_estado["status"] = f"desligado: {type(erro).__name__}: {erro}"
            log.exception("Gateway caiu")
            return


# ───────────────────────── servidor MCP ─────────────────────────

mcp = MCPServer(
    name="ECO PULSE",
    instructions=(
        "Agente do servidor de Discord ECO PULSE. Canais, cargos e membros aceitam ID, menção ou nome. "
        "Horários são de Brasília. Antes de qualquer ação que apaga, expulsa ou bane, confirme com o usuário "
        "e só então chame de novo com confirmado=true. Em boas-vindas e respostas automáticas, os textos "
        "aceitam {usuario} (menciona a pessoa), {nome}, {servidor} e {membros}. "
        "As automações rodam no próprio bot, mesmo com o Claude fechado. Para trocar painéis de outro bot "
        "(ticket, verificação, sorteio), leia com ver_mensagem e publique de novo com copiar_de apontando para a mensagem antiga."
    ),
    version=VERSAO,
)

LEITURA = ToolAnnotations(readOnlyHint=True, destructiveHint=False)
DESTRUTIVA = ToolAnnotations(readOnlyHint=False, destructiveHint=True)


# ── canais ──

@mcp.tool(annotations=LEITURA)
async def listar_canais() -> dict:
    """Lista todos os canais e categorias do servidor, com id, nome, tipo e categoria."""
    canais = await _canais()
    gid = await servidor_id()
    cats = {c["id"]: c for c in canais if c["type"] == 4}

    def ordem(c):
        voz = 1 if c["type"] in (2, 13) else 0
        if c["type"] == 4:
            return (c["position"], 0, 0, 0)
        pai = cats.get(c.get("parent_id"))
        return (pai["position"] if pai else -1, 1, voz, c["position"])

    saida = []
    for c in sorted(canais, key=ordem):
        item: dict[str, Any] = {"id": c["id"], "nome": c["name"], "tipo": TIPOS.get(c["type"], str(c["type"]))}
        if c["type"] != 4 and c.get("parent_id") in cats:
            item["categoria"] = cats[c["parent_id"]]["name"]
        todos = next((o for o in c.get("permission_overwrites", []) if o["id"] == gid), None)
        if todos and int(todos["deny"]) & VER:
            item["privado"] = True
        saida.append(item)
    return {"canais": saida}


@mcp.tool()
async def criar_canal(nome: str, tipo: str = "texto", categoria_id: str | None = None, topico: str | None = None,
                      privado: bool = False, cargos_com_acesso: list[str] | None = None,
                      modo_lento_segundos: int | None = None) -> dict:
    """Cria um canal. tipo: texto, voz, categoria, anuncios, forum ou palco. categoria_id aceita ID ou nome.
    privado=true esconde de todos e libera só para cargos_com_acesso (nomes ou IDs)."""
    t = TIPOS_CRIAR.get(_norm(tipo))
    if t is None:
        raise ErroDiscord(f'Tipo "{tipo}" inválido. Use: texto, voz, categoria, anuncios, forum ou palco.')
    gid = await servidor_id()
    corpo: dict[str, Any] = {"name": nome, "type": t}
    if topico and t in (0, 5, 15):
        corpo["topic"] = topico[:1024]
    if categoria_id and t != 4:
        corpo["parent_id"] = (await achar_categoria(categoria_id))["id"]
    if modo_lento_segundos is not None and t in (0, 15):
        corpo["rate_limit_per_user"] = max(0, min(21600, int(modo_lento_segundos)))
    if privado or cargos_com_acesso:
        acesso = VER | ENVIAR | HISTORICO | CONECTAR | FALAR
        bot = await eu()
        sobre = [{"id": gid, "type": 0, "allow": "0", "deny": str(VER)},
                 {"id": bot["id"], "type": 1, "allow": str(acesso), "deny": "0"}]
        for ref in cargos_com_acesso or []:
            cargo = await achar_cargo(ref)
            sobre.append({"id": cargo["id"], "type": 0, "allow": str(acesso), "deny": "0"})
        corpo["permission_overwrites"] = sobre
    canal = await dc("POST", f"/guilds/{gid}/channels", corpo=corpo, motivo="Agente ECO PULSE")
    return {"ok": True, "id": canal["id"], "nome": canal["name"], "tipo": TIPOS.get(canal["type"]),
            "link": _link_canal(gid, canal["id"])}


@mcp.tool()
async def editar_canal(canal_id: str, nome: str | None = None, topico: str | None = None,
                       categoria_id: str | None = None, posicao: int | None = None,
                       modo_lento_segundos: int | None = None, nsfw: bool | None = None) -> dict:
    """Renomeia, muda o tópico, move de categoria (categoria_id = ID/nome, ou "nenhuma" para tirar),
    muda a posição, o modo lento (segundos, 0 desliga) ou a marcação +18 de um canal."""
    canal = await achar_canal(canal_id)
    corpo: dict[str, Any] = {}
    if nome is not None:
        corpo["name"] = nome
    if topico is not None:
        corpo["topic"] = topico[:1024]
    if categoria_id is not None:
        corpo["parent_id"] = None if _norm(categoria_id) in ("", "nenhuma", "semcategoria", "nada", "none") \
            else (await achar_categoria(categoria_id))["id"]
    if posicao is not None:
        corpo["position"] = posicao
    if modo_lento_segundos is not None:
        corpo["rate_limit_per_user"] = max(0, min(21600, int(modo_lento_segundos)))
    if nsfw is not None:
        corpo["nsfw"] = nsfw
    if not corpo:
        raise ErroDiscord("Nada para mudar: passe nome, topico, categoria_id, posicao, modo_lento_segundos ou nsfw.")
    novo = await dc("PATCH", f'/channels/{canal["id"]}', corpo=corpo, motivo="Agente ECO PULSE")
    return {"ok": True, "id": novo["id"], "nome": novo["name"], "mudou": list(corpo)}


@mcp.tool(annotations=DESTRUTIVA)
async def apagar_canal(canal_id: str, confirmado: bool = False) -> str:
    """Apaga um canal ou categoria. Só chame com confirmado=true depois que o usuário confirmar."""
    canal = await achar_canal(canal_id)
    if canal["id"] == _cfg_estado.get("canal_id") or canal["name"] == NOME_CANAL_CONFIG:
        raise ErroDiscord("Esse canal guarda a memória das automações do agente; não vou apagá-lo.")
    rotulo = f'{"a categoria" if canal["type"] == 4 else "o canal"} #{canal["name"]} ({canal["id"]})'
    if not confirmado:
        return f"⚠️ Nada foi apagado. Confirme com o usuário que ele quer apagar {rotulo} — não tem volta. Depois chame de novo com confirmado=true."
    await dc("DELETE", f'/channels/{canal["id"]}', motivo="Agente ECO PULSE")
    await registrar(f'🗑️ O agente apagou {rotulo}.')
    extra = " Os canais que estavam dentro dela ficaram sem categoria." if canal["type"] == 4 else ""
    return f"✅ Apaguei {rotulo}.{extra}"


@mcp.tool()
async def permissoes_canal(canal_id: str, alvo: str, permitir: list[str] | None = None,
                           negar: list[str] | None = None, herdar: list[str] | None = None,
                           limpar_tudo: bool = False) -> dict:
    """Muda o que um cargo (ou @everyone, ou um membro) pode fazer em um canal.
    Permissões: ver_canal, enviar_mensagens, ler_historico, reagir, anexar_arquivos, inserir_links,
    mencionar_todos, gerenciar_mensagens, conectar, falar, criar_threads, enviar_em_threads, usar_comandos,
    criar_enquetes... herdar volta a permissão para o padrão do servidor. limpar_tudo remove a regra desse alvo."""
    canal = await achar_canal(canal_id)
    alvo_id, tipo, rotulo = await achar_alvo_permissao(alvo)
    if limpar_tudo:
        await dc("DELETE", f'/channels/{canal["id"]}/permissions/{alvo_id}', motivo="Agente ECO PULSE")
        return {"ok": True, "canal": canal["name"], "alvo": rotulo, "regra": "removida (volta ao padrão)"}
    p, n, h = _bits(permitir), _bits(negar), _bits(herdar)
    if not (p or n or h):
        raise ErroDiscord("Passe pelo menos uma permissão em permitir, negar ou herdar.")
    allow, deny = await _sobrescrever(canal, alvo_id, tipo, p, n, h, motivo="Agente ECO PULSE")
    return {"ok": True, "canal": canal["name"], "alvo": rotulo,
            "permitido": _nomes_perm(allow), "negado": _nomes_perm(deny)}


@mcp.tool()
async def trancar_canal(canal_id: str, trancar: bool = True, motivo: str | None = None) -> str:
    """Tranca (ninguém sem cargo especial escreve) ou destranca um canal de texto."""
    canal = await achar_canal(canal_id)
    gid = await servidor_id()
    bits = ENVIAR | PERMISSOES["enviar_em_threads"] | PERMISSOES["criar_threads"]
    if trancar:
        await _sobrescrever(canal, gid, 0, negar=bits, motivo=motivo or "Canal trancado pelo agente")
        await dc("POST", f'/channels/{canal["id"]}/messages', corpo={
            "embeds": [{"color": CORES["vermelho"], "description": f"🔒 Canal trancado.{' Motivo: ' + motivo if motivo else ''}"}]})
        return f'🔒 #{canal["name"]} trancado.'
    await _sobrescrever(canal, gid, 0, herdar=bits, motivo=motivo or "Canal destrancado pelo agente")
    await dc("POST", f'/channels/{canal["id"]}/messages', corpo={
        "embeds": [{"color": COR_PADRAO, "description": "🔓 Canal destrancado."}]})
    return f'🔓 #{canal["name"]} destrancado.'


# ── mensagens ──

@mcp.tool()
async def enviar_mensagem(canal_id: str, texto: str | None = None, titulo: str | None = None,
                          descricao: str | None = None, cor: str | None = None, imagem_url: str | None = None,
                          miniatura_url: str | None = None, rodape: str | None = None,
                          botao_texto: str | None = None, botao_link: str | None = None,
                          mencionar_todos: bool = False, responder_a: str | None = None) -> dict:
    """Envia uma mensagem em um canal. Use texto para mensagem simples e/ou titulo + descricao para um
    embed (caixa colorida; cor = #RRGGBB ou verde, azul, vermelho, amarelo, roxo, laranja, rosa, dourado...).
    botao_link adiciona um botão com link. mencionar_todos=true permite @everyone/@here funcionar.
    responder_a = ID de uma mensagem para responder."""
    canal = await achar_canal(canal_id, tipos=TIPOS_MENSAGEM)
    payload = montar_mensagem(texto, titulo, descricao, cor, imagem_url, miniatura_url, rodape,
                              botao_texto, botao_link, mencionar_todos)
    if responder_a:
        payload["message_reference"] = {"message_id": _id(responder_a) or responder_a, "fail_if_not_exists": False}
    msg = await dc("POST", f'/channels/{canal["id"]}/messages', corpo=payload)
    return {"ok": True, "mensagem_id": msg["id"], "canal": canal["name"],
            "link": _link_canal(await servidor_id(), canal["id"], msg["id"])}


@mcp.tool()
async def editar_mensagem(canal_id: str, mensagem_id: str, texto: str | None = None, titulo: str | None = None,
                          descricao: str | None = None, cor: str | None = None, imagem_url: str | None = None,
                          rodape: str | None = None, botao_texto: str | None = None, botao_link: str | None = None,
                          remover_embed: bool = False) -> dict:
    """Edita uma mensagem enviada pelo bot. Só os campos passados mudam; texto="" apaga o texto."""
    canal = await achar_canal(canal_id, tipos=TIPOS_MENSAGEM)
    atual = await dc("GET", f'/channels/{canal["id"]}/messages/{mensagem_id}')
    if atual["author"]["id"] != (await eu())["id"]:
        raise ErroDiscord("Só consigo editar mensagens enviadas pelo próprio bot.")
    corpo: dict[str, Any] = {}
    if texto is not None:
        if len(texto) > 2000:
            raise ErroDiscord("O texto passou de 2000 caracteres.")
        corpo["content"] = texto
    if remover_embed:
        corpo["embeds"] = []
    elif any(v is not None for v in (titulo, descricao, cor, imagem_url, rodape)):
        embed = dict(atual["embeds"][0]) if atual.get("embeds") else {"color": COR_PADRAO}
        for chave in ("type", "video", "provider"):
            embed.pop(chave, None)
        if titulo is not None:
            embed["title"] = titulo[:256]
        if descricao is not None:
            embed["description"] = descricao[:4096]
        if cor is not None:
            embed["color"] = _cor(cor)
        if imagem_url is not None:
            embed["image"] = {"url": imagem_url} if imagem_url else None
        if rodape is not None:
            embed["footer"] = {"text": rodape} if rodape else None
        corpo["embeds"] = [{k: v for k, v in embed.items() if v is not None}]
    if botao_link is not None:
        corpo["components"] = [] if not botao_link else [{"type": 1, "components": [
            {"type": 2, "style": 5, "label": (botao_texto or "Abrir")[:80], "url": botao_link}]}]
    if not corpo:
        raise ErroDiscord("Nada para mudar.")
    await dc("PATCH", f'/channels/{canal["id"]}/messages/{mensagem_id}', corpo=corpo)
    return {"ok": True, "mensagem_id": mensagem_id, "mudou": list(corpo)}


@mcp.tool(annotations=DESTRUTIVA)
async def apagar_mensagem(canal_id: str, mensagem_id: str) -> str:
    """Apaga uma mensagem."""
    canal = await achar_canal(canal_id, tipos=TIPOS_MENSAGEM)
    await dc("DELETE", f'/channels/{canal["id"]}/messages/{mensagem_id}', motivo="Agente ECO PULSE")
    return f'✅ Mensagem {mensagem_id} apagada de #{canal["name"]}.'


@mcp.tool(annotations=LEITURA)
async def ler_mensagens(canal_id: str, limite: int = 20) -> dict:
    """Lê as últimas mensagens de um canal (até 100), da mais antiga para a mais nova."""
    canal = await achar_canal(canal_id, tipos=TIPOS_MENSAGEM)
    msgs = await dc("GET", f'/channels/{canal["id"]}/messages', params={"limit": max(1, min(100, limite))})
    saida, vazias = [], 0
    for m in reversed(msgs):
        item: dict[str, Any] = {"id": m["id"], "autor": m["author"].get("global_name") or m["author"]["username"],
                                "autor_id": m["author"]["id"], "quando": _fmt(m["timestamp"]),
                                "texto": (m.get("content") or "")[:600]}
        if m.get("embeds"):
            e0 = m["embeds"][0]
            item["embed"] = "\n".join(x for x in (e0.get("title"), (e0.get("description") or "")[:1500]) if x)
        if m.get("components"):
            item["botoes"] = [b.get("texto") or b.get("tipo") for b in _resumo_componentes(m["components"])]
        if m.get("attachments"):
            item["anexos"] = [a["filename"] for a in m["attachments"]]
        if m.get("pinned"):
            item["fixada"] = True
        if not m.get("content") and not m.get("embeds") and not m.get("attachments") and not m["author"].get("bot"):
            vazias += 1
        saida.append(item)
    resultado: dict[str, Any] = {"canal": canal["name"], "mensagens": saida}
    if vazias and vazias >= len(saida) // 2:
        resultado["aviso"] = "Muitas mensagens vieram sem texto: ative MESSAGE CONTENT INTENT no Developer Portal → Bot."
    return resultado


@mcp.tool(annotations=DESTRUTIVA)
async def limpar_mensagens(canal_id: str, quantidade: int, confirmado: bool = False,
                           apenas_do_membro: str | None = None) -> str:
    """Apaga em massa as últimas mensagens de um canal (até 500; só as com menos de 14 dias).
    apenas_do_membro limita a uma pessoa. Só chame com confirmado=true depois que o usuário confirmar."""
    canal = await achar_canal(canal_id, tipos=TIPOS_MENSAGEM)
    quantidade = max(1, min(500, int(quantidade)))
    uid = None
    if apenas_do_membro:
        uid = _id(apenas_do_membro) or (await achar_membro(apenas_do_membro))["user"]["id"]
    if not confirmado:
        quem = f" de <@{uid}>" if uid else ""
        return f"⚠️ Nada foi apagado. Confirme com o usuário: apagar as últimas {quantidade} mensagens{quem} de #{canal['name']}? Depois chame com confirmado=true."
    limite = _agora() - timedelta(days=13, hours=23)
    ids: list[str] = []
    antigas, antes = 0, None
    for _ in range(20):
        params: dict[str, Any] = {"limit": 100}
        if antes:
            params["before"] = antes
        lote = await dc("GET", f'/channels/{canal["id"]}/messages', params=params)
        if not lote:
            break
        for m in lote:
            if uid and m["author"]["id"] != uid:
                continue
            if _data_snowflake(m["id"]) < limite:
                antigas += 1
                continue
            ids.append(m["id"])
            if len(ids) >= quantidade:
                break
        antes = lote[-1]["id"]
        if len(ids) >= quantidade or len(lote) < 100 or _data_snowflake(antes) < limite:
            break
    for i in range(0, len(ids), 100):
        grupo = ids[i:i + 100]
        if len(grupo) == 1:
            await dc("DELETE", f'/channels/{canal["id"]}/messages/{grupo[0]}', motivo="Limpeza pelo agente")
        else:
            await dc("POST", f'/channels/{canal["id"]}/messages/bulk-delete', corpo={"messages": grupo}, motivo="Limpeza pelo agente")
    await registrar(f'🧹 O agente apagou {len(ids)} mensagens de <#{canal["id"]}>.')
    extra = f" ({antigas} tinham mais de 14 dias e o Discord não deixa apagar em massa)" if antigas else ""
    return f'✅ Apaguei {len(ids)} mensagens de #{canal["name"]}{extra}.'


@mcp.tool()
async def fixar_mensagem(canal_id: str, mensagem_id: str, fixar: bool = True) -> str:
    """Fixa ou desafixa uma mensagem no canal."""
    canal = await achar_canal(canal_id, tipos=TIPOS_MENSAGEM)
    metodo = "PUT" if fixar else "DELETE"
    try:
        await dc(metodo, f'/channels/{canal["id"]}/messages/pins/{mensagem_id}', motivo="Agente ECO PULSE")
    except ErroDiscord as erro:
        if erro.status not in (404, 405) or erro.codigo:
            raise
        await dc(metodo, f'/channels/{canal["id"]}/pins/{mensagem_id}', motivo="Agente ECO PULSE")
    return f'📌 Mensagem {"fixada" if fixar else "desafixada"} em #{canal["name"]}.'


@mcp.tool()
async def reagir(canal_id: str, mensagem_id: str, emoji: str) -> str:
    """Faz o bot reagir a uma mensagem com um emoji (ex.: ✅ ou <:nome:id> para emoji do servidor)."""
    canal = await achar_canal(canal_id, tipos=TIPOS_MENSAGEM)
    await dc("PUT", f'/channels/{canal["id"]}/messages/{mensagem_id}/reactions/{_emoji_url(emoji)}/@me')
    return f"✅ Reagi com {emoji}."


@mcp.tool()
async def criar_enquete(canal_id: str, pergunta: str, opcoes: list[str], horas: int = 24,
                        multipla_escolha: bool = False) -> dict:
    """Cria uma enquete nativa do Discord (2 a 10 opções, de 1 a 768 horas)."""
    canal = await achar_canal(canal_id, tipos=TIPOS_MENSAGEM)
    if not 2 <= len(opcoes) <= 10:
        raise ErroDiscord("A enquete precisa de 2 a 10 opções.")
    corpo = {"poll": {"question": {"text": pergunta[:300]},
                      "answers": [{"poll_media": {"text": o[:55]}} for o in opcoes],
                      "duration": max(1, min(768, int(horas))), "allow_multiselect": multipla_escolha}}
    msg = await dc("POST", f'/channels/{canal["id"]}/messages', corpo=corpo)
    return {"ok": True, "mensagem_id": msg["id"], "link": _link_canal(await servidor_id(), canal["id"], msg["id"])}


@mcp.tool()
async def enviar_dm(membro: str, texto: str | None = None, titulo: str | None = None, descricao: str | None = None,
                    cor: str | None = None, imagem_url: str | None = None, botao_texto: str | None = None,
                    botao_link: str | None = None) -> str:
    """Manda uma mensagem direta (DM) do bot para um membro."""
    m = await achar_membro(membro)
    payload = montar_mensagem(texto, titulo, descricao, cor, imagem_url, None, None, botao_texto, botao_link)
    dm = await dc("POST", "/users/@me/channels", corpo={"recipient_id": m["user"]["id"]})
    await dc("POST", f'/channels/{dm["id"]}/messages', corpo=payload)
    return f"✅ DM enviada para {_nome_membro(m)}."


# ── automações ──

@mcp.tool()
async def agendar_mensagem(canal_id: str, quando: str, texto: str | None = None, titulo: str | None = None,
                           descricao: str | None = None, cor: str | None = None, imagem_url: str | None = None,
                           rodape: str | None = None, botao_texto: str | None = None, botao_link: str | None = None,
                           repetir: str = "nao", intervalo_minutos: int | None = None,
                           mencionar_todos: bool = False, nome: str | None = None) -> dict:
    """Agenda uma mensagem (horário de Brasília) e, se quiser, repete. quando: "AAAA-MM-DD HH:MM",
    "DD/MM HH:MM", "HH:MM" (hoje, ou amanhã se já passou), "amanhã 9h" ou "daqui a 30 min".
    repetir: nao, diario, semanal, dias_uteis (seg a sex) ou minutos (com intervalo_minutos, mínimo 10).
    Roda no próprio bot, mesmo com o Claude fechado."""
    await exigir_config()
    canal = await achar_canal(canal_id, tipos=TIPOS_MENSAGEM)
    payload = montar_mensagem(texto, titulo, descricao, cor, await _guardar_imagem(imagem_url), None, rodape,
                              botao_texto, botao_link, mencionar_todos)
    rep = REPETICOES.get(_norm(repetir))
    if rep is None:
        raise ErroDiscord('repetir deve ser: nao, diario, semanal, dias_uteis ou minutos.')
    if rep == "minutos":
        if not intervalo_minutos or not 10 <= int(intervalo_minutos) <= 43200:
            raise ErroDiscord("Para repetir a cada X minutos, passe intervalo_minutos entre 10 e 43200.")
    quando_dt = _ler_quando(quando)
    if quando_dt.astimezone(timezone.utc) < _agora() - timedelta(minutes=1):
        raise ErroDiscord(f"Esse horário ({_fmt(quando_dt)}) já passou.")
    if rep == "dias_uteis":
        while quando_dt.astimezone(FUSO).weekday() >= 5:
            quando_dt += timedelta(days=1)
    item = {"id": secrets.token_hex(3), "nome": (nome or titulo or texto or "mensagem")[:50],
            "canal_id": canal["id"], "canal_nome": canal["name"], "mensagem": payload,
            "proxima": quando_dt.astimezone(timezone.utc).isoformat(), "repetir": rep,
            "intervalo_minutos": int(intervalo_minutos) if rep == "minutos" else None,
            "criada": _agora().isoformat(), "envios": 0}
    _cfg["agendadas"].append(item)
    await salvar_config()
    return {"ok": True, "id": item["id"], "canal": canal["name"], "primeiro_envio": _fmt(quando_dt),
            "repete": NOMES_REPETICAO[rep].format(n=intervalo_minutos)}


@mcp.tool(annotations=LEITURA)
async def listar_automacoes() -> dict:
    """Mostra tudo que está automatizado: mensagens agendadas, boas-vindas, despedida, respostas
    automáticas, cargos por reação e canal de registros (com os IDs para remover)."""
    await garantir_config()
    bv, dp, lg = _cfg.get("boas_vindas") or {}, _cfg.get("despedida") or {}, _cfg.get("logs") or {}
    resultado: dict[str, Any] = {
        "mensagens_agendadas": [
            {"id": a["id"], "nome": a.get("nome"), "canal": a.get("canal_nome"), "proximo_envio": _fmt(a["proxima"]),
             "repete": NOMES_REPETICAO.get(a.get("repetir", "nao"), "?").format(n=a.get("intervalo_minutos")),
             "envios": a.get("envios", 0), **({"ultimo_erro": a["ultimo_erro"]} if a.get("ultimo_erro") else {})}
            for a in sorted(_cfg["agendadas"], key=lambda a: a["proxima"])],
        "boas_vindas": ({"canal": bv.get("canal_nome"), "texto": bv.get("texto"), "titulo": bv.get("titulo"),
                         "cargo_automatico": bv.get("cargo_nome"), "dm": bv.get("mandar_dm", False)}
                        if bv.get("ativo") else "desligado"),
        "despedida": {"canal": dp.get("canal_nome"), "texto": dp.get("texto")} if dp.get("ativo") else "desligado",
        "respostas_automaticas": [
            {"id": r["id"], "gatilho": r["gatilho"], "modo": r.get("modo", "contem"),
             "canal": r.get("canal_nome") or "todos", "resposta": r["resposta"][:120]} for r in _cfg["respostas"]],
        "cargos_por_reacao": [
            {"id": c["id"], "emoji": c["emoji_exibir"], "cargo": c["cargo_nome"], "canal": c.get("canal_nome"),
             "mensagem_id": c["mensagem_id"]} for c in _cfg["cargos_reacao"]],
        "registros": f'#{lg.get("canal_nome")}' if lg.get("ativo") else "desligado",
        "paineis": [
            {"id": p["id"], "tipo": "ticket" if p["tipo"] == "ticket" else "verificação", "canal": p.get("canal_nome"),
             **({"cargo": p.get("cargo_nome")} if p["tipo"] == "verificacao" else
                {"tickets_em": p.get("categoria_nome"), "equipe": [c["nome"] for c in p.get("cargos_equipe", [])],
                 "historico_em": p.get("canal_historico_nome")})} for p in _cfg.get("paineis", {}).values()],
        "tickets_abertos": [
            {"canal": f"<#{cid}>", "numero": t.get("numero"), "dono": t.get("dono_nome"), "assunto": t.get("motivo"),
             "atendido_por": t.get("assumido_nome"), "aberto": _fmt(t.get("aberto"))}
            for cid, t in _cfg.get("tickets", {}).items()],
        "sorteios": [
            {"id": x["id"], "premio": x["premio"], "canal": x.get("canal_nome"), "status": x["status"],
             "participantes": len(x.get("participantes", [])),
             ("termina" if x["status"] == "ativo" else "terminou"): _fmt(x["fim"]),
             **({"ganhadores": [f"<@{g}>" for g in x.get("ganhadores", [])]} if x["status"] == "encerrado" else {})}
            for x in sorted(_cfg.get("sorteios", {}).values(), key=lambda x: x["fim"], reverse=True)],
    }
    if not _cfg_estado["carregada"]:
        resultado["aviso"] = _cfg_estado["aviso"] or "Memória ainda não carregada."
    return resultado


@mcp.tool(annotations=DESTRUTIVA)
async def remover_automacao(automacao_id: str) -> str:
    """Remove uma mensagem agendada, resposta automática, cargo por reação ou painel (ticket/verificação) pelo ID
    (veja listar_automacoes). Remover um painel desliga o botão dele; a mensagem continua no canal."""
    await exigir_config()
    alvo = automacao_id.strip().strip("`")
    if alvo in _cfg.get("paineis", {}):
        p = _cfg["paineis"].pop(alvo)
        await salvar_config()
        return f'✅ Painel de {"ticket" if p["tipo"] == "ticket" else "verificação"} {alvo} desligado (a mensagem em #{p.get("canal_nome")} continua lá; apague se quiser).'
    if alvo in _cfg.get("sorteios", {}):
        raise ErroDiscord("Para sorteios use encerrar_sorteio ou cancelar_sorteio.")
    for lista, rotulo in (("agendadas", "Mensagem agendada"), ("respostas", "Resposta automática"),
                          ("cargos_reacao", "Cargo por reação")):
        for item in _cfg[lista]:
            if item["id"] == alvo:
                _cfg[lista].remove(item)
                await salvar_config()
                return f"✅ {rotulo} {alvo} removida."
    raise ErroDiscord(f"Não achei automação com ID {alvo}. Use listar_automacoes.")


@mcp.tool()
async def configurar_boas_vindas(canal_id: str | None = None, texto: str | None = None, titulo: str | None = None,
                                 descricao: str | None = None, cor: str | None = None, imagem_url: str | None = None,
                                 cargo_automatico: str | None = None, mandar_dm: bool = False,
                                 ativo: bool = True) -> dict:
    """Mensagem automática quando alguém entra no servidor. Textos aceitam {usuario} (menciona),
    {nome}, {servidor} e {membros}. cargo_automatico dá um cargo para quem entra. mandar_dm também
    manda a mensagem no privado. ativo=false desliga."""
    await exigir_config()
    if not ativo:
        _cfg["boas_vindas"] = {**(_cfg.get("boas_vindas") or {}), "ativo": False}
        await salvar_config()
        return {"ok": True, "boas_vindas": "desligado"}
    conf: dict[str, Any] = {"ativo": True, "texto": texto, "titulo": titulo, "descricao": descricao,
                            "cor": cor, "imagem_url": await _guardar_imagem(imagem_url), "mandar_dm": mandar_dm}
    if canal_id:
        canal = await achar_canal(canal_id, tipos=TIPOS_MENSAGEM)
        conf.update(canal_id=canal["id"], canal_nome=canal["name"])
    if cargo_automatico:
        cargo = await achar_cargo(cargo_automatico)
        conf.update(cargo_id=cargo["id"], cargo_nome=cargo["name"])
    if not (canal_id or mandar_dm or cargo_automatico):
        raise ErroDiscord("Diga o canal da mensagem (canal_id), ou mandar_dm=true, ou um cargo_automatico.")
    if canal_id or mandar_dm:
        montar_mensagem(texto, titulo, descricao, cor, imagem_url)  # valida
    _cfg["boas_vindas"] = conf
    await salvar_config()
    resultado: dict[str, Any] = {"ok": True, "boas_vindas": "ligado", "canal": conf.get("canal_nome"),
                                 "cargo_automatico": conf.get("cargo_nome"), "dm": mandar_dm}
    if _bot_estado.get("intents_privilegiadas") is False or not str(_bot_estado["status"]).startswith("conectado"):
        resultado["atencao"] = _bot_estado.get("aviso") or f'O bot em tempo real está: {_bot_estado["status"]}.'
    return resultado


@mcp.tool()
async def configurar_despedida(canal_id: str | None = None, texto: str | None = None, titulo: str | None = None,
                               descricao: str | None = None, cor: str | None = None, ativo: bool = True) -> dict:
    """Mensagem automática quando alguém sai do servidor ({nome}, {usuario}, {servidor}, {membros}).
    ativo=false desliga."""
    await exigir_config()
    if not ativo:
        _cfg["despedida"] = {**(_cfg.get("despedida") or {}), "ativo": False}
        await salvar_config()
        return {"ok": True, "despedida": "desligado"}
    if not canal_id:
        raise ErroDiscord("Diga em qual canal a despedida aparece (canal_id).")
    canal = await achar_canal(canal_id, tipos=TIPOS_MENSAGEM)
    montar_mensagem(texto, titulo, descricao, cor)
    _cfg["despedida"] = {"ativo": True, "canal_id": canal["id"], "canal_nome": canal["name"], "texto": texto,
                         "titulo": titulo, "descricao": descricao, "cor": cor}
    await salvar_config()
    return {"ok": True, "despedida": "ligado", "canal": canal["name"]}


@mcp.tool()
async def adicionar_resposta_automatica(gatilho: str, resposta: str, modo: str = "contem",
                                        canal_id: str | None = None) -> dict:
    """O bot responde sozinho quando alguém escreve o gatilho. modo: contem (a palavra/frase aparece
    na mensagem), exata (a mensagem é só isso) ou comeca. canal_id limita a um canal.
    A resposta aceita {usuario} e {nome}."""
    await exigir_config()
    modo_n = {"contem": "contem", "exata": "exata", "exato": "exata", "comeca": "comeca", "comecacom": "comeca"}.get(_norm(modo))
    if not modo_n:
        raise ErroDiscord("modo deve ser contem, exata ou comeca.")
    if not _norm_frase(gatilho):
        raise ErroDiscord("O gatilho está vazio.")
    if len(_cfg["respostas"]) >= 100:
        raise ErroDiscord("Limite de 100 respostas automáticas atingido; remova alguma antes.")
    item: dict[str, Any] = {"id": secrets.token_hex(3), "gatilho": gatilho.strip(), "resposta": resposta[:2000], "modo": modo_n}
    if canal_id:
        canal = await achar_canal(canal_id, tipos=TIPOS_MENSAGEM)
        item.update(canal_id=canal["id"], canal_nome=canal["name"])
    _cfg["respostas"].append(item)
    await salvar_config()
    resultado: dict[str, Any] = {"ok": True, "id": item["id"], "gatilho": item["gatilho"], "modo": modo_n,
                                 "canal": item.get("canal_nome", "todos")}
    if _bot_estado.get("intents_privilegiadas") is False:
        resultado["atencao"] = _bot_estado.get("aviso")
    return resultado


@mcp.tool()
async def criar_cargo_por_reacao(canal_id: str, mensagem_id: str, emoji: str, cargo: str) -> dict:
    """Quem reagir com o emoji na mensagem ganha o cargo (e perde ao tirar a reação). Para montar um
    painel: envie a mensagem com enviar_mensagem e chame esta ferramenta uma vez para cada emoji."""
    await exigir_config()
    canal = await achar_canal(canal_id, tipos=TIPOS_MENSAGEM)
    await dc("GET", f'/channels/{canal["id"]}/messages/{mensagem_id}')
    c = await achar_cargo(cargo)
    if c["id"] == await servidor_id() or c.get("managed"):
        raise ErroDiscord("Esse cargo não pode ser dado por reação.")
    await dc("PUT", f'/channels/{canal["id"]}/messages/{mensagem_id}/reactions/{_emoji_url(emoji)}/@me')
    chave = _emoji_chave(emoji)
    _cfg["cargos_reacao"] = [r for r in _cfg["cargos_reacao"] if not (r["mensagem_id"] == mensagem_id and r["emoji"] == chave)]
    item = {"id": secrets.token_hex(3), "canal_id": canal["id"], "canal_nome": canal["name"], "mensagem_id": mensagem_id,
            "emoji": chave, "emoji_exibir": emoji, "cargo_id": c["id"], "cargo_nome": c["name"]}
    _cfg["cargos_reacao"].append(item)
    await salvar_config()
    return {"ok": True, "id": item["id"], "emoji": emoji, "cargo": c["name"]}


@mcp.tool()
async def configurar_logs(canal_id: str | None = None, ativo: bool = True) -> str:
    """Define um canal de registros: entradas, saídas e ações do agente (apagar, banir, expulsar...)."""
    await exigir_config()
    if not ativo:
        _cfg["logs"] = {**(_cfg.get("logs") or {}), "ativo": False}
        await salvar_config()
        return "Registros desligados."
    if not canal_id:
        raise ErroDiscord("Diga qual canal recebe os registros.")
    canal = await achar_canal(canal_id, tipos=TIPOS_MENSAGEM)
    _cfg["logs"] = {"ativo": True, "canal_id": canal["id"], "canal_nome": canal["name"]}
    await salvar_config()
    await registrar("✅ Este canal agora recebe os registros do agente ECO PULSE.")
    return f'✅ Registros indo para #{canal["name"]}.'


NOME_REGRA_FILTRO = "ECO PULSE • Filtro"


@mcp.tool()
async def configurar_filtro_palavras(palavras: list[str] | None = None, bloquear_convites: bool = False,
                                     mensagem_bloqueio: str | None = None, canal_alerta: str | None = None,
                                     cargos_liberados: list[str] | None = None, ativo: bool = True) -> dict:
    """Usa o AutoMod nativo do Discord (funciona até com o bot desligado) para bloquear mensagens com
    palavras proibidas e/ou convites de outros servidores. 'golpe' bloqueia a palavra inteira; '*golpe*'
    bloqueia em qualquer parte. Cada chamada substitui a configuração anterior. canal_alerta recebe um
    aviso a cada bloqueio; cargos_liberados (ex.: staff) não são filtrados. ativo=false desliga."""
    gid = await servidor_id()
    regras = await dc("GET", f"/guilds/{gid}/auto-moderation/rules")
    atual = next((r for r in regras if r["name"] == NOME_REGRA_FILTRO), None)
    if not ativo:
        if atual:
            await dc("PATCH", f'/guilds/{gid}/auto-moderation/rules/{atual["id"]}', corpo={"enabled": False})
        return {"ok": True, "filtro": "desligado"}
    lista = [p.strip()[:60] for p in (palavras or []) if p.strip()][:1000]
    regex = [r"discord(?:app)?\.(?:gg|io|me|li|com/invite)/\S+", r"dsc\.gg/\S+"] if bloquear_convites else []
    if not lista and not regex:
        raise ErroDiscord("Passe palavras e/ou bloquear_convites=true.")
    acoes: list[dict[str, Any]] = [{"type": 1, "metadata": {"custom_message": (mensagem_bloqueio or "Mensagem bloqueada pelo filtro do ECO PULSE.")[:150]}}]
    if canal_alerta:
        acoes.append({"type": 2, "metadata": {"channel_id": (await achar_canal(canal_alerta, tipos={0, 5}))["id"]}})
    isentos = [(await achar_cargo(c))["id"] for c in (cargos_liberados or [])][:20]
    corpo = {"name": NOME_REGRA_FILTRO, "event_type": 1, "trigger_type": 1,
             "trigger_metadata": {"keyword_filter": lista, "regex_patterns": regex},
             "actions": acoes, "enabled": True, "exempt_roles": isentos}
    if atual:
        corpo.pop("trigger_type")
        corpo.pop("event_type")
        await dc("PATCH", f'/guilds/{gid}/auto-moderation/rules/{atual["id"]}', corpo=corpo, motivo="Agente ECO PULSE")
    else:
        await dc("POST", f"/guilds/{gid}/auto-moderation/rules", corpo=corpo, motivo="Agente ECO PULSE")
    return {"ok": True, "filtro": "ligado", "palavras": len(lista), "bloqueia_convites": bloquear_convites,
            "alerta_em": canal_alerta, "cargos_liberados": len(isentos)}


# ── cargos ──

@mcp.tool(annotations=LEITURA)
async def listar_cargos() -> dict:
    """Lista os cargos do servidor (do mais alto para o mais baixo) com id, cor e principais permissões."""
    gid = await servidor_id()
    saida = []
    for c in sorted(await _cargos(), key=lambda c: -c["position"]):
        perms = int(c["permissions"])
        item: dict[str, Any] = {"id": c["id"], "nome": c["name"], "cor": f'#{c["color"]:06x}' if c["color"] else None,
                                "posicao": c["position"]}
        if perms & PERMISSOES["administrador"]:
            item["administrador"] = True
        if c.get("hoist"):
            item["separado"] = True
        if c.get("mentionable"):
            item["mencionavel"] = True
        if c.get("managed"):
            item["de_bot_ou_integracao"] = True
        if c["id"] == gid:
            item["nome"] = "@everyone"
        saida.append(item)
    return {"cargos": saida}


@mcp.tool()
async def criar_cargo(nome: str, cor: str | None = None, separado: bool = False, mencionavel: bool = False,
                      permissoes: list[str] | None = None) -> dict:
    """Cria um cargo. separado=true mostra os membros separados na lista lateral. permissoes: lista
    (ex.: ["gerenciar_mensagens", "castigar"]); sem passar, usa as permissões padrão."""
    gid = await servidor_id()
    corpo: dict[str, Any] = {"name": nome, "hoist": separado, "mentionable": mencionavel}
    if cor:
        corpo["color"] = _cor(cor)
    if permissoes is not None:
        corpo["permissions"] = str(_bits(permissoes))
    c = await dc("POST", f"/guilds/{gid}/roles", corpo=corpo, motivo="Agente ECO PULSE")
    return {"ok": True, "id": c["id"], "nome": c["name"]}


@mcp.tool()
async def editar_cargo(cargo: str, nome: str | None = None, cor: str | None = None, separado: bool | None = None,
                       mencionavel: bool | None = None, permissoes: list[str] | None = None,
                       adicionar_permissoes: list[str] | None = None, remover_permissoes: list[str] | None = None,
                       posicao: int | None = None) -> dict:
    """Edita um cargo: nome, cor, separado, mencionável, permissões (permissoes substitui todas;
    adicionar_permissoes/remover_permissoes mexem só nas citadas) e posição (maior = mais alto)."""
    gid = await servidor_id()
    c = await achar_cargo(cargo)
    corpo: dict[str, Any] = {}
    if nome is not None:
        corpo["name"] = nome
    if cor is not None:
        corpo["color"] = _cor(cor) or 0
    if separado is not None:
        corpo["hoist"] = separado
    if mencionavel is not None:
        corpo["mentionable"] = mencionavel
    if permissoes is not None or adicionar_permissoes or remover_permissoes:
        base = _bits(permissoes) if permissoes is not None else int(c["permissions"])
        corpo["permissions"] = str((base | _bits(adicionar_permissoes)) & ~_bits(remover_permissoes))
    if corpo:
        c = await dc("PATCH", f'/guilds/{gid}/roles/{c["id"]}', corpo=corpo, motivo="Agente ECO PULSE")
    if posicao is not None:
        await dc("PATCH", f"/guilds/{gid}/roles", corpo=[{"id": c["id"], "position": posicao}], motivo="Agente ECO PULSE")
    if not corpo and posicao is None:
        raise ErroDiscord("Nada para mudar.")
    return {"ok": True, "id": c["id"], "nome": c["name"], "permissoes": _nomes_perm(int(c["permissions"]))}


@mcp.tool(annotations=DESTRUTIVA)
async def apagar_cargo(cargo: str, confirmado: bool = False) -> str:
    """Apaga um cargo. Só chame com confirmado=true depois que o usuário confirmar."""
    gid = await servidor_id()
    c = await achar_cargo(cargo)
    if c["id"] == gid or c.get("managed"):
        raise ErroDiscord("Esse cargo não pode ser apagado.")
    if not confirmado:
        return f'⚠️ Nada foi apagado. Confirme com o usuário que ele quer apagar o cargo @{c["name"]} ({c["id"]}). Depois chame com confirmado=true.'
    await dc("DELETE", f'/guilds/{gid}/roles/{c["id"]}', motivo="Agente ECO PULSE")
    await registrar(f'🗑️ O agente apagou o cargo **@{c["name"]}**.')
    return f'✅ Cargo @{c["name"]} apagado.'


@mcp.tool()
async def dar_cargo(membro: str, cargo: str) -> str:
    """Dá um cargo a um membro."""
    gid = await servidor_id()
    m, c = await achar_membro(membro), await achar_cargo(cargo)
    await dc("PUT", f'/guilds/{gid}/members/{m["user"]["id"]}/roles/{c["id"]}', motivo="Agente ECO PULSE")
    return f'✅ {_nome_membro(m)} agora tem o cargo @{c["name"]}.'


@mcp.tool()
async def tirar_cargo(membro: str, cargo: str) -> str:
    """Tira um cargo de um membro."""
    gid = await servidor_id()
    m, c = await achar_membro(membro), await achar_cargo(cargo)
    await dc("DELETE", f'/guilds/{gid}/members/{m["user"]["id"]}/roles/{c["id"]}', motivo="Agente ECO PULSE")
    return f'✅ Tirei o cargo @{c["name"]} de {_nome_membro(m)}.'


# ── membros e moderação ──

@mcp.tool(annotations=LEITURA)
async def listar_membros(limite: int = 100, cargo: str | None = None) -> dict:
    """Lista membros do servidor (até 1000), opcionalmente só os de um cargo."""
    gid = await servidor_id()
    cargos = {c["id"]: c["name"] for c in await _cargos()}
    filtro = (await achar_cargo(cargo))["id"] if cargo else None
    limite = max(1, min(1000, limite))
    membros: list[dict] = []
    depois = "0"
    try:
        while len(membros) < limite:
            lote = await dc("GET", f"/guilds/{gid}/members", params={"limit": 1000, "after": depois})
            if not lote:
                break
            for m in lote:
                if filtro and filtro not in m.get("roles", []):
                    continue
                membros.append(m)
            depois = lote[-1]["user"]["id"]
            if len(lote) < 1000:
                break
    except ErroDiscord as erro:
        if erro.codigo == 50001 or erro.status == 403:
            raise ErroDiscord("Para listar membros, ative SERVER MEMBERS INTENT no Developer Portal → Bot.")
        raise
    saida = [{"id": m["user"]["id"], "nome": _nome_membro(m), "usuario": m["user"]["username"],
              **({"bot": True} if m["user"].get("bot") else {}),
              "cargos": [cargos.get(r, r) for r in m.get("roles", [])], "entrou": _fmt(m.get("joined_at"))}
             for m in membros[:limite]]
    return {"quantidade": len(saida), "membros": saida}


@mcp.tool(annotations=LEITURA)
async def info_membro(membro: str) -> dict:
    """Mostra dados de um membro: nome, cargos, quando entrou, conta criada e se está de castigo."""
    m = await achar_membro(membro)
    cargos = {c["id"]: c["name"] for c in await _cargos()}
    u = m["user"]
    info: dict[str, Any] = {"id": u["id"], "usuario": u["username"], "nome_exibido": _nome_membro(m),
                            "apelido": m.get("nick"), "bot": u.get("bot", False),
                            "cargos": [cargos.get(r, r) for r in m.get("roles", [])],
                            "entrou_no_servidor": _fmt(m.get("joined_at")), "conta_criada": _fmt(_data_snowflake(u["id"]))}
    ate = m.get("communication_disabled_until")
    if ate and datetime.fromisoformat(ate.replace("Z", "+00:00")) > _agora():
        info["de_castigo_ate"] = _fmt(ate)
    return info


@mcp.tool()
async def mudar_apelido(membro: str, apelido: str | None = None) -> str:
    """Muda o apelido de um membro no servidor (vazio volta ao nome normal)."""
    gid = await servidor_id()
    m = await achar_membro(membro)
    await dc("PATCH", f'/guilds/{gid}/members/{m["user"]["id"]}', corpo={"nick": apelido or None}, motivo="Agente ECO PULSE")
    return f'✅ Apelido de @{m["user"]["username"]} {"agora é " + apelido if apelido else "removido"}.'


@mcp.tool()
async def castigar(membro: str, minutos: int, motivo: str | None = None) -> str:
    """Deixa um membro de castigo (timeout: não fala nem reage) por X minutos (máx. 40320 = 28 dias).
    minutos=0 tira o castigo."""
    gid = await servidor_id()
    m = await achar_membro(membro)
    minutos = max(0, min(40320, int(minutos)))
    ate = (_agora() + timedelta(minutes=minutos)).isoformat() if minutos else None
    await dc("PATCH", f'/guilds/{gid}/members/{m["user"]["id"]}', corpo={"communication_disabled_until": ate},
             motivo=motivo or "Agente ECO PULSE")
    if minutos:
        await registrar(f'🔇 O agente deixou <@{m["user"]["id"]}> de castigo por {minutos} min.{" Motivo: " + motivo if motivo else ""}')
        return f"🔇 {_nome_membro(m)} de castigo até {_fmt(ate)}."
    await registrar(f'🔈 O agente tirou o castigo de <@{m["user"]["id"]}>.')
    return f"🔈 Castigo de {_nome_membro(m)} removido."


@mcp.tool(annotations=DESTRUTIVA)
async def expulsar(membro: str, motivo: str | None = None, confirmado: bool = False) -> str:
    """Expulsa um membro (ele pode voltar com convite). Só chame com confirmado=true depois que o usuário confirmar."""
    gid = await servidor_id()
    m = await achar_membro(membro)
    rotulo = f'{_nome_membro(m)} (@{m["user"]["username"]}, ID {m["user"]["id"]})'
    if not confirmado:
        return f"⚠️ Ninguém foi expulso. Confirme com o usuário que ele quer expulsar {rotulo}. Depois chame com confirmado=true."
    await dc("DELETE", f'/guilds/{gid}/members/{m["user"]["id"]}', motivo=motivo or "Agente ECO PULSE")
    await registrar(f"👢 O agente expulsou **{rotulo}**.{' Motivo: ' + motivo if motivo else ''}")
    return f"👢 {rotulo} expulso."


@mcp.tool(annotations=DESTRUTIVA)
async def banir(membro: str, motivo: str | None = None, apagar_mensagens_horas: int = 0, confirmado: bool = False) -> str:
    """Bane um membro (ou um ID de usuário). apagar_mensagens_horas apaga as mensagens dele das últimas X
    horas (máx. 168). Só chame com confirmado=true depois que o usuário confirmar."""
    gid = await servidor_id()
    uid = _id(membro)
    if uid:
        rotulo = f"o usuário {uid}"
        try:
            m = await dc("GET", f"/guilds/{gid}/members/{uid}")
            rotulo = f'{_nome_membro(m)} (@{m["user"]["username"]}, ID {uid})'
        except ErroDiscord:
            pass
    else:
        m = await achar_membro(membro)
        uid = m["user"]["id"]
        rotulo = f'{_nome_membro(m)} (@{m["user"]["username"]}, ID {uid})'
    if not confirmado:
        return f"⚠️ Ninguém foi banido. Confirme com o usuário que ele quer banir {rotulo}. Depois chame com confirmado=true."
    segundos = max(0, min(168, int(apagar_mensagens_horas))) * 3600
    await dc("PUT", f"/guilds/{gid}/bans/{uid}", corpo={"delete_message_seconds": segundos}, motivo=motivo or "Agente ECO PULSE")
    await registrar(f"🔨 O agente baniu **{rotulo}**.{' Motivo: ' + motivo if motivo else ''}")
    return f"🔨 {rotulo} banido."


@mcp.tool()
async def desbanir(usuario: str) -> str:
    """Tira o banimento de um usuário (ID ou nome de usuário)."""
    gid = await servidor_id()
    uid = _id(usuario)
    if not uid:
        bans = await dc("GET", f"/guilds/{gid}/bans", params={"limit": 1000})
        alvo = _norm(usuario.lstrip("@"))
        achados = [b for b in bans if alvo in (_norm(b["user"]["username"]), _norm(b["user"].get("global_name") or ""))]
        if len(achados) != 1:
            raise ErroDiscord("Não achei exatamente um banido com esse nome. Use o ID." if not achados else
                              "Vários banidos com esse nome: " + ", ".join(f'{b["user"]["username"]} ({b["user"]["id"]})' for b in achados))
        uid = achados[0]["user"]["id"]
    await dc("DELETE", f"/guilds/{gid}/bans/{uid}", motivo="Agente ECO PULSE")
    await registrar(f"♻️ O agente desbaniu <@{uid}>.")
    return f"✅ Usuário {uid} desbanido."


# ── loja (compra em chat privado com Pix) ──

def _resumo_produto(p: dict) -> dict:
    return {
        "id": p["id"], "nome": p.get("nome"), "preco": _reais(p.get("preco")), "ativo": p.get("ativo", True),
        "aprovador": p.get("cargo_aprovador_nome") or "nenhum (só o dono do servidor)",
        "cargo_cliente": p.get("cargo_cliente_nome") or "nenhum",
        "canal_estoque": f'<#{p["canal_estoque_id"]}>' if p.get("canal_estoque_id") else "nenhum",
        "entrega_texto": "configurado" if p.get("entrega_texto") else "nenhum",
        "entrega": {"canal": f'canal privado do comprador (apagado em {p.get("dias_entrega") or DIAS_ENTREGA_PADRAO} dias)',
                    "dm": "DM do comprador",
                    "canal_e_dm": f'canal privado ({p.get("dias_entrega") or DIAS_ENTREGA_PADRAO} dias) + DM'}[_modo_entrega(p)],
        "link_pagamento": p.get("link_pagamento") or "nenhum",
        "qr_imagem_url": p.get("qr_imagem_url") or "nenhum",
        "nome_do_chat": f'{p.get("prefixo_canal") or "compra-" + p["id"]}-nome-da-pessoa',
        "categoria_dos_chats": f'<#{p["categoria_id"]}>' if p.get("categoria_id") else "nenhuma (topo do servidor)",
        "canal_vendas": f'<#{p["canal_vendas_id"]}>' if p.get("canal_vendas_id") else "nenhum",
        "painel": p.get("painel") or "não publicado",
    }


@mcp.tool()
async def configurar_produto(produto: str, nome: str | None = None, preco: str | None = None,
                             cargo_cliente: str | None = None, canal_estoque: str | None = None,
                             entrega_texto: str | None = None, link_pagamento: str | None = None,
                             qr_imagem_url: str | None = None, prefixo_canal: str | None = None,
                             categoria: str | None = None, cargo_aprovador: str | None = None,
                             canal_vendas: str | None = None, cor: str | None = None,
                             ativo: bool | None = None, entrega: str | None = None,
                             dias_entrega: int | None = None, categoria_entrega: str | None = None) -> dict:
    """Cria ou atualiza um produto da loja (compra em chat privado com Pix).
    produto = identificador curto (ex.: chatgpt-astra). preco em reais (ex.: "19,90").
    Pagamento: o QR Code e o "copia e cola" saem da variável PIX_CHAVE do Render com o valor do produto;
    link_pagamento (botão) e qr_imagem_url (imagem pronta) são opcionais.
    Entrega automática: canal_estoque (cada mensagem nele = 1 produto, entregue por DM e apagada na venda;
    mensagens fixadas são ignoradas) ou, sem estoque, entrega_texto (o mesmo texto para todos).
    cargo_aprovador (padrão: Fundador) confirma ou recusa os pagamentos e vê os chats. cargo_cliente é dado
    ao comprador. prefixo_canal define o nome do chat: prefixo-nome-da-pessoa. categoria (padrão: a de
    tickets) e canal_vendas (padrão: registro-de-vendas). Passe "" para limpar um campo.
    entrega = onde o produto chega quando o pagamento é confirmado: "canal" (padrão: canal privado só do
    comprador, apagado depois de dias_entrega dias, padrão 7), "dm" ou "canal_e_dm".
    categoria_entrega = categoria dos canais de entrega (padrão: a mesma dos chats de compra)."""
    await exigir_config()
    pid = _slug(produto, 40)
    if not pid:
        raise ErroDiscord("Dê um identificador para o produto, por exemplo chatgpt-astra.")
    produtos = _cfg.setdefault("produtos", {})
    novo = pid not in produtos
    p = produtos.setdefault(pid, {"id": pid, "nome": (nome or produto).strip(), "ativo": True,
                                  "criado": _agora().isoformat()})
    if nome is not None:
        p["nome"] = nome.strip() or pid
    if preco is not None:
        p["preco"] = _ler_preco(preco) if str(preco).strip() else None
    if cor is not None:
        p["cor"] = _cor(cor) if cor else None
    if ativo is not None:
        p["ativo"] = bool(ativo)
    if prefixo_canal is not None:
        p["prefixo_canal"] = prefixo_canal.strip()[:60] or None
    if entrega is not None:
        modo = _MODOS_ENTREGA.get(_norm(entrega)) if entrega else "canal"
        if not modo:
            raise ErroDiscord('entrega deve ser "canal", "dm" ou "canal_e_dm".')
        p["entrega_modo"] = modo
    if dias_entrega is not None:
        p["dias_entrega"] = max(1, min(60, int(dias_entrega)))
    if entrega_texto is not None:
        p["entrega_texto"] = entrega_texto or None
    for campo, valor in (("link_pagamento", link_pagamento), ("qr_imagem_url", qr_imagem_url)):
        if valor is not None:
            if valor and not re.match(r"https?://", valor):
                raise ErroDiscord(f"{campo} precisa começar com https://")
            p[campo] = valor or None

    async def _guardar(ref: str | None, chave: str, achar) -> None:
        if ref is None:
            return
        if not str(ref).strip():
            p.pop(f"{chave}_id", None)
            p.pop(f"{chave}_nome", None)
            return
        item = await achar(ref)
        p[f"{chave}_id"], p[f"{chave}_nome"] = item["id"], item["name"]

    await _guardar(cargo_cliente, "cargo_cliente", achar_cargo)
    await _guardar(cargo_aprovador, "cargo_aprovador", achar_cargo)
    await _guardar(canal_estoque, "canal_estoque", lambda ref: achar_canal(ref, tipos={0}))
    await _guardar(categoria, "categoria", achar_categoria)
    await _guardar(canal_vendas, "canal_vendas", lambda ref: achar_canal(ref, tipos={0}))
    await _guardar(categoria_entrega, "categoria_entrega", achar_categoria)
    if novo:  # padrões do ECO PULSE
        if cargo_aprovador is None:
            try:
                cg = next(c for c in await _cargos() if _norm(c["name"]) == "fundador")
                p["cargo_aprovador_id"], p["cargo_aprovador_nome"] = cg["id"], cg["name"]
            except StopIteration:
                pass
        canais = await _canais()
        if categoria is None:
            cat = next((c for c in canais if c["type"] == 4 and "ticket" in _norm(c["name"])), None)
            if cat:
                p["categoria_id"], p["categoria_nome"] = cat["id"], cat["name"]
        if canal_vendas is None:
            cv = next((c for c in canais if c["type"] == 0 and "registrodevendas" in _norm(c["name"])), None)
            if cv:
                p["canal_vendas_id"], p["canal_vendas_nome"] = cv["id"], cv["name"]
    await salvar_config()
    avisos = []
    if not (PIX_CHAVE or PIX_COPIA_COLA or p.get("link_pagamento") or p.get("qr_imagem_url")):
        avisos.append("Sem dados de pagamento: o dono precisa criar a variável PIX_CHAVE no Render "
                      "(ou passar link_pagamento / qr_imagem_url). Sem isso o chat pede para a equipe mandar os dados.")
    if PIX_COPIA_COLA and not PIX_CHAVE and p.get("preco"):
        avisos.append("PIX_COPIA_COLA é um código fixo: o valor dele não muda com o preço do produto.")
    if not p.get("canal_estoque_id") and not p.get("entrega_texto"):
        avisos.append("Sem entrega automática: configure canal_estoque ou entrega_texto.")
    if not p.get("cargo_aprovador_id"):
        avisos.append("Sem cargo aprovador: só o dono do servidor consegue confirmar pagamentos.")
    if not p.get("preco"):
        avisos.append("Sem preço: o Pix sai sem valor (a pessoa digita o valor no banco).")
    return {"ok": True, "novo": novo, "produto": _resumo_produto(p), "avisos": avisos}


@mcp.tool()
async def publicar_painel_compra(canal_id: str, produto: str, mensagem_id: str | None = None,
                                 titulo: str | None = None, descricao: str | None = None, cor: str | None = None,
                                 imagem_url: str | None = None, miniatura_url: str | None = None,
                                 rodape: str | None = None, botao_texto: str = "Comprar agora") -> dict:
    """Publica o painel de venda de um produto com o botão que abre o chat privado de compra.
    Com mensagem_id, troca os botões de uma mensagem já enviada pelo bot (e o texto, se passar
    titulo/descricao) em vez de mandar outra."""
    await exigir_config()
    pid = _slug(produto, 40)
    prod = _cfg["produtos"].get(pid)
    if not prod:
        raise ErroDiscord(f'O produto "{produto}" não existe. Crie antes com configurar_produto.')
    canal = await achar_canal(canal_id)
    botoes = {"type": 1, "components": [{**_botao(botao_texto, f"ecop:comprar:{pid}", 3), "emoji": {"name": "🛒"}}]}
    tem_texto = any([titulo, descricao, imagem_url, miniatura_url, rodape])
    if mensagem_id and not tem_texto:
        payload: dict[str, Any] = {"components": [botoes]}
    else:
        payload = montar_mensagem(
            titulo=titulo or f'💎 {prod["nome"]}',
            descricao=descricao or (f'💰 **Valor:** {_reais(prod.get("preco"))}\n\n'
                                    "Clique em **Comprar agora** e um chat privado será criado só para você, "
                                    "com o QR Code do Pix. Pagou? Clique em **Confirmar pagamento**, informe seu "
                                    f"nome completo e o produto chega {_onde_entrega(prod)} assim que a equipe confirmar."),
            cor=cor, imagem_url=imagem_url, miniatura_url=miniatura_url, rodape=rodape or "ECO PULSE • Compra segura")
        payload["components"] = [botoes]
    msg = await _postar(canal["id"], payload, editar_id=mensagem_id)
    prod["painel"] = {"canal_id": canal["id"], "mensagem_id": msg["id"]}
    await salvar_config()
    return {"ok": True, "mensagem_id": msg["id"], "link": _link_canal(await servidor_id(), canal["id"], msg["id"])}


@mcp.tool(annotations=LEITURA)
async def ver_loja() -> dict:
    """Mostra os produtos da loja (preço, entrega, estoque, aprovador) e as compras em andamento."""
    await exigir_config()
    produtos = []
    for p in _cfg.get("produtos", {}).values():
        resumo = _resumo_produto(p)
        if p.get("canal_estoque_id"):
            resumo["itens_no_estoque"] = await _contar_estoque(p)
        produtos.append(resumo)
    compras = [{"canal": f"<#{cid}>", "canal_id": cid, "produto": c["produto"], "comprador": f'<@{c["comprador"]}>',
                "status": c["status"], "nome_completo": c.get("nome_completo"), "codigo": c["txid"],
                "aberta_em": _fmt(c["criado"])} for cid, c in _cfg.get("compras", {}).items()]
    return {"pix": "configurado" if (PIX_CHAVE or PIX_COPIA_COLA) else "não configurado (variável PIX_CHAVE no Render)",
            "produtos": produtos, "compras_em_andamento": compras,
            "canais_de_entrega": [{"canal": f"<#{cid}>", "comprador": f'<@{e["comprador"]}>', "produto": e["produto"],
                                   "codigo": e["txid"], "apaga_em": _fmt(e["fechar_em"])}
                                  for cid, e in _cfg.get("entregas", {}).items()]}


@mcp.tool(annotations=LEITURA)
async def resumo_vendas(dias: int = 30) -> dict:
    """Resumo das vendas confirmadas pelo bot: hoje, 7 dias, 30 dias, desde o início, por produto (nos últimos
    `dias`) e as últimas 5 vendas. É o mesmo que o comando /vendas mostra no Discord."""
    await exigir_config()
    return _resumo_vendas(max(1, min(3650, int(dias))))


# ── leitura detalhada ──

@mcp.tool(annotations=LEITURA)
async def ver_mensagem(mensagem: str, canal_id: str | None = None) -> dict:
    """Mostra uma mensagem por completo: texto, embeds inteiros (título, descrição, campos, cor, imagens, rodapé),
    botões e menus (texto, emoji e cor de cada um) e anexos. Use para copiar painéis de outros bots.
    mensagem = link da mensagem, "canal_id/mensagem_id" ou só o ID (passando canal_id)."""
    m = await _buscar_mensagem(mensagem, canal_id)
    resultado: dict[str, Any] = {
        "id": m["id"], "canal_id": m["channel_id"], "autor": m["author"].get("global_name") or m["author"]["username"],
        "autor_id": m["author"]["id"], "autor_e_bot": bool(m["author"].get("bot")), "quando": _fmt(m["timestamp"]),
        "texto": m.get("content") or "",
        "embeds": [{**_limpar_embed(e), **({"cor_hex": f'#{e["color"]:06x}'} if e.get("color") is not None else {})}
                   for e in m.get("embeds", [])],
        "botoes_e_menus": _resumo_componentes(m.get("components", [])),
        "anexos": [{"nome": a["filename"], "url": a["url"], "tipo": a.get("content_type")} for a in m.get("attachments", [])],
    }
    if m.get("pinned"):
        resultado["fixada"] = True
    if m["author"]["id"] != (await eu())["id"] and resultado["botoes_e_menus"]:
        resultado["obs"] = ("Os botões desta mensagem pertencem a outro bot e param de funcionar quando ele sai. "
                            "Para trocar, publique um painel novo com copiar_de apontando para esta mensagem.")
    return resultado


@mcp.tool(annotations=LEITURA)
async def info_canal(canal_id: str) -> dict:
    """Detalhes de um canal: tópico, categoria, modo lento e quem pode ver/escrever (permissões por cargo e membro)."""
    canal = await achar_canal(canal_id)
    gid = await servidor_id()
    cargos = {c["id"]: c["name"] for c in await _cargos()}
    info: dict[str, Any] = {"id": canal["id"], "nome": canal["name"], "tipo": TIPOS.get(canal["type"], str(canal["type"]))}
    if canal.get("topic"):
        info["topico"] = canal["topic"]
    if canal.get("parent_id"):
        try:
            info["categoria"] = (await dc("GET", f'/channels/{canal["parent_id"]}'))["name"]
        except ErroDiscord:
            info["categoria"] = canal["parent_id"]
    if canal.get("rate_limit_per_user"):
        info["modo_lento_segundos"] = canal["rate_limit_per_user"]
    regras = []
    for o in canal.get("permission_overwrites", []):
        alvo = "@everyone" if o["id"] == gid else (f'@{cargos.get(o["id"], o["id"])}' if o["type"] == 0 else f'membro <@{o["id"]}>')
        regras.append({"alvo": alvo, "permitido": _nomes_perm(int(o["allow"])), "negado": _nomes_perm(int(o["deny"]))})
    info["permissoes"] = regras or "segue a categoria/servidor"
    return info


# ── tickets ──

@mcp.tool()
async def publicar_painel_ticket(canal_id: str, titulo: str | None = None, descricao: str | None = None,
                                 cor: str | None = None, imagem_url: str | None = None, miniatura_url: str | None = None,
                                 rodape: str | None = None, botao_texto: str = "Abrir ticket", botao_emoji: str | None = "🎫",
                                 botao_cor: str = "azul", motivos: list[str] | None = None, categoria: str | None = None,
                                 cargos_equipe: list[str] | None = None, canal_historico: str | None = None,
                                 mensagem_abertura: str | None = None, avisar_equipe: bool = True,
                                 copiar_de: str | None = None, mensagem_id: str | None = None) -> dict:
    """Publica o painel de suporte: quem clica ganha um canal privado só com a equipe (o ticket), com botões
    para a equipe assumir e para fechar. Ao fechar, o histórico vai em .txt para canal_historico e para a DM da pessoa.
    motivos = assuntos para escolher num menu (ex.: ["Dúvida", "Compra", "Problema"]); sem motivos vira um botão.
    categoria = onde os tickets são criados. cargos_equipe = quem atende (nomes ou IDs).
    mensagem_abertura aceita {usuario} e {nome}. copiar_de = link/ID de outra mensagem (ex.: painel de outro bot)
    para reaproveitar título, texto, cor e imagens; o que você passar por cima substitui.
    mensagem_id = atualizar um painel deste bot que já existe em vez de publicar outro."""
    await exigir_config()
    canal = await achar_canal(canal_id, tipos=TIPOS_MENSAGEM)
    embed, texto = await _montar_painel(
        copiar_de=copiar_de, titulo=titulo, descricao=descricao, cor=cor, imagem_url=imagem_url,
        miniatura_url=miniatura_url, rodape=rodape, titulo_padrao="🎫 Suporte",
        descricao_padrao="Precisa de ajuda? Clique no botão abaixo para abrir um ticket. Só você e a equipe vão ver a conversa.")
    pid = next((k for k, p in _cfg["paineis"].items() if mensagem_id and p.get("mensagem_id") == mensagem_id), None) \
        or secrets.token_hex(3)
    painel: dict[str, Any] = {"id": pid, "tipo": "ticket", "canal_id": canal["id"], "canal_nome": canal["name"],
                              "avisar_equipe": avisar_equipe, "cor": embed.get("color"),
                              "botao_texto": botao_texto, "botao_emoji": botao_emoji, "botao_cor": botao_cor}
    if categoria:
        cat = await achar_categoria(categoria)
        painel.update(categoria_id=cat["id"], categoria_nome=cat["name"])
    painel["cargos_equipe"] = [{"id": c["id"], "nome": c["name"]} for c in [await achar_cargo(x) for x in (cargos_equipe or [])]]
    if canal_historico:
        h = await achar_canal(canal_historico, tipos=TIPOS_MENSAGEM)
        painel.update(canal_historico_id=h["id"], canal_historico_nome=h["name"])
    if mensagem_abertura:
        painel["mensagem_abertura"] = mensagem_abertura[:3500]
    motivos = [m.strip()[:100] for m in (motivos or []) if m and m.strip()][:25]
    if motivos:
        painel["motivos"] = motivos
        componente = {"type": 1, "components": [{
            "type": 3, "custom_id": f"ecot:abrir:{pid}", "placeholder": (botao_texto or "Escolha o assunto")[:150],
            "options": [{"label": m, "value": str(i), **({"emoji": _emoji_botao(botao_emoji)} if botao_emoji else {})}
                        for i, m in enumerate(motivos)]}]}
    else:
        componente = _linha(_botao_painel(botao_texto, f"ecot:abrir:{pid}", botao_cor, botao_emoji))
    payload: dict[str, Any] = {"embeds": [embed], "components": [componente], "allowed_mentions": {"parse": []}}
    if texto:
        payload["content"] = texto
    msg = await _postar(canal["id"], payload, editar_id=mensagem_id)
    painel["mensagem_id"] = msg["id"]
    _cfg["paineis"][pid] = painel
    await salvar_config()
    return {"ok": True, "painel_id": pid, "canal": canal["name"], "mensagem_id": msg["id"],
            "link": _link_canal(await servidor_id(), canal["id"], msg["id"]),
            "tickets_em": painel.get("categoria_nome") or "fora de categoria",
            "equipe": [c["nome"] for c in painel["cargos_equipe"]] or "só administradores",
            "historico_em": painel.get("canal_historico_nome") or ("canal de registros" if (_cfg.get("logs") or {}).get("ativo") else "nenhum")}


@mcp.tool(annotations=DESTRUTIVA)
async def fechar_ticket(canal_id: str, confirmado: bool = False) -> str:
    """Fecha um ticket aberto: salva o histórico, avisa a pessoa por DM e apaga o canal.
    Só chame com confirmado=true depois que o usuário confirmar."""
    await exigir_config()
    canal = await achar_canal(canal_id)
    t = _cfg["tickets"].get(canal["id"])
    if not t:
        raise ErroDiscord(f'#{canal["name"]} não é um ticket aberto por este bot.')
    if not confirmado:
        return f'⚠️ Nada foi fechado. Confirme com o usuário que ele quer fechar o ticket #{canal["name"]} de {t.get("dono_nome")}. Depois chame com confirmado=true.'
    await dc("POST", f'/channels/{canal["id"]}/messages', corpo={
        "content": f"🔒 Ticket fechado pela equipe. O histórico foi salvo e este canal some em {FECHAR_TICKET_EM} segundos."})
    await encerrar_ticket(canal["id"], None, "a equipe (pelo Claude)")
    return f'✅ Ticket #{canal["name"]} fechado e histórico salvo.'


# ── verificação ──

@mcp.tool()
async def publicar_painel_verificacao(canal_id: str, cargo: str, titulo: str | None = None, descricao: str | None = None,
                                      cor: str | None = None, imagem_url: str | None = None, miniatura_url: str | None = None,
                                      rodape: str | None = None, botao_texto: str = "Verificar", botao_emoji: str | None = "✅",
                                      botao_cor: str = "verde", tirar_cargo: str | None = None,
                                      mensagem_sucesso: str | None = None, copiar_de: str | None = None,
                                      mensagem_id: str | None = None) -> dict:
    """Publica o painel de verificação: quem clica no botão ganha o cargo (ex.: Membro) e passa a ver o servidor.
    tirar_cargo = cargo de "não verificado" para remover ao verificar. copiar_de = link/ID de outra mensagem
    para reaproveitar o visual. mensagem_id = atualizar um painel deste bot que já existe."""
    await exigir_config()
    canal = await achar_canal(canal_id, tipos=TIPOS_MENSAGEM)
    c = await achar_cargo(cargo)
    if c["id"] == await servidor_id() or c.get("managed"):
        raise ErroDiscord("Esse cargo não pode ser dado pela verificação.")
    embed, texto = await _montar_painel(
        copiar_de=copiar_de, titulo=titulo, descricao=descricao, cor=cor, imagem_url=imagem_url,
        miniatura_url=miniatura_url, rodape=rodape, titulo_padrao="🔐 Verificação",
        descricao_padrao="Clique no botão abaixo para se verificar e liberar o acesso ao servidor.")
    pid = next((k for k, p in _cfg["paineis"].items() if mensagem_id and p.get("mensagem_id") == mensagem_id), None) \
        or secrets.token_hex(3)
    painel: dict[str, Any] = {"id": pid, "tipo": "verificacao", "canal_id": canal["id"], "canal_nome": canal["name"],
                              "cargo_id": c["id"], "cargo_nome": c["name"],
                              "botao_texto": botao_texto, "botao_emoji": botao_emoji, "botao_cor": botao_cor}
    if tirar_cargo:
        t = await achar_cargo(tirar_cargo)
        painel.update(tirar_cargo_id=t["id"], tirar_cargo_nome=t["name"])
    if mensagem_sucesso:
        painel["mensagem_sucesso"] = mensagem_sucesso[:1500]
    payload: dict[str, Any] = {"embeds": [embed], "allowed_mentions": {"parse": []},
                               "components": [_linha(_botao_painel(botao_texto, f"ecov:{pid}", botao_cor, botao_emoji))]}
    if texto:
        payload["content"] = texto
    msg = await _postar(canal["id"], payload, editar_id=mensagem_id)
    painel["mensagem_id"] = msg["id"]
    _cfg["paineis"][pid] = painel
    await salvar_config()
    return {"ok": True, "painel_id": pid, "canal": canal["name"], "cargo": c["name"], "mensagem_id": msg["id"],
            "link": _link_canal(await servidor_id(), canal["id"], msg["id"])}


# ── sorteios ──

@mcp.tool()
async def criar_sorteio(canal_id: str, premio: str, termina: str, vencedores: int = 1, descricao: str | None = None,
                        titulo: str | None = None, cor: str | None = None, imagem_url: str | None = None,
                        cargo_obrigatorio: str | None = None, mencionar_todos: bool = False,
                        botao_texto: str = "Participar", botao_emoji: str | None = "🎉",
                        copiar_de: str | None = None) -> dict:
    """Cria um sorteio com botão Participar. Quando chega a hora, o bot sorteia sozinho, anuncia e marca os ganhadores
    (mesmo com o Claude fechado). termina: "daqui a 3 dias", "30/10 20:00", "2026-11-05 18:00", "amanhã 20h"
    (horário de Brasília). cargo_obrigatorio = só quem tem o cargo participa. copiar_de = link/ID de outra mensagem
    (ex.: sorteio de outro bot) para reaproveitar título, texto e imagem."""
    await exigir_config()
    canal = await achar_canal(canal_id, tipos=TIPOS_MENSAGEM)
    fim = _ler_quando(termina)
    agora = _agora()
    if fim.astimezone(timezone.utc) <= agora + timedelta(minutes=1):
        raise ErroDiscord(f"O fim do sorteio ({_fmt(fim)}) precisa ser no futuro.")
    if fim.astimezone(timezone.utc) > agora + timedelta(days=60):
        raise ErroDiscord("O sorteio pode durar no máximo 60 dias.")
    vencedores = max(1, min(20, int(vencedores)))
    base: dict[str, Any] = {}
    if copiar_de:
        base, _ = await _montar_painel(copiar_de=copiar_de, titulo=None, descricao=None, cor=None, imagem_url=None,
                                       miniatura_url=None, rodape=None, titulo_padrao="", descricao_padrao="")
    sid = secrets.token_hex(3)
    s: dict[str, Any] = {
        "id": sid, "canal_id": canal["id"], "canal_nome": canal["name"], "premio": premio[:200],
        "titulo": (titulo or base.get("title") or None), "descricao": descricao if descricao is not None else (base.get("description") or None),
        "vencedores": vencedores, "fim": fim.astimezone(timezone.utc).isoformat(), "status": "ativo",
        "participantes": [], "ganhadores": [], "cor": _cor(cor) if cor else base.get("color"),
        "imagem_url": imagem_url or (base.get("image") or {}).get("url"),
        "miniatura_url": (base.get("thumbnail") or {}).get("url"),
        "botao_texto": botao_texto, "botao_emoji": botao_emoji, "criado": agora.isoformat(),
    }
    if s["descricao"] and len(s["descricao"]) > 3500:
        raise ErroDiscord("A descrição do sorteio passou de 3500 caracteres.")
    if cargo_obrigatorio:
        c = await achar_cargo(cargo_obrigatorio)
        s.update(cargo_obrigatorio_id=c["id"], cargo_obrigatorio_nome=c["name"])
    payload: dict[str, Any] = {"embeds": [_embed_sorteio(s)], "components": [_botoes_sorteio(s)],
                               "allowed_mentions": {"parse": ["everyone"] if mencionar_todos else []}}
    if mencionar_todos:
        payload["content"] = "@everyone"
    msg = await _postar(canal["id"], payload)
    s["mensagem_id"] = msg["id"]
    nomes = {a["filename"] for a in msg.get("attachments", [])}
    for k in ("image", "thumbnail"):
        url = ((msg.get("embeds") or [{}])[0].get(k) or {}).get("url") or ""
        arq = url.split("?")[0].rsplit("/", 1)[-1]
        if arq in nomes:
            s[f"{k}_arquivo"] = arq
    _cfg["sorteios"][sid] = s
    await salvar_config()
    return {"ok": True, "sorteio_id": sid, "canal": canal["name"], "premio": s["premio"], "termina": _fmt(fim),
            "vencedores": vencedores, "link": _link_canal(await servidor_id(), canal["id"], msg["id"])}


def _achar_sorteio(sorteio_id: str) -> dict:
    s = _cfg.get("sorteios", {}).get(str(sorteio_id).strip().strip("`"))
    if not s:
        raise ErroDiscord(f"Não achei o sorteio {sorteio_id}. Use listar_automacoes para ver os IDs.")
    return s


@mcp.tool()
async def encerrar_sorteio(sorteio_id: str) -> dict:
    """Termina um sorteio agora: sorteia os ganhadores, anuncia no canal e atualiza a mensagem."""
    await exigir_config()
    s = _achar_sorteio(sorteio_id)
    if s["status"] != "ativo":
        raise ErroDiscord("Esse sorteio não está mais ativo. Para escolher outro ganhador, use sortear_de_novo.")
    ganhadores = await finalizar_sorteio(s)
    return {"ok": True, "premio": s["premio"], "participantes": len(s.get("participantes", [])),
            "ganhadores": [f"<@{g}>" for g in ganhadores] or "ninguém participou"}


@mcp.tool()
async def sortear_de_novo(sorteio_id: str, vencedores: int = 1) -> dict:
    """Escolhe novo(s) ganhador(es) de um sorteio já encerrado (ex.: o ganhador não respondeu), sem repetir os anteriores."""
    await exigir_config()
    s = _achar_sorteio(sorteio_id)
    if s["status"] != "encerrado":
        raise ErroDiscord("Só dá para sortear de novo um sorteio já encerrado.")
    anteriores = set(s.get("ganhadores", [])) | set(s.get("ja_sorteados", []))
    novos = await _sortear(s, max(1, min(20, int(vencedores))), anteriores)
    s["ja_sorteados"] = sorted(anteriores)
    s["ganhadores"] = novos or s.get("ganhadores", [])
    await salvar_config()
    if novos:
        await _atualizar_mensagem_sorteio(s)
    await _anunciar_ganhadores(s, novos, novo_sorteio=True)
    return {"ok": True, "novos_ganhadores": [f"<@{g}>" for g in novos] or "não sobrou ninguém para sortear"}


@mcp.tool(annotations=DESTRUTIVA)
async def cancelar_sorteio(sorteio_id: str, confirmado: bool = False) -> str:
    """Cancela um sorteio ativo sem escolher ganhador. Só chame com confirmado=true depois que o usuário confirmar."""
    await exigir_config()
    s = _achar_sorteio(sorteio_id)
    if s["status"] != "ativo":
        raise ErroDiscord("Esse sorteio não está ativo.")
    if not confirmado:
        return f'⚠️ Nada foi cancelado. Confirme com o usuário que ele quer cancelar o sorteio de "{s["premio"]}" ({len(s.get("participantes", []))} participantes). Depois chame com confirmado=true.'
    s["status"] = "cancelado"
    await salvar_config()
    await _atualizar_mensagem_sorteio(s)
    return f'✅ Sorteio de "{s["premio"]}" cancelado.'


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
            "comunidade": "COMMUNITY" in g.get("features", []), "descricao": g.get("description")}


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
        "comandos_de_barra": "registrados (" + ", ".join("/" + c["name"] for c in COMANDOS) + ")" if _comandos_registrados
                             else "ainda não registrados",
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


# ───────────────────────── comandos de barra (/) — os mesmos do bot antigo ─────────────────────────

_CANAL_TEXTO = {"type": 7, "name": "canal", "description": "Canal do painel (vazio = este canal)", "required": False,
                "channel_types": [0, 5]}
COMANDOS: list[dict[str, Any]] = [
    {"name": "ping", "description": "Testar o bot", "type": 1},
    {"name": "loja_painel", "description": "Publicar ou atualizar o painel de compra de um produto da loja", "type": 1,
     "default_member_permissions": "8",
     "options": [{"type": 3, "name": "produto", "description": "Produto (vazio = o do painel deste canal)",
                  "required": False, "autocomplete": True}, _CANAL_TEXTO]},
    {"name": "vendas", "description": "Resumo das vendas", "type": 1, "default_member_permissions": "8"},
    {"name": "pedidos_pendentes", "description": "Consultar pedidos pendentes", "type": 1, "default_member_permissions": "8"},
    {"name": "aprovar_pagamento", "description": "Aprovar pedido após conferir o recebimento do Pix", "type": 1,
     "default_member_permissions": "8",
     "options": [{"type": 3, "name": "pedido", "description": "Código do pedido (vazio = o pedido deste chat)",
                  "required": False, "autocomplete": True}]},
    {"name": "ticket_painel", "description": "Publicar ou atualizar o painel de tickets de suporte", "type": 1,
     "default_member_permissions": "8", "options": [_CANAL_TEXTO]},
    {"name": "verificacao_painel", "description": "Publicar ou atualizar o painel de verificação", "type": 1,
     "default_member_permissions": "8",
     "options": [{"type": 8, "name": "cargo", "description": "Cargo que a pessoa ganha ao se verificar", "required": False},
                 _CANAL_TEXTO]},
]
_NOMES_COMANDOS = {c["name"] for c in COMANDOS}
_comandos_registrados = False


async def registrar_comandos(app_id: str) -> None:
    global _comandos_registrados
    if _comandos_registrados:
        return
    try:
        await dc("PUT", f"/applications/{app_id}/guilds/{await servidor_id()}/commands", corpo=COMANDOS)
        _comandos_registrados = True
        log.info("Comandos de barra registrados: %s", ", ".join("/" + c["name"] for c in COMANDOS))
    except Exception as erro:
        log.warning("Não consegui registrar os comandos de barra: %s", erro)


def _resumo_vendas(dias: int | None = None) -> dict:
    vendas = _cfg.get("vendas", [])
    agora = _agora()
    hoje = agora.astimezone(FUSO).date()

    def soma(lista):
        total = sum(v.get("valor") or 0 for v in lista)
        return {"vendas": len(lista), "total": _reais(total) if total else "R$ 0,00"}

    def desde(delta):
        return [v for v in vendas if datetime.fromisoformat(v["quando"]) >= agora - delta]

    resumo: dict[str, Any] = {
        "hoje": soma([v for v in vendas if datetime.fromisoformat(v["quando"]).astimezone(FUSO).date() == hoje]),
        "ultimos_7_dias": soma(desde(timedelta(days=7))),
        "ultimos_30_dias": soma(desde(timedelta(days=30))),
        "desde_o_inicio": soma(vendas),
    }
    janela = desde(timedelta(days=dias)) if dias else vendas
    por_produto: dict[str, list] = {}
    for v in janela:
        por_produto.setdefault(v.get("produto_nome") or v["produto"], []).append(v)
    resumo["por_produto"] = {k: soma(lista) for k, lista in sorted(por_produto.items(), key=lambda x: -len(x[1]))}
    resumo["ultimas"] = [{"quando": _fmt(v["quando"]), "produto": v.get("produto_nome") or v["produto"],
                          "valor": _reais(v.get("valor")), "comprador": f'<@{v["comprador"]}>', "codigo": v["txid"]}
                         for v in reversed(vendas[-5:])]
    return resumo


def _embed_vendas() -> dict:
    r = _resumo_vendas(30)
    linhas = [f'📅 **Hoje:** {r["hoje"]["vendas"]} venda(s) • {r["hoje"]["total"]}',
              f'🗓️ **7 dias:** {r["ultimos_7_dias"]["vendas"]} • {r["ultimos_7_dias"]["total"]}',
              f'📆 **30 dias:** {r["ultimos_30_dias"]["vendas"]} • {r["ultimos_30_dias"]["total"]}',
              f'🏁 **Desde o início:** {r["desde_o_inicio"]["vendas"]} • {r["desde_o_inicio"]["total"]}']
    if r["por_produto"]:
        linhas += ["", "**Por produto (30 dias)**"] + [f'• {k}: {v["vendas"]} • {v["total"]}' for k, v in r["por_produto"].items()]
    if r["ultimas"]:
        linhas += ["", "**Últimas vendas**"] + [f'• {u["quando"]} — {u["produto"]} • {u["valor"]} • {u["comprador"]} `{u["codigo"]}`'
                                               for u in r["ultimas"]]
    if not _cfg.get("vendas"):
        linhas += ["", "_Nenhuma venda confirmada por este bot ainda._"]
    return {"title": "📊 Resumo das vendas", "description": "\n".join(linhas)[:4096], "color": COR_PADRAO,
            "footer": {"text": "Conta as vendas confirmadas pelo ECO PULSE 2"}}


_STATUS_PEDIDO = {"aguardando": "⏳ aguardando pagamento", "analise": "🧾 pagamento informado — conferir",
                  "entregando": "📦 entregando"}


def _pendentes() -> list[tuple[str, dict]]:
    return sorted(((cid, c) for cid, c in _cfg.get("compras", {}).items() if c["status"] in _STATUS_PEDIDO),
                  key=lambda x: (x[1]["status"] != "analise", x[1]["criado"]))


def _embed_pendentes() -> dict:
    itens = _pendentes()
    if not itens:
        return {"title": "📋 Pedidos pendentes", "description": "Nenhum pedido pendente. 🎉", "color": COR_PADRAO}
    linhas = []
    for cid, c in itens[:20]:
        prod = _cfg.get("produtos", {}).get(c["produto"], {})
        linhas.append(f'**`{c["txid"]}`** • {prod.get("nome", c["produto"])} • {_reais(c.get("valor"))}\n'
                      f'{_STATUS_PEDIDO[c["status"]]} • <@{c["comprador"]}>'
                      + (f' ({c["nome_completo"]})' if c.get("nome_completo") else "")
                      + f' • <#{cid}> • {_fmt(c.get("informado") or c["criado"])}')
    if len(itens) > 20:
        linhas.append(f"… e mais {len(itens) - 20}.")
    return {"title": f"📋 Pedidos pendentes ({len(itens)})", "description": "\n\n".join(linhas)[:4096], "color": CORES["amarelo"],
            "footer": {"text": "Para aprovar: /aprovar_pagamento pedido:CÓDIGO (ou use o comando dentro do chat da compra)"}}


def _opcoes(dados: dict) -> dict[str, Any]:
    return {o["name"]: o.get("value") for o in dados.get("options", []) or []}


async def _cmd_ping(r: _Resposta) -> None:
    lat = getattr(_bot, "latency", None)
    ms = f"{lat * 1000:.0f} ms" if isinstance(lat, (int, float)) and lat == lat and lat < 60 else "?"
    minutos = int((time.time() - INICIO) / 60)
    await r.efemera(f"🏓 Pong! ECO PULSE 2 online há {minutos // 60}h{minutos % 60:02d}min • latência {ms} • versão {VERSAO}")


async def _cmd_ticket_painel(r: _Resposta, op: dict) -> None:
    await r.adiar()
    await exigir_config()
    canal_id = str(op.get("canal") or r.inter.channel_id)
    paineis = [p for p in _cfg["paineis"].values() if p["tipo"] == "ticket"]
    aqui = next((p for p in paineis if p["canal_id"] == canal_id), None)
    base = aqui or (paineis[-1] if paineis else None)
    if base:
        kw: dict[str, Any] = dict(
            categoria=base.get("categoria_id"), cargos_equipe=[c["id"] for c in base.get("cargos_equipe", [])],
            canal_historico=base.get("canal_historico_id"), motivos=base.get("motivos"),
            mensagem_abertura=base.get("mensagem_abertura"), avisar_equipe=base.get("avisar_equipe", True),
            botao_texto=base.get("botao_texto") or "Abrir ticket", botao_emoji=base.get("botao_emoji", "🎫"),
            botao_cor=base.get("botao_cor") or "azul", copiar_de=f'{base["canal_id"]}/{base["mensagem_id"]}')
    else:
        canais, cargos = await _canais(), await _cargos()
        cat = next((c for c in canais if c["type"] == 4 and "ticket" in _norm(c["name"])), None)
        hist = next((c for c in canais if c["type"] == 0 and "ticketsfechados" in _norm(c["name"])), None)
        kw = dict(categoria=cat["id"] if cat else None, canal_historico=hist["id"] if hist else None,
                  cargos_equipe=[c["id"] for c in cargos if not c.get("managed")
                                 and any(k in _norm(c["name"]) for k in ("suporte", "moderador", "administrador", "fundador"))])
    try:
        res = await publicar_painel_ticket(canal_id=canal_id, mensagem_id=aqui["mensagem_id"] if aqui else None, **kw)
    except ErroDiscord as erro:
        if not aqui or erro.codigo != 10008:
            raise
        _cfg["paineis"].pop(aqui["id"], None)  # a mensagem do painel foi apagada: publica um novo
        kw.pop("copiar_de", None)
        res = await publicar_painel_ticket(canal_id=canal_id, **kw)
        aqui = None
    await r.efemera(f'✅ Painel de tickets {"atualizado" if aqui else "publicado"} em <#{canal_id}>.\n'
                    f'Tickets em: {res["tickets_em"]} • Equipe: {", ".join(res["equipe"]) if isinstance(res["equipe"], list) else res["equipe"]}'
                    f' • Histórico: {res["historico_em"]}\nPara mudar textos ou imagem, peça ao Claude.')


async def _cmd_verificacao_painel(r: _Resposta, op: dict) -> None:
    await r.adiar()
    await exigir_config()
    canal_id = str(op.get("canal") or r.inter.channel_id)
    paineis = [p for p in _cfg["paineis"].values() if p["tipo"] == "verificacao"]
    aqui = next((p for p in paineis if p["canal_id"] == canal_id), None)
    base = aqui or (paineis[-1] if paineis else None)
    cargo = op.get("cargo") or (base or {}).get("cargo_id")
    if not cargo:
        membro = next((c for c in await _cargos() if "membro" in _norm(c["name"]) and not c.get("managed")), None)
        if not membro:
            await r.efemera("Escolha o cargo que a pessoa ganha na opção **cargo** do comando.")
            return
        cargo = membro["id"]
    kw: dict[str, Any] = {"cargo": str(cargo)}
    if base:
        kw.update(tirar_cargo=base.get("tirar_cargo_id"), mensagem_sucesso=base.get("mensagem_sucesso"),
                  botao_texto=base.get("botao_texto") or "Verificar", botao_emoji=base.get("botao_emoji", "✅"),
                  botao_cor=base.get("botao_cor") or "verde", copiar_de=f'{base["canal_id"]}/{base["mensagem_id"]}')
    try:
        res = await publicar_painel_verificacao(canal_id=canal_id, mensagem_id=aqui["mensagem_id"] if aqui else None, **kw)
    except ErroDiscord as erro:
        if not aqui or erro.codigo != 10008:
            raise
        _cfg["paineis"].pop(aqui["id"], None)
        kw.pop("copiar_de", None)
        res = await publicar_painel_verificacao(canal_id=canal_id, **kw)
        aqui = None
    await r.efemera(f'✅ Painel de verificação {"atualizado" if aqui else "publicado"} em <#{canal_id}>. '
                    f'Quem clicar ganha o cargo **{res["cargo"]}**.')


async def _cmd_loja_painel(r: _Resposta, op: dict) -> None:
    await r.adiar()
    await exigir_config()
    produtos = _cfg.get("produtos", {})
    if not produtos:
        await r.efemera("Nenhum produto cadastrado ainda. Peça ao Claude para cadastrar o produto (nome, preço e "
                        "canal de estoque) e depois use **/loja_painel** de novo.")
        return
    canal_id = str(op.get("canal") or r.inter.channel_id)
    pid = _slug(op.get("produto") or "", 40)
    if pid and pid not in produtos:
        pid = next((k for k, p in produtos.items() if _norm(p.get("nome")) == _norm(op.get("produto"))), "")
    if not pid:
        pid = next((k for k, p in produtos.items() if (p.get("painel") or {}).get("canal_id") == canal_id), "")
        if not pid and len(produtos) == 1:
            pid = next(iter(produtos))
    if not pid:
        await r.efemera("Escolha o produto na opção **produto**: " + ", ".join(p["nome"] for p in produtos.values()))
        return
    painel = produtos[pid].get("painel") or {}
    editar = painel.get("mensagem_id") if painel.get("canal_id") == canal_id else None
    try:
        await publicar_painel_compra(canal_id=canal_id, produto=pid, mensagem_id=editar)
    except ErroDiscord as erro:
        if not editar or erro.codigo != 10008:
            raise
        editar = None
        await publicar_painel_compra(canal_id=canal_id, produto=pid)
    await r.efemera(f'✅ Painel de **{produtos[pid]["nome"]}** {"atualizado" if editar else "publicado"} em <#{canal_id}>.')


async def _cmd_aprovar(r: _Resposta, op: dict) -> None:
    await r.adiar()
    await exigir_config()
    codigo = re.sub(r"[^A-Z0-9]", "", str(op.get("pedido") or "").upper())
    achado = None
    for cid, c in _cfg.get("compras", {}).items():
        if (codigo and c["txid"].upper() == codigo) or (not codigo and cid == str(r.inter.channel_id)):
            achado = (cid, c)
            break
    if not achado:
        await r.efemera("Não achei esse pedido. Veja os códigos em **/pedidos_pendentes**." if codigo else
                        "Use este comando dentro do chat da compra ou informe o código do pedido.")
        return
    canal, c = achado
    prod = _cfg.get("produtos", {}).get(c["produto"], {"nome": c["produto"]})
    if not _pode_aprovar(r.inter, prod):
        await r.efemera(f'Só quem tem o cargo {prod.get("cargo_aprovador_nome") or "Fundador"} pode aprovar pagamentos.')
        return
    if c["status"] not in ("aguardando", "analise"):
        await r.efemera("Esse pedido já foi decidido.")
        return
    c.setdefault("nome_completo", "não informado")
    embed = {"title": f'🧾 Pedido `{c["txid"]}`', "color": CORES["amarelo"],
             "description": f'**{prod.get("nome")}** • {_reais(c.get("valor"))}\nComprador: <@{c["comprador"]}> • chat <#{canal}>'}
    status_antes = c["status"]
    c["status"] = "entregando"
    try:
        await _aprovar(r, canal, c, prod, str(r.inter.user.id), embed)
    except Exception:
        if c.get("status") == "entregando":
            c["status"] = status_antes
        raise


async def _autocompletar(r: _Resposta, nome: str, dados: dict) -> None:
    foco = next((o for o in dados.get("options", []) if o.get("focused")), {})
    texto = _norm(foco.get("value") or "")
    escolhas: list[dict] = []
    if nome == "loja_painel":
        escolhas = [{"name": p["nome"][:100], "value": k} for k, p in _cfg.get("produtos", {}).items()
                    if not texto or texto in _norm(p["nome"]) or texto in _norm(k)]
    elif nome == "aprovar_pagamento":
        for cid, c in _pendentes():
            if c["status"] == "entregando":
                continue
            prod = _cfg.get("produtos", {}).get(c["produto"], {})
            rotulo = f'{c["txid"]} • {prod.get("nome", c["produto"])} • {c.get("nome_completo") or c.get("comprador_nome") or ""}'
            if not texto or texto in _norm(rotulo):
                escolhas.append({"name": rotulo[:100], "value": c["txid"]})
    await r.enviar(8, {"choices": escolhas[:25]})


async def ao_comando(inter: Any, tipo: int, dados: dict) -> None:
    nome = dados.get("name")
    if nome not in _NOMES_COMANDOS:
        return
    r = _Resposta(inter)
    try:
        if tipo == 4:
            await _autocompletar(r, nome, dados)
            return
        op = _opcoes(dados)
        if nome == "ping":
            await _cmd_ping(r)
        elif nome == "vendas":
            await r.adiar()
            await exigir_config()
            await r.editar_original({"embeds": [_embed_vendas()], "allowed_mentions": {"parse": []}})
            r.adiada = False
        elif nome == "pedidos_pendentes":
            await r.adiar()
            await exigir_config()
            await r.editar_original({"embeds": [_embed_pendentes()], "allowed_mentions": {"parse": []}})
            r.adiada = False
        elif nome == "aprovar_pagamento":
            await _cmd_aprovar(r, op)
        elif nome == "ticket_painel":
            await _cmd_ticket_painel(r, op)
        elif nome == "verificacao_painel":
            await _cmd_verificacao_painel(r, op)
        elif nome == "loja_painel":
            await _cmd_loja_painel(r, op)
    except Exception as erro:
        log.exception("Falha no comando /%s", nome)
        if tipo == 4:
            return
        texto = str(erro) if isinstance(erro, ErroDiscord) else "Deu um erro aqui. Tente de novo ou chame o Claude."
        try:
            await r.efemera(f"⚠️ {texto}")
        except Exception:
            pass


# ───────────────────────── app web ─────────────────────────

_SEGURANCA = TransportSecuritySettings(enable_dns_rebinding_protection=False)
_PREFIXO = f"/{CHAVE}" if CHAVE else ""
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
        log.info("Agente ECO PULSE %s no ar (MCP em %s/mcp e %s/sse)", VERSAO, _PREFIXO or "", _PREFIXO or "")
        try:
            yield
        finally:
            for t in tarefas:
                t.cancel()
            await _salvar_pendente()
            if _bot is not None:
                try:
                    await _bot.close()
                except Exception:
                    pass
            for c in (_api, _web):
                if c is not None:
                    await c.aclose()


app = Starlette(routes=[Route("/", saude), Route("/saude", saude), *_app_http.routes, *_app_sse.routes],
                lifespan=ciclo_de_vida)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORTA, proxy_headers=True, forwarded_allow_ips="*")
