"""Comandos de barra das vendas (keys, estoque, entrega, painéis) e arquivos de entrega."""

import asyncio
import json
import re
import sqlite3
import unicodedata
from typing import Any

from .. import estado
from ..discord_api import _Resposta
from .base import JOGOS_PADRAO, PLANOS_PADRAO

# ── comandos de barra das vendas ──

_ESCOLHAS_JOGO = [{"name": f"{n} • {pl}", "value": i} for i, n, pl, _, _ in JOGOS_PADRAO]
_ESCOLHAS_PLANO = [{"name": n, "value": i} for i, n, _, _ in PLANOS_PADRAO]
_OP_JOGO = {"type": 3, "name": "jogo", "description": "Jogo e plataforma", "required": True, "choices": _ESCOLHAS_JOGO}
_OP_PLANO = {"type": 3, "name": "plano", "description": "Plano (duração da key)", "required": True, "choices": _ESCOLHAS_PLANO}


def _opcional(op: dict, descricao: str | None = None) -> dict:
    return {**op, "required": False, **({"description": descricao} if descricao else {})}


COMANDOS_VENDAS: list[dict[str, Any]] = [
    {"name": "produto_configurar", "description": "Configurar produto: jogo, plano, preço, duração e se está à venda", "type": 1,
     "default_member_permissions": "8",
     "options": [{**_OP_JOGO, "choices": _ESCOLHAS_JOGO + [{"name": "Todos os jogos", "value": "todos"}]}, _OP_PLANO,
                 {"type": 10, "name": "preco", "description": "Preço em reais (ex.: 17.90)", "required": False, "min_value": 0.5, "max_value": 10000},
                 {"type": 5, "name": "ativo", "description": "À venda?", "required": False},
                 {"type": 4, "name": "dias", "description": "Duração em dias (0 = permanente)", "required": False, "min_value": 0, "max_value": 3650},
                 {"type": 5, "name": "usa_keys", "description": "Entrega uma key do estoque? (não = só login/instruções)", "required": False},
                 {"type": 3, "name": "nome", "description": "Nome exibido (ex.: Key 7 dias)", "required": False, "max_length": 60},
                 {"type": 3, "name": "link_pagamento", "description": "Link de pagamento opcional (https://…) ou 'remover'", "required": False}]},
    {"name": "key_adicionar", "description": "Cadastrar uma ou mais keys no estoque (ninguém vê além de você)", "type": 1,
     "default_member_permissions": "8",
     "options": [_OP_JOGO, _OP_PLANO,
                 {"type": 3, "name": "keys", "description": "Keys separadas por espaço, vírgula ou linha", "required": False, "max_length": 6000},
                 {"type": 11, "name": "arquivo", "description": "Arquivo .txt com uma key por linha", "required": False}]},
    {"name": "key_estoque", "description": "Consultar o estoque de keys por jogo e plano", "type": 1, "default_member_permissions": "8",
     "options": [_opcional(_OP_JOGO), _opcional(_OP_PLANO)]},
    {"name": "key_consultar", "description": "Consultar uma key (ou a key de um pedido)", "type": 1, "default_member_permissions": "8",
     "options": [{"type": 3, "name": "key", "description": "A key", "required": False},
                 {"type": 3, "name": "pedido", "description": "ID do pedido (ECO-…)", "required": False, "autocomplete": True},
                 {"type": 5, "name": "mostrar_completa", "description": "Mostrar a key inteira (só para você)", "required": False}]},
    {"name": "key_revogar", "description": "Revogar uma key, ou zerar o estoque de um plano inteiro", "type": 1,
     "default_member_permissions": "8",
     "options": [{"type": 3, "name": "motivo", "description": "Motivo", "required": True, "max_length": 200},
                 {"type": 3, "name": "key", "description": "A key", "required": False},
                 {"type": 3, "name": "pedido", "description": "ID do pedido (ECO-…)", "required": False, "autocomplete": True},
                 _opcional(_OP_JOGO, "Jogo (para zerar o estoque)"), _opcional(_OP_PLANO, "Plano (para zerar o estoque)"),
                 {"type": 5, "name": "zerar_estoque", "description": "Revogar TODAS as keys disponíveis do jogo e plano escolhidos",
                  "required": False}]},
    {"name": "entrega_configurar", "description": "Cadastrar login, instruções e arquivo enviados junto com a key", "type": 1,
     "default_member_permissions": "8",
     "options": [_OP_JOGO, _opcional(_OP_PLANO, "Plano (vazio = vale para todos os planos do jogo)"),
                 {"type": 11, "name": "arquivo", "description": "Arquivo que vai junto em toda entrega (até 10 MB)", "required": False},
                 {"type": 11, "name": "arquivo2", "description": "Mais um arquivo (opcional)", "required": False},
                 {"type": 11, "name": "arquivo3", "description": "Mais um arquivo (opcional)", "required": False},
                 {"type": 5, "name": "remover_arquivo", "description": "Tirar TODOS os arquivos deste jogo/plano", "required": False}]},
    {"name": "pedido_consultar", "description": "Consultar um pedido", "type": 1, "default_member_permissions": "8",
     "options": [{"type": 3, "name": "pedido", "description": "ID do pedido (ECO-…)", "required": True, "autocomplete": True}]},
    {"name": "painel_vendas_publicar", "description": "Publicar ou atualizar os cinco painéis de venda", "type": 1,
     "default_member_permissions": "8"},
    {"name": "painel_vendas_atualizar", "description": "Atualizar preços, planos e textos dos painéis de venda", "type": 1,
     "default_member_permissions": "8",
     "options": [_opcional(_OP_PLANO, "Plano para mudar (em todos os jogos, ou só no jogo escolhido)"),
                 {"type": 10, "name": "preco", "description": "Novo preço em reais (ex.: 17.90)", "required": False, "min_value": 0.5, "max_value": 10000},
                 {"type": 5, "name": "ativo", "description": "Plano à venda?", "required": False},
                 _opcional({**_OP_JOGO, "choices": _ESCOLHAS_JOGO}, "Só este jogo (vazio = todos)"),
                 {"type": 3, "name": "descricao", "description": "Texto de apresentação do painel ('padrao' volta ao original)", "required": False, "max_length": 1500},
                 {"type": 11, "name": "imagem", "description": "Imagem/banner do painel", "required": False}]},
]
_NOMES_VENDAS = {c["name"] for c in COMANDOS_VENDAS}


