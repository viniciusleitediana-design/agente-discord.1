"""Peças das mensagens: botões, linhas de componentes, formulários e embeds."""

import re
from copy import deepcopy
from typing import Any

def _botao(rotulo: str, custom_id: str, estilo: int = 1, emoji: str | None = None) -> dict:
    b: dict[str, Any] = {"type": 2, "style": estilo, "label": rotulo[:80], "custom_id": custom_id[:100]}
    if emoji:
        b["emoji"] = {"name": emoji}
    return b


def _linha(*botoes: dict) -> dict:
    return {"type": 1, "components": list(botoes)[:5]}


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


# Importados no fim: estes módulos também usam este aqui (evita import circular).
from .paineis import _ESTILOS_BOTAO
from .util import CORES, _norm
