"""Base dos painéis da comunidade: copiar visual de outra mensagem, imagens e botões."""

import asyncio
import json
import re
from copy import deepcopy
from typing import Any

FECHAR_TICKET_EM = 5                       # segundos entre "Fechar" e o canal sumir
_CDN_ANEXO = re.compile(r"^https://(?:cdn\.discordapp\.com|media\.discordapp\.net)/(?:ephemeral-)?attachments/", re.I)
_ESTILOS_BOTAO = {"azul": 1, "roxo": 1, "primario": 1, "cinza": 2, "secundario": 2, "verde": 3, "vermelho": 4}
_ticket_lock = asyncio.Lock()
_tarefas_sorteio: dict[str, asyncio.Task] = {}


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


# Importados no fim: estes módulos também usam este aqui (evita import circular).
from .busca import achar_canal
from .config import COR_PADRAO, log
from .discord_api import ErroDiscord, cliente_web, dc
from .loja import _ids_cargos
from .memoria import _canal_config, _cfg_estado
from .util import _cor, _slug, servidor_id