def _achar_key(texto: str | None, pedido: str | None) -> sqlite3.Row | None:
    if texto and texto.strip():
        return _q1("SELECT * FROM keys WHERE hash = ?", (_hash_key(texto.strip()),))
    if pedido:
        p = _pedido(pedido.strip().upper())
        if p and p["key_id"]:
            return _q1("SELECT * FROM keys WHERE id = ?", (p["key_id"],))
        return _q1("SELECT * FROM keys WHERE pedido_id = ? ORDER BY id DESC", (pedido.strip().upper(),))
    return None


_DATA_HORA = re.compile(r"^\d+(?:[/.:\-]\d+)+$")  # 29/10/2026, 23:44:07, 1.234
_BORDAS_KEY = "`\"'“”‘’()[]{}<>*•·|"


def _parece_key(texto: str) -> bool:
    """Uma key tem pelo menos 6 caracteres e algum número (ou é bem longa).
    Fica de fora o que vem junto nos arquivos .txt: títulos, palavras, rótulos ("Quantidade:"),
    numeração ("01."), separadores ("-----", "====="), datas, horas e links."""
    t = (texto or "").strip().strip(_BORDAS_KEY)
    if t.endswith(":"):
        return False
    t = t.rstrip(".")
    if not 6 <= len(t) <= 300 or not any(c.isalnum() for c in t):
        return False
    if t.lower().startswith(("http://", "https://", "www.", "discord.gg/")) or _DATA_HORA.match(t):
        return False
    return any(c.isdigit() for c in t) or len(t) >= 16


def _formato_key(k: str) -> str:
    """ECO-5127E36A-45DECC00-7F77504D-4817B526 → 3-8-8-8-8"""
    return re.sub(r"[A-Za-z0-9]+", lambda m: str(len(m.group())), k)


def _ler_keys(texto: str) -> tuple[list[str], int, list[str]]:
    """Separa as keys de um texto ou arquivo. Devolve (keys, quantos trechos foram ignorados, keys fora do padrão).
    Quando quase todas as keys têm o mesmo formato (5 ou mais, 80%+), as que fogem dele também ficam de fora
    e são mostradas para conferência: costuma ser título ou rodapé do arquivo, não key."""
    keys, ignorados = [], 0
    for linha in (texto or "").splitlines():
        achadas = [x.strip().strip(_BORDAS_KEY).rstrip(".") for x in re.split(r"[\s,;]+", linha) if x.strip() and _parece_key(x)]
        keys += achadas
        ignorados += 0 if achadas or not linha.strip() else 1
    fora: list[str] = []
    if len(keys) >= 5:
        contagem: dict[str, int] = {}
        for k in keys:
            contagem[_formato_key(k)] = contagem.get(_formato_key(k), 0) + 1
        padrao, n = max(contagem.items(), key=lambda x: x[1])
        if n < len(keys) and n >= 0.8 * len(keys):
            fora = [k for k in keys if _formato_key(k) != padrao]
            keys = [k for k in keys if _formato_key(k) == padrao]
    return keys, ignorados, fora


def _limpar_keys_invalidas(quem: str) -> int:
    """Revoga o que entrou no estoque sem ser key (títulos, numeração e separadores de arquivos lidos
    antes da versão 3.4). Nunca mexe em keys entregues."""
    if estado._db is None or not _vendas["pronto"]:
        return 0
    ruins = []
    for k in _q("SELECT id, status, pedido_id, valor_cifrado FROM keys WHERE status IN ('disponivel', 'reservada')"):
        valor = decifrar(k["valor_cifrado"])
        if not valor.startswith("⚠️") and not _parece_key(valor):
            ruins.append(k)
    if not ruins:
        return 0
    with _tx() as conn:
        for k in ruins:
            conn.execute("UPDATE keys SET status = 'revogada', revogada_por = ?, revogada_em = ?, "
                         "motivo_revogacao = 'não era key (título/numeração do arquivo)', "
                         "pedido_id = CASE WHEN status = 'reservada' THEN NULL ELSE pedido_id END "
                         "WHERE id = ? AND status IN ('disponivel', 'reservada')", (quem, _agora_iso(), k["id"]))
            if k["status"] == "reservada" and k["pedido_id"]:
                conn.execute("UPDATE pedidos SET key_id = NULL WHERE id = ? AND status != ?", (k["pedido_id"], ENTREGUE))
        _auditar(conn, "keys_invalidas_revogadas", None, quem, f"{len(ruins)} itens que não eram keys")
    log.warning("Vendas: %s itens do estoque não eram keys e foram revogados", len(ruins))
    _paineis_depois(2)
    return len(ruins)


def _embed_estoque(jogo: str | None, plano: str | None) -> dict:
    linhas = []
    for j in _q("SELECT * FROM jogos ORDER BY ordem"):
        if jogo and j["id"] != jogo:
            continue
        linhas.append(f'**{j["emoji"] or "🎮"} {_rotulo_jogo(j)}**')
        for pr in sorted(_q("SELECT * FROM produtos WHERE jogo = ?", (j["id"],)), key=lambda x: _ORDEM_PLANOS.get(x["plano"], 99)):
            if plano and pr["plano"] != plano:
                continue
            cont = {row["status"]: row["n"] for row in _q("SELECT status, COUNT(*) n FROM keys WHERE jogo = ? AND plano = ? GROUP BY status",
                                                          (j["id"], pr["plano"]))}
            est = _estoque(j["id"], pr["plano"])
            situacao = "" if pr["ativo"] else " • ⏸️ fora de venda"
            if not pr["usa_keys"]:
                situacao += " • entrega sem key"
            linhas.append(f'`{pr["nome"]:<15}` 🟢 {cont.get("disponivel", 0)} disp. • ⏳ {est["em_aberto"]} em pedidos • '
                          f'📦 {cont.get("entregue", 0)} entregues • ⛔ {cont.get("revogada", 0)} revogadas{situacao}')
        linhas.append("")
    return {"title": "🔑 Estoque de keys", "description": "\n".join(linhas)[:4096] or "Nada encontrado.", "color": NEON,
            "footer": {"text": "'disp.' = no cofre • 'em pedidos' = já prometidas a pedidos em andamento"}}


