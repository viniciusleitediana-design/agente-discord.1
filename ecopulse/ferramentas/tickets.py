"""Ferramentas do conector: tickets."""

import secrets
from typing import Any

from ..conector import DESTRUTIVA, mcp

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


# Importados no fim: estes módulos também usam este aqui (evita import circular).
from ..busca import _link_canal, achar_canal, achar_cargo, achar_categoria
from ..discord_api import ErroDiscord, dc
from ..interface import _botao_painel, _emoji_botao, _linha
from ..memoria import _cfg, exigir_config, salvar_config
from ..paineis import FECHAR_TICKET_EM, _montar_painel, _postar
from ..tickets import encerrar_ticket
from ..util import TIPOS_MENSAGEM, servidor_id
