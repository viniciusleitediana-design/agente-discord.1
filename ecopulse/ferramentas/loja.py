"""Ferramentas do conector: loja."""

import re
from typing import Any

from ..conector import LEITURA, mcp

# ── loja (compra em chat privado com Pix) ──

def _resumo_produto(p: dict) -> dict:
    return {
        "id": p["id"], "nome": p.get("nome"), "preco": _reais(p.get("preco")), "ativo": p.get("ativo", True),
        "aprovador": p.get("cargo_aprovador_nome") or "nenhum (só o dono do servidor)",
        "cargo_cliente": p.get("cargo_cliente_nome") or "nenhum",
        "canal_estoque": f'<#{p["canal_estoque_id"]}>' if p.get("canal_estoque_id") else "nenhum",
        "tipo_de_estoque": ("conteúdo fixo: a mensagem mais recente do canal vai para todos e não é apagada"
                            if p.get("conteudo_fixo") else "1 mensagem = 1 entrega (apagada depois de entregar)"),
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
                             dias_entrega: int | None = None, categoria_entrega: str | None = None,
                             conteudo_fixo: bool | None = None) -> dict:
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
    categoria_entrega = categoria dos canais de entrega (padrão: a mesma dos chats de compra).
    conteudo_fixo=true: o canal_estoque guarda o MESMO conteúdo para todos os compradores. O bot entrega a mensagem
    mais recente do canal (que não esteja fixada) e não apaga; para trocar o conteúdo, basta mandar uma mensagem nova."""
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
    if conteudo_fixo is not None:
        p["conteudo_fixo"] = bool(conteudo_fixo)
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
    if p.get("conteudo_fixo") and not p.get("canal_estoque_id"):
        avisos.append("conteudo_fixo precisa de um canal_estoque com a mensagem do conteúdo.")
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


# Importados no fim: estes módulos também usam este aqui (evita import circular).
from ..busca import _canais, _cargos, _link_canal, achar_canal, achar_cargo, achar_categoria
from ..comandos import _resumo_vendas
from ..config import PIX_CHAVE, PIX_COPIA_COLA
from ..discord_api import ErroDiscord
from ..interface import _botao
from ..loja import DIAS_ENTREGA_PADRAO, _MODOS_ENTREGA, _contar_estoque, _modo_entrega, _onde_entrega
from ..memoria import _cfg, exigir_config, salvar_config
from ..paineis import _postar
from ..util import _agora, _cor, _fmt, _ler_preco, _norm, _reais, _slug, montar_mensagem, servidor_id