def _embed_pedido_admin(p: sqlite3.Row) -> dict:
    j = _jogo(p["jogo"])
    k = _q1("SELECT final, status, expira_em FROM keys WHERE id = ?", (p["key_id"],)) if p["key_id"] else None
    linhas = [f'**Cliente:** <@{p["usuario_id"]}> ({p["usuario_nome"]})',
              f'**Produto:** {_rotulo_jogo(j)} • {p["produto_nome"]} • {_duracao(p["dias"])} • {_reais_c(p["preco_centavos"])}',
              f'**Status:** {ROTULO_STATUS.get(p["status"], p["status"])}',
              f'**Criado:** {_fmt(p["criado_em"])}']
    if p["pagador_cifrado"]:
        linhas.append(f'**Pagador:** {decifrar(p["pagador_cifrado"])} • informado {_fmt(p["informado_em"])}')
    if p["aprovado_por"]:
        linhas.append(f'**Aprovado por:** <@{p["aprovado_por"]}> em {_fmt(p["aprovado_em"])}')
    if p["rejeitado_por"]:
        linhas.append(f'**Rejeitado por:** <@{p["rejeitado_por"]}> em {_fmt(p["rejeitado_em"])} • motivo: {p["motivo_rejeicao"]}')
    if p["entregue_em"]:
        linhas.append(f'**Entregue:** {_fmt(p["entregue_em"])}' + (f' • canal <#{p["canal_entrega_id"]}>' if p["canal_entrega_id"] else ""))
    if k:
        linhas.append(f'**Key:** {k["final"]} ({k["status"]})' + (f' • validade até {_fmt(k["expira_em"])} (informativo)' if k["expira_em"] else ""))
    if p["canal_pagamento_id"] and not p["pagamento_apagado"]:
        linhas.append(f'**Canal de pagamento:** <#{p["canal_pagamento_id"]}>')
    eventos = _q("SELECT * FROM auditoria WHERE pedido_id = ? ORDER BY id DESC LIMIT 8", (p["id"],))
    if eventos:
        linhas.append("\n**Histórico**")
        linhas += [f'• {_fmt(e["quando"])} — {e["acao"]}' + (f' por <@{e["ator_id"]}>' if e["ator_id"] else "") for e in reversed(eventos)]
    return {"title": f'🧾 Pedido {p["id"]}', "description": "\n".join(linhas)[:4096], "color": NEON}


def _embed_pendentes_vendas() -> dict:
    ordem = [AG_CONFERENCIA, AG_ESTOQUE, APROVADO, ENTREGANDO, AG_PAGAMENTO]
    linhas = []
    for st in ordem:
        for p in _q("SELECT * FROM pedidos WHERE status = ? ORDER BY criado_em", (st,))[:15]:
            j = _jogo(p["jogo"])
            canal = f' • <#{p["canal_pagamento_id"]}>' if p["canal_pagamento_id"] and not p["pagamento_apagado"] else ""
            linhas.append(f'**`{p["id"]}`** • {_rotulo_jogo(j)} • {p["produto_nome"]} • {_reais_c(p["preco_centavos"])}\n'
                          f'{ROTULO_STATUS[st]} • <@{p["usuario_id"]}>{canal} • {_fmt(p["informado_em"] or p["criado_em"])}')
    if not linhas:
        return {"title": "🎮 Vendas de keys • pendentes", "description": "Nenhum pedido pendente.", "color": NEON}
    return {"title": "🎮 Vendas de keys • pendentes", "description": "\n\n".join(linhas)[:4096], "color": CORES["amarelo"],
            "footer": {"text": "Aprove ou rejeite pelos botões na mensagem do pedido (só FUNDADOR)"}}


async def _baixar_anexo_comando(dados: dict, nome_opcao: str) -> tuple[bytes, str] | None:
    valor = next((o.get("value") for o in dados.get("options", []) if o["name"] == nome_opcao), None)
    if not valor:
        return None
    anexo = ((dados.get("resolved") or {}).get("attachments") or {}).get(str(valor))
    if not anexo:
        return None
    if anexo.get("size", 0) > 2_000_000:
        raise ErroDiscord("Arquivo grande demais (máximo 2 MB).")
    resp = await cliente_web().get(anexo["url"])
    resp.raise_for_status()
    return resp.content, anexo.get("filename", "arquivo")


