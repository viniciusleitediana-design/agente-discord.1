"""Utilidades: datas, textos, cores, permissões e montagem de mensagens."""

import re
import unicodedata
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

from . import estado

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


async def _servidores_do_bot() -> str:
    try:
        lista = await dc("GET", "/users/@me/guilds")
    except ErroDiscord:
        return "não consegui listar"
    return ", ".join(f'{s["name"]} (ID {s["id"]})' for s in lista) or "nenhum"


async def servidor_id() -> str:
    if estado._servidor and not estado._servidor_ok:
        try:
            await dc("GET", f"/guilds/{estado._servidor}")
            estado._servidor_ok = True
        except ErroDiscord as erro:
            if erro.status in (403, 404):
                raise ErroDiscord(
                    f"O bot não está no servidor {estado._servidor} (variável GUILD_ID no Render). "
                    f"Servidores em que ele está: {await _servidores_do_bot()}. Convide o bot para o "
                    f"ECO PULSE (Developer Portal → OAuth2 → URL Generator → bot + Administrator) "
                    f"ou corrija GUILD_ID.", erro.status, erro.codigo)
            raise
    if estado._servidor:
        return estado._servidor
    servidores = await dc("GET", "/users/@me/guilds")
    if not servidores:
        raise ErroDiscord("O bot não está em nenhum servidor. Convide-o pelo Developer Portal → OAuth2 → URL Generator.")
    if len(servidores) == 1:
        estado._servidor = servidores[0]["id"]
        return estado._servidor
    for s in servidores:
        if "ecopulse" in _norm(s["name"]):
            estado._servidor = s["id"]
            return estado._servidor
    nomes = ", ".join(f'{s["name"]} ({s["id"]})' for s in servidores)
    raise ErroDiscord(f"O bot está em vários servidores: {nomes}. Coloque o ID do ECO PULSE na variável GUILD_ID no Render.")


async def eu() -> dict:
    if estado._eu is None:
        estado._eu = await dc("GET", "/users/@me")
    return estado._eu


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


def _ts(dt: datetime | str) -> int:
    if isinstance(dt, str):
        dt = datetime.fromisoformat(dt)
    return int(dt.timestamp())


# Importados no fim: estes módulos também usam este aqui (evita import circular).
from .config import COR_PADRAO, FUSO
from .discord_api import ErroDiscord, dc