async def ao_comando_vendas(r: _Resposta, nome: str, op: dict, dados: dict) -> None:
    inter = r.inter
    if nome == "entrega_configurar":  # abre um formulário (precisa responder na hora)
        if not _vendas["pronto"]:
            await r.efemera("O sistema de vendas está iniciando. Tente de novo em alguns segundos.")
            return
        if not _eh_fundador(inter):
            await r.efemera("⛔ Só o cargo **FUNDADOR** pode usar este comando.")
            return
        jid, plano = op["jogo"], op.get("plano") or "*"
        if op.get("arquivo") or op.get("arquivo2") or op.get("arquivo3") or op.get("remover_arquivo"):
            await r.adiar()
            await _configurar_arquivo_entrega(r, jid, plano, dados, bool(op.get("remover_arquivo")))
            return
        j = _jogo(jid)
        atual = _q1("SELECT * FROM entregas_config WHERE jogo = ? AND plano = ?", (jid, plano))
        campo = lambda cid, rotulo, estilo, maximo, valor, ph: {
            "type": 1, "components": [{"type": 4, "custom_id": cid, "style": estilo, "label": rotulo, "max_length": maximo,
                                       "required": False, "placeholder": ph, **({"value": valor} if valor else {})}]}
        alvo = "todos os planos" if plano == "*" else _produto(jid, plano)["nome"]
        await r.enviar(9, {"custom_id": f"ecvd:m_entrega:{jid}:{plano}", "title": f'Entrega • {j["nome"]} {j["plataforma"]}'[:45],
                           "components": [
                               campo("instrucoes", f"Instruções ({alvo})"[:45], 2, 1500, atual["instrucoes"] if atual else None,
                                     "Passo a passo para usar a key"),
                               campo("login", "Login / acesso (fica cifrado)", 2, 1000,
                                     decifrar(atual["login_cifrado"]) if atual and atual["login_cifrado"] else None, "Opcional"),
                               campo("link", "Links de download (um por linha)", 2, 1000, atual["link_download"] if atual else None,
                                     "Programa: https://…  (outra linha)  Vídeo: https://…")]})
        return
    await r.adiar()
    if not _vendas["pronto"]:
        await r.efemera("O sistema de vendas está iniciando. Tente de novo em alguns segundos.")
        return
    if not _eh_fundador(inter):
        await r.efemera("⛔ Só o cargo **FUNDADOR** pode usar os comandos de vendas.")
        return
    quem = str(inter.user.id)

    if nome == "produto_configurar":
        jogos = [x[0] for x in JOGOS_PADRAO] if op["jogo"] == "todos" else [op["jogo"]]
        mudancas = []
        with _tx() as conn:
            for jid in jogos:
                _produto(jid, op["plano"])
                sets, args = [], []
                if op.get("preco") is not None:
                    sets.append("preco_centavos = ?"); args.append(int(round(float(op["preco"]) * 100)))
                if op.get("ativo") is not None:
                    sets.append("ativo = ?"); args.append(1 if op["ativo"] else 0)
                if op.get("dias") is not None:
                    sets.append("dias = ?"); args.append(int(op["dias"]) or None)
                if op.get("usa_keys") is not None:
                    sets.append("usa_keys = ?"); args.append(1 if op["usa_keys"] else 0)
                if op.get("nome"):
                    sets.append("nome = ?"); args.append(op["nome"].strip()[:60])
                if op.get("link_pagamento"):
                    link = op["link_pagamento"].strip()
                    if _norm(link) == "remover":
                        link = None
                    elif not re.match(r"https://", link):
                        raise ErroDiscord("O link de pagamento precisa começar com https://")
                    sets.append("link_pagamento = ?"); args.append(link)
                if sets:
                    conn.execute(f"UPDATE produtos SET {', '.join(sets)}, atualizado_em = ? WHERE jogo = ? AND plano = ?",
                                 (*args, _agora_iso(), jid, op["plano"]))
                    _auditar(conn, "produto_configurado", None, quem, f'{jid}/{op["plano"]}: {", ".join(sets)}')
                mudancas.append(jid)
        linhas = []
        for jid in jogos:
            pr, j = _produto(jid, op["plano"]), _jogo(jid)
            linhas.append(f'• {_rotulo_jogo(j)} • **{pr["nome"]}** • {_reais_c(pr["preco_centavos"])} • {_duracao(pr["dias"])} • '
                          f'{"à venda" if pr["ativo"] else "fora de venda"} • {"key do estoque" if pr["usa_keys"] else "sem key (só login/instruções)"}')
        _paineis_depois(1)
        await r.efemera("✅ Produto configurado. Os painéis serão atualizados em instantes.\n" + "\n".join(linhas))

    elif nome == "key_adicionar":
        bruto = op.get("keys") or ""
        arq = await _baixar_anexo_comando(dados, "arquivo")
        if arq:
            bruto += "\n" + arq[0].decode("utf-8", "ignore")
        keys, ignorados, fora = _ler_keys(bruto)
        if not keys:
            await r.efemera("Nenhuma key encontrada. Mande em **keys** (separadas por espaço, vírgula ou linha) ou em um arquivo .txt."
                            + (f"\nIgnorei {ignorados} linha(s) sem key (título, grupos, separadores)." if ignorados else ""))
            return
        if len(keys) > 1000:
            await r.efemera("Mande no máximo 1000 keys por vez.")
            return
        jid, plano = op["jogo"], op["plano"]
        j, pr = _jogo(jid), _produto(jid, plano)
        novas = repetidas = reativadas = 0
        with _tx() as conn:
            for k in dict.fromkeys(keys):
                cur = conn.execute("INSERT OR IGNORE INTO keys (jogo, plano, valor_cifrado, hash, final, adicionada_por, adicionada_em) "
                                   "VALUES (?, ?, ?, ?, ?, ?, ?)", (jid, plano, cifrar(k), _hash_key(k), _mascarar(k), quem, _agora_iso()))
                if cur.rowcount:
                    novas += 1
                    continue
                # key revogada que nunca foi entregue pode voltar ao estoque (ex.: tinha entrado no plano errado)
                volta = conn.execute("UPDATE keys SET jogo = ?, plano = ?, status = 'disponivel', pedido_id = NULL, adicionada_por = ?, "
                                     "adicionada_em = ?, revogada_por = NULL, revogada_em = NULL, motivo_revogacao = NULL "
                                     "WHERE hash = ? AND status = 'revogada' AND entregue_em IS NULL",
                                     (jid, plano, quem, _agora_iso(), _hash_key(k))).rowcount
                if volta:
                    reativadas += 1
                else:
                    repetidas += 1
            repetidas += len(keys) - len(dict.fromkeys(keys))
            _auditar(conn, "keys_adicionadas", None, quem, f"{jid}/{plano}: {novas} novas, {reativadas} reativadas")
        est = _estoque(jid, plano)
        lidas = list(dict.fromkeys(keys))
        conferir = (f"\n📄 Li **{len(lidas)}** key(s) (primeira {_mascarar(lidas[0])} • última {_mascarar(lidas[-1])})"
                    + (f"; ignorei {ignorados} linha(s) sem key (título, grupos, separadores)." if ignorados else ".")
                    + (f"\n🔎 {len(fora)} fora do formato das outras, **não** adicionada(s): "
                       + ", ".join(f"`{x[:40]}`" for x in fora[:5]) + (" …" if len(fora) > 5 else "")
                       + ". Se for key mesmo, mande sozinha em **keys**." if fora else ""))
        await r.efemera(f'✅ **{novas + reativadas}** key(s) adicionada(s) em {_rotulo_jogo(j)} • {pr["nome"]}.' + conferir
                        + (f"\n♻️ {reativadas} delas estavam revogadas (sem nunca terem sido entregues) e voltaram ao estoque neste plano."
                           if reativadas else "")
                        + (f"\n⚠️ {repetidas} repetida(s) ignorada(s) (já estão no estoque ou já foram entregues)." if repetidas else "")
                        + f'\nEstoque agora: **{est["disponiveis"]}** no cofre • {est["livre"]} livres para novos pedidos.')
        await registrar_venda_log(f'🔑 <@{quem}> adicionou {novas + reativadas} key(s) em {_rotulo_jogo(j)} • {pr["nome"]}.')
        for p in _q("SELECT id FROM pedidos WHERE status = ? AND jogo = ? AND plano = ? ORDER BY aprovado_em", (AG_ESTOQUE, jid, plano)):
            asyncio.create_task(entregar_pedido(p["id"]))
        _paineis_depois(2, jogo=jid)

    elif nome == "key_estoque":
        await r.editar_original({"embeds": [_embed_estoque(op.get("jogo"), op.get("plano"))], "allowed_mentions": {"parse": []}})
        r.adiada = False

    elif nome == "key_consultar":
        k = _achar_key(op.get("key"), op.get("pedido"))
        if not k:
            await r.efemera("Key não encontrada no cofre.")
            return
        j = _jogo(k["jogo"])
        valor = decifrar(k["valor_cifrado"]) if op.get("mostrar_completa") else k["final"]
        linhas = [f'**Key:** `{valor}`', f'**Jogo/plano:** {_rotulo_jogo(j)} • {_produto(k["jogo"], k["plano"])["nome"]}',
                  f'**Status:** {k["status"]}', f'**Cadastrada:** {_fmt(k["adicionada_em"])} por <@{k["adicionada_por"]}>']
        if k["pedido_id"]:
            p = _pedido(k["pedido_id"])
            linhas.append(f'**Pedido:** `{k["pedido_id"]}`' + (f' • cliente <@{p["usuario_id"]}>' if p else ""))
        if k["entregue_em"]:
            linhas.append(f'**Entregue:** {_fmt(k["entregue_em"])} • validade {_duracao(k["validade_dias"])}'
                          + (f' • até {_fmt(k["expira_em"])} (informativo: o bot não controla o programa)' if k["expira_em"] else ""))
        if k["revogada_em"]:
            linhas.append(f'**Revogada:** {_fmt(k["revogada_em"])} por <@{k["revogada_por"]}> • {k["motivo_revogacao"]}')
        await r.editar_original({"embeds": [{"title": "🔑 Consulta de key", "description": "\n".join(linhas), "color": NEON}],
                                 "allowed_mentions": {"parse": []}})
        r.adiada = False

    elif nome == "key_revogar" and op.get("zerar_estoque"):
        if not (op.get("jogo") and op.get("plano")):
            await r.efemera("Para zerar o estoque, escolha também o **jogo** e o **plano**.")
            return
        jid, plano = op["jogo"], op["plano"]
        j, pr = _jogo(jid), _produto(jid, plano)
        with _tx() as conn:
            n = conn.execute("UPDATE keys SET status = 'revogada', revogada_por = ?, revogada_em = ?, motivo_revogacao = ? "
                             "WHERE jogo = ? AND plano = ? AND status = 'disponivel'",
                             (quem, _agora_iso(), op["motivo"][:200], jid, plano)).rowcount
            _auditar(conn, "estoque_zerado", None, quem, f'{jid}/{plano}: {n} keys • {op["motivo"][:150]}')
        abertos = _estoque(jid, plano)["em_aberto"]
        aviso = (f"\nℹ️ Há {abertos} pedido(s) em andamento desse plano: se forem aprovados sem estoque, ficam aguardando keys "
                 "e o FUNDADOR é avisado." if abertos else "")
        await r.efemera(f'⛔ Estoque zerado: **{n}** key(s) disponível(is) de {_rotulo_jogo(j)} • {pr["nome"]} revogada(s). '
                        f"Keys já entregues não foram mexidas.{aviso}")
        await registrar_venda_log(f'⛔ <@{quem}> zerou o estoque de {_rotulo_jogo(j)} • {pr["nome"]} ({n} keys). Motivo: {op["motivo"][:150]}')
        _paineis_depois(1, jogo=jid)

    elif nome == "key_revogar":
        k = _achar_key(op.get("key"), op.get("pedido"))
        if not k:
            await r.efemera("Key não encontrada no cofre. Informe a key ou o pedido.")
            return
        if k["status"] == "revogada":
            await r.efemera("Esta key já está revogada.")
            return
        with _tx() as conn:
            conn.execute("UPDATE keys SET status = 'revogada', revogada_por = ?, revogada_em = ?, motivo_revogacao = ?, "
                         "pedido_id = CASE WHEN status = 'reservada' THEN NULL ELSE pedido_id END WHERE id = ?",
                         (quem, _agora_iso(), op["motivo"][:200], k["id"]))
            if k["status"] == "reservada" and k["pedido_id"]:
                conn.execute("UPDATE pedidos SET key_id = NULL WHERE id = ? AND status != ?", (k["pedido_id"], ENTREGUE))
            _auditar(conn, "key_revogada", k["pedido_id"], quem, f'{k["final"]} ({k["status"]}): {op["motivo"][:150]}')
        extra = ""
        if k["status"] == "entregue":
            extra = ("\nℹ️ Ela já tinha sido entregue: a revogação fica registrada aqui, mas o bot **não** desativa a key no programa. "
                     "Se o seu sistema de licenças tiver painel próprio, desative lá também.")
        elif k["status"] == "reservada":
            extra = "\nℹ️ Ela estava reservada para um pedido em entrega; o pedido vai receber outra key do estoque."
        await r.efemera(f'⛔ Key {k["final"]} revogada.{extra}')
        await registrar_venda_log(f'⛔ <@{quem}> revogou a key {k["final"]} ({k["jogo"]}/{k["plano"]}). Motivo: {op["motivo"][:150]}')
        _paineis_depois(2)

    elif nome == "pedido_consultar":
        p = _pedido(str(op.get("pedido") or "").strip().upper())
        if not p:
            await r.efemera("Pedido não encontrado.")
            return
        await r.editar_original({"embeds": [_embed_pedido_admin(p)], "allowed_mentions": {"parse": []}})
        r.adiada = False

    elif nome == "painel_vendas_publicar":
        resultado = await sincronizar_paineis(criar=True)
        await r.efemera("📢 **Painéis de venda**\n" + "\n".join(f"• {x}" for x in resultado))

    elif nome == "painel_vendas_atualizar":
        jogos = [op["jogo"]] if op.get("jogo") else [x[0] for x in JOGOS_PADRAO]
        img = await _baixar_anexo_comando(dados, "imagem")
        url_img = None
        if img:
            url_img = await _guardar_imagem_bytes(img[0], img[1])
        with _tx() as conn:
            for jid in jogos:
                if op.get("plano"):
                    sets, args = [], []
                    if op.get("preco") is not None:
                        sets.append("preco_centavos = ?"); args.append(int(round(float(op["preco"]) * 100)))
                    if op.get("ativo") is not None:
                        sets.append("ativo = ?"); args.append(1 if op["ativo"] else 0)
                    if sets:
                        conn.execute(f"UPDATE produtos SET {', '.join(sets)}, atualizado_em = ? WHERE jogo = ? AND plano = ?",
                                     (*args, _agora_iso(), jid, op["plano"]))
                if op.get("descricao"):
                    conn.execute("UPDATE jogos SET descricao = ? WHERE id = ?",
                                 (None if _norm(op["descricao"]) == "padrao" else op["descricao"].strip(), jid))
                if url_img:
                    conn.execute("UPDATE jogos SET imagem_url = ? WHERE id = ?", (url_img, jid))
            _auditar(conn, "paineis_atualizados", None, quem, json.dumps({k: v for k, v in op.items() if k != "imagem"})[:300])
        resultado = await sincronizar_paineis(criar=False)
        await r.efemera("✅ Painéis atualizados:\n" + "\n".join(f"• {x}" for x in resultado))


async def _guardar_imagem_bytes(conteudo: bytes, nome: str) -> str:
    canal = _cfg_estado.get("canal_id") or await _canal_config()
    nome = re.sub(r"[^A-Za-z0-9._-]+", "_", nome)[-60:] or "imagem.png"
    msg = await dc("POST", f"/channels/{canal}/messages",
                   dados={"payload_json": json.dumps({"content": "🖼️ Imagem de painel de vendas. Não apague.",
                                                      "attachments": [{"id": 0, "filename": nome}]})},
                   arquivos={"files[0]": (nome, conteudo, "application/octet-stream")})
    return msg["attachments"][0]["url"].split("?")[0]


LIMITE_ARQUIVO_ENTREGA = 25 * 1024 * 1024  # teto de memória do Render, mesmo em servidor com impulso


async def _limite_upload() -> int:
    """Quanto o bot pode enviar num arquivo neste servidor (cresce com o nível de impulso)."""
    g = await dc("GET", f"/guilds/{await servidor_id()}")
    return min(LIMITE_ARQUIVO_ENTREGA, {2: 50, 3: 100}.get(g.get("premium_tier") or 0, 10) * 1024 * 1024)


async def _canal_arquivos_entrega() -> str:
    """Canal privado onde ficam guardados os arquivos de entrega (o bot copia de lá a cada venda)."""
    canais = await _canais()
    achado = next((c for c in canais if c["type"] == 0 and "arquivosentrega" in _norm(c["name"])), None)
    if achado:
        return achado["id"]
    gid, bot = await servidor_id(), await eu()
    pai = next((c for c in canais if c["type"] == 4 and "sistema" in _norm(c["name"])), None) or \
        next((c for c in canais if c["type"] == 4 and "staff" in _norm(c["name"])), None)
    perms = [{"id": gid, "type": 0, "allow": "0", "deny": str(VER)},
             {"id": bot["id"], "type": 1, "allow": str(VER | ENVIAR | ANEXAR | HISTORICO), "deny": "0"}]
    fund = _cfg_vendas("cargo_fundador_id")
    if fund:
        perms.append({"id": fund, "type": 0, "allow": str(VER | HISTORICO), "deny": "0"})
    corpo: dict[str, Any] = {"name": "📁・arquivos-entrega", "type": 0, "permission_overwrites": perms,
                             "topic": "Arquivos que o bot envia junto com as entregas. Não apague."}
    if pai:
        corpo["parent_id"] = pai["id"]
    return (await dc("POST", f"/guilds/{gid}/channels", corpo=corpo, motivo="Arquivos de entrega"))["id"]


def _mb(n: int) -> str:
    return f"{n / 1024 / 1024:.1f} MB".replace(".", ",")


MAX_ARQUIVOS_ENTREGA = 5
_OPCOES_ARQUIVO = ("arquivo", "arquivo2", "arquivo3")


def _lista_arquivos(jid: str, plano: str) -> list[sqlite3.Row]:
    return _q("SELECT * FROM entregas_arquivos WHERE jogo = ? AND plano = ? ORDER BY adicionado_em, rowid", (jid, plano))


async def _configurar_arquivo_entrega(r: _Resposta, jid: str, plano: str, dados: dict, remover: bool) -> None:
    quem = str(r.inter.user.id)
    j = _jogo(jid)
    alvo = "todos os planos" if plano == "*" else _produto(jid, plano)["nome"]
    resolvidos = (dados.get("resolved") or {}).get("attachments") or {}
    anexos = []
    for o in dados.get("options", []):
        if o["name"] in _OPCOES_ARQUIVO and str(o.get("value")) in resolvidos:
            anexos.append(resolvidos[str(o["value"])])
    if remover and not anexos:
        with _tx() as conn:
            n = conn.execute("DELETE FROM entregas_arquivos WHERE jogo = ? AND plano = ?", (jid, plano)).rowcount
            _auditar(conn, "arquivos_entrega_removidos", None, quem, f"{jid}/{plano}: {n}")
        await r.efemera(f"🗑️ {n} arquivo(s) tirado(s) das próximas entregas de {_rotulo_jogo(j)} ({alvo})." if n
                        else f"Não havia arquivo configurado para {_rotulo_jogo(j)} ({alvo}).")
        return
    if not anexos:
        await r.efemera("Não recebi o arquivo. Tente anexar de novo.")
        return
    limite = await _limite_upload()
    grandes = [a for a in anexos if (a.get("size") or 0) > limite]
    if grandes:
        await r.efemera("Grande demais para o bot enviar neste servidor (máximo " + _mb(limite) + " por arquivo): "
                        + ", ".join(f'**{a.get("filename")}** ({_mb(a["size"])})' for a in grandes)
                        + ". Nada foi salvo. Para esse, use um **link de download** (`/entrega_configurar` sem arquivo).")
        return
    nomes = [re.sub(r"[^A-Za-z0-9.\-]+", "_", unicodedata.normalize("NFKD", a.get("filename") or "arquivo")
                    .encode("ascii", "ignore").decode()).replace("_.", ".").strip("_")[:100] or "arquivo" for a in anexos]
    if len(set(nomes)) < len(nomes):
        await r.efemera("Dois arquivos com o mesmo nome. Renomeie um deles e mande de novo.")
        return
    existentes = {x["nome"] for x in _lista_arquivos(jid, plano)}
    total = len(existentes | set(nomes)) if not remover else len(nomes)
    if total > MAX_ARQUIVOS_ENTREGA:
        await r.efemera(f"Cada jogo/plano aceita até {MAX_ARQUIVOS_ENTREGA} arquivos (ficaria com {total}). "
                        "Use `remover_arquivo: True` junto para trocar todos de uma vez.")
        return
    canal = await _canal_arquivos_entrega()
    guardados = []
    for a, nome in zip(anexos, nomes):
        resp = await cliente_web().get(a["url"], timeout=120)
        resp.raise_for_status()
        msg = await dc("POST", f"/channels/{canal}/messages", dados={"payload_json": json.dumps({
            "content": f"📁 Arquivo de entrega • {_rotulo_jogo(j)} • {alvo} • enviado por <@{quem}>. Não apague.",
            "allowed_mentions": {"parse": []}, "attachments": [{"id": 0, "filename": nome}]})},
            arquivos={"files[0]": (nome, resp.content, a.get("content_type") or "application/octet-stream")})
        guardados.append((nome, msg["id"], len(resp.content)))
    with _tx() as conn:
        if remover:  # remover + arquivos novos = troca a lista inteira
            conn.execute("DELETE FROM entregas_arquivos WHERE jogo = ? AND plano = ?", (jid, plano))
        for nome, mid, tam in guardados:
            conn.execute("INSERT INTO entregas_arquivos (jogo, plano, nome, canal_id, mensagem_id, tamanho, adicionado_por, adicionado_em) "
                         "VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT (jogo, plano, nome) DO UPDATE SET canal_id = excluded.canal_id, "
                         "mensagem_id = excluded.mensagem_id, tamanho = excluded.tamanho, adicionado_por = excluded.adicionado_por",
                         (jid, plano, nome, canal, mid, tam, quem, _agora_iso()))
        _auditar(conn, "arquivos_entrega", None, quem, f"{jid}/{plano}: " + ", ".join(n for n, _, _ in guardados))
    lista = _lista_arquivos(jid, plano)
    trocados = [n for n, _, _ in guardados if n in existentes]
    linhas = "\n".join(f'• 📎 **{x["nome"]}** ({_mb(x["tamanho"] or 0)})' for x in lista)
    extra = ""
    if plano != "*" and _lista_arquivos(jid, "*"):
        extra = "\nℹ️ Os arquivos de **todos os planos** deste jogo também vão junto."
    await r.efemera(f'📁 Salvo! **{len(lista)}** arquivo(s) vão em **toda entrega nova** de {_rotulo_jogo(j)} ({alvo}), '
                    f"logo depois do passo a passo:\n{linhas}"
                    + (f"\n♻️ Substituído(s) pelo novo: {', '.join(trocados)}." if trocados else "") + extra
                    + "\nPara adicionar mais, mande de novo; para tirar todos, use `remover_arquivo: True`.")
    await registrar_venda_log(f'📁 <@{quem}> configurou arquivo(s) de entrega de {_rotulo_jogo(j)} ({alvo}): '
                              + ", ".join(n for n, _, _ in guardados) + ".")


def _arquivos_entrega(jid: str, plano: str) -> list[sqlite3.Row]:
    """Os arquivos de todos os planos do jogo + os do plano (com o mesmo nome, vale o do plano)."""
    por_nome: dict[str, sqlite3.Row] = {}
    for x in _lista_arquivos(jid, "*") + (_lista_arquivos(jid, plano) if plano != "*" else []):
        por_nome[x["nome"]] = x
    return list(por_nome.values())


async def _baixar_arquivo_entrega(cfg: sqlite3.Row) -> tuple[str, bytes] | None:
    try:
        msg = await dc("GET", f'/channels/{cfg["canal_id"]}/messages/{cfg["mensagem_id"]}')
        anexo = next((a for a in msg.get("attachments", []) if a["filename"] == cfg["nome"]), None) or \
            (msg.get("attachments") or [None])[0]
        if not anexo:
            return None
        resp = await cliente_web().get(anexo["url"], timeout=120)
        resp.raise_for_status()
        return anexo["filename"], resp.content
    except Exception as erro:
        log.warning("Não consegui baixar o arquivo de entrega: %s", erro)
        return None


async def _vendas_modal_entrega(r: _Resposta, jid: str, plano: str) -> None:
    inter = r.inter
    if not _eh_fundador(inter):
        await r.efemera("⛔ Só o cargo **FUNDADOR** pode configurar a entrega.")
        return
    instr = (_valor_modal(inter.data, "instrucoes") or "").strip()
    login = (_valor_modal(inter.data, "login") or "").strip()
    link = (_valor_modal(inter.data, "link") or "").strip()
    linhas_link = [x.strip() for x in link.splitlines() if x.strip()]
    sem_link = [x for x in linhas_link if not re.search(r"https?://\S+", x)]
    if sem_link:
        await r.efemera("Cada linha dos links precisa ter um endereço começando com https:// (ex.: `Vídeo: https://…`). "
                        f"Linha sem link: `{sem_link[0][:80]}`")
        return
    link = "\n".join(linhas_link)
    with _tx() as conn:
        conn.execute("INSERT INTO entregas_config (jogo, plano, instrucoes, login_cifrado, link_download, atualizado_por, atualizado_em) "
                     "VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT (jogo, plano) DO UPDATE SET instrucoes = excluded.instrucoes, "
                     "login_cifrado = excluded.login_cifrado, link_download = excluded.link_download, "
                     "atualizado_por = excluded.atualizado_por, atualizado_em = excluded.atualizado_em",
                     (jid, plano, instr or None, cifrar(login) if login else None, link or None, str(inter.user.id), _agora_iso()))
        _auditar(conn, "entrega_configurada", None, str(inter.user.id), f"{jid}/{plano}")
    j = _jogo(jid)
    alvo = "todos os planos" if plano == "*" else _produto(jid, plano)["nome"]
    await r.efemera(f'✅ Entrega de {_rotulo_jogo(j)} ({alvo}) salva: '
                    + ", ".join(x for x, v in (("instruções", instr), ("login (cifrado)", login), ("link de download", link)) if v)
                    or "nada preenchido (a entrega vai só com a key)")


async def _autocompletar_vendas(r: _Resposta, nome: str, dados: dict) -> None:
    foco = next((o for o in dados.get("options", []) if o.get("focused")), {})
    texto = _norm(foco.get("value") or "")
    escolhas = []
    if _vendas["pronto"] and _eh_fundador(r.inter):
        for p in _q("SELECT * FROM pedidos ORDER BY criado_em DESC LIMIT 200"):
            rotulo = f'{p["id"]} • {p["produto_nome"]} • {p["jogo"]} • {p["usuario_nome"] or ""} • {p["status"]}'
            if not texto or texto in _norm(rotulo):
                escolhas.append({"name": rotulo[:100], "value": p["id"]})
            if len(escolhas) >= 25:
                break
    await r.enviar(8, {"choices": escolhas})


async def ao_clique_vendas(r: _Resposta, tipo: int, partes: list[str], dados: dict) -> None:
    acao = partes[1] if len(partes) > 1 else ""
    alvo = partes[2] if len(partes) > 2 else ""
    if not _vendas["pronto"]:
        if acao == "menu":
            await r.enviar(6)
        await r.efemera("O sistema de vendas está iniciando. Tente de novo em alguns segundos.")
        return
    if tipo == 5:
        if acao == "m_pagador":
            await _vendas_modal_pagador(r, alvo)
        elif acao == "m_aprovar":
            await _vendas_modal_aprovar(r, alvo)
        elif acao == "m_rejeitar":
            await _vendas_modal_rejeitar(r, alvo)
        elif acao == "m_entrega":
            await _vendas_modal_entrega(r, alvo, partes[3] if len(partes) > 3 else "*")
        return
    if acao == "menu":
        valores = dados.get("values") or []
        await _vendas_menu(r, alvo, valores[0] if valores else "")
    elif acao == "pagar":
        await _vendas_pagar(r, alvo)
    elif acao in ("cancelar", "cancelar_ok"):
        await _vendas_cancelar(r, alvo, acao == "cancelar_ok")
    elif acao in ("aprovar", "rejeitar"):
        await _vendas_pedir_aprovacao(r, alvo, acao == "aprovar")
    elif acao == "reentregar":
        await _vendas_reentregar(r, alvo)
    elif acao in ("fechar_entrega", "fechar_entrega_ok"):
        await _vendas_fechar_entrega(r, alvo, acao == "fechar_entrega_ok")


# Importados no fim: estes módulos também usam este aqui (evita import circular).
from ..busca import _canais
from ..config import log
from ..discord_api import ErroDiscord, cliente_web, dc
from ..interface import _valor_modal
from ..memoria import _canal_config, _cfg_estado
from ..util import ANEXAR, CORES, ENVIAR, HISTORICO, VER, _fmt, _norm, eu, servidor_id
from .backup import registrar_venda_log
from .banco import (
    _agora_iso,
    _auditar,
    _cfg_vendas,
    _duracao,
    _eh_fundador,
    _estoque,
    _jogo,
    _produto,
    _q,
    _q1,
    _reais_c,
    _rotulo_jogo,
    _tx,
)
from .base import (
    AG_CONFERENCIA,
    AG_ESTOQUE,
    AG_PAGAMENTO,
    APROVADO,
    ENTREGANDO,
    ENTREGUE,
    NEON,
    ROTULO_STATUS,
    _ORDEM_PLANOS,
    _vendas,
)
from .cofre import _hash_key, _mascarar, cifrar, decifrar
from .compra import (
    _vendas_cancelar,
    _vendas_menu,
    _vendas_modal_aprovar,
    _vendas_modal_pagador,
    _vendas_modal_rejeitar,
    _vendas_pagar,
    _vendas_pedir_aprovacao,
)
from .entrega import _vendas_fechar_entrega, _vendas_reentregar, entregar_pedido
from .paineis import _paineis_depois, sincronizar_paineis
from .pedido import _pedido
