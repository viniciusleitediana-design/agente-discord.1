"""Entrega: reserva da key, canal privado, passo a passo, arquivos, login e key."""

import json
import sqlite3
import time
from datetime import timedelta

from ..discord_api import _Resposta

# ── entrega ──

def _config_entrega(jid: str, plano: str) -> sqlite3.Row | None:
    """Instruções/login/link do plano; se o plano não tiver texto próprio, os do jogo todo.
    (O arquivo é procurado à parte em _arquivo_entrega: um plano pode ter só o arquivo e herdar o texto.)"""
    tem_texto = "AND (instrucoes IS NOT NULL OR login_cifrado IS NOT NULL OR link_download IS NOT NULL)"
    return _q1(f"SELECT * FROM entregas_config WHERE jogo = ? AND plano = ? {tem_texto}", (jid, plano)) or \
        _q1(f"SELECT * FROM entregas_config WHERE jogo = ? AND plano = '*' {tem_texto}", (jid,))


async def entregar_pedido(pid: str) -> str:
    """Entrega um pedido APROVADO: reserva a key (transação), cria o canal privado de entrega e manda tudo.
    Nunca entrega duas vezes: cada passo confere o status no banco."""
    async with _lock_pedido(pid):
        p = _pedido(pid)
        if not p or p["status"] not in (APROVADO, AG_ESTOQUE, ENTREGANDO):
            return "nada a fazer"
        if not p["aprovado_por"]:
            return "pedido sem aprovação registrada"  # trava extra: nada é entregue sem aprovação do FUNDADOR
        prod = _produto(p["jogo"], p["plano"])
        key_row = None
        ja_avisado = p["status"] == AG_ESTOQUE
        with _tx() as conn:
            if prod["usa_keys"]:
                key_row = conn.execute("SELECT * FROM keys WHERE pedido_id = ? AND status = 'reservada'", (pid,)).fetchone()
                if not key_row:
                    key_row = conn.execute("SELECT * FROM keys WHERE jogo = ? AND plano = ? AND status = 'disponivel' "
                                           "ORDER BY id LIMIT 1", (p["jogo"], p["plano"])).fetchone()
                    if key_row:
                        conn.execute("UPDATE keys SET status = 'reservada', pedido_id = ? WHERE id = ? AND status = 'disponivel'",
                                     (pid, key_row["id"]))
            if prod["usa_keys"] and not key_row:
                conn.execute("UPDATE pedidos SET status = ? WHERE id = ?", (AG_ESTOQUE, pid))
                if not ja_avisado:
                    _auditar(conn, "sem_estoque", pid)
            else:
                conn.execute("UPDATE pedidos SET status = ?, key_id = ?, entregando_desde = ? WHERE id = ?",
                             (ENTREGANDO, key_row["id"] if key_row else None, _agora_iso(), pid))
        p = _pedido(pid)
        if p["status"] == AG_ESTOQUE:
            if not ja_avisado:
                await _avisar_sem_estoque(p)
            return "sem estoque"
        try:
            await _executar_entrega(p, key_row)
        except Exception as erro:
            log.exception("Falha na entrega do pedido %s", pid)
            with _tx() as conn:  # volta para APROVADO; a key continua reservada para este pedido
                conn.execute("UPDATE pedidos SET status = ? WHERE id = ? AND status = ?", (APROVADO, pid, ENTREGANDO))
                _auditar(conn, "erro_entrega", pid, None, str(erro)[:300])
            onde = f' → <#{p["canal_pagamento_id"]}>' if p["canal_pagamento_id"] and not p["pagamento_apagado"] else ""
            alertou = await alertar_equipe(f'⚠️ **Entrega travada** • `{pid}` • <@{p["usuario_id"]}> • {str(erro)[:200]}{onde}')
            fund = None if alertou else _cfg_vendas("cargo_fundador_id")
            if p["canal_pagamento_id"] and not p["pagamento_apagado"]:
                try:
                    await dc("POST", f'/channels/{p["canal_pagamento_id"]}/messages', corpo={
                        "content": (f"<@&{fund}> " if fund else "") + f"⚠️ Não consegui concluir a entrega do pedido `{pid}` ({erro}). "
                                   "O pagamento continua aprovado e a key reservada. Clique para tentar de novo:",
                        "components": [_linha(_botao("Tentar entregar de novo", f"ecvd:reentregar:{pid}", 1, "🔁"))],
                        "allowed_mentions": {"parse": [], "roles": [fund] if fund else []}})
                except ErroDiscord:
                    pass
            return f"erro: {erro}"
    return "entregue"


async def _avisar_sem_estoque(p: sqlite3.Row) -> None:
    j = _jogo(p["jogo"])
    fund = _cfg_vendas("cargo_fundador_id")
    texto = (f"<@&{fund}> " if fund else "") + (
        f'⚠️ **Sem keys** de {_rotulo_jogo(j)} • {p["produto_nome"]} para o pedido `{p["id"]}` (pagamento já aprovado). '
        f'Cadastre com `/key_adicionar` e a entrega sai **automaticamente**.')
    sem_mencao = texto.replace(f"<@&{fund}> ", "") if fund else texto
    if await alertar_equipe(f'📦 {sem_mencao} Cliente: <@{p["usuario_id"]}>.'):
        texto, fund = sem_mencao, None
    if p["canal_pagamento_id"] and not p["pagamento_apagado"]:
        try:
            await dc("POST", f'/channels/{p["canal_pagamento_id"]}/messages', corpo={
                "content": texto + f'\n<@{p["usuario_id"]}>, seu pagamento foi aprovado! Sua key será entregue assim que o estoque for reposto.',
                "allowed_mentions": {"parse": [], "roles": [fund] if fund else [], "users": [p["usuario_id"]]}})
        except ErroDiscord:
            pass
    await registrar_venda_log(texto.replace(f"<@&{fund}> ", "") if fund else texto)


async def _executar_entrega(p: sqlite3.Row, key_row: sqlite3.Row | None) -> None:
    pid = p["id"]
    j = _jogo(p["jogo"])
    cfg = _config_entrega(p["jogo"], p["plano"])
    uid = p["usuario_id"]
    canal_id = p["canal_entrega_id"]
    if canal_id and not await _canal_existe(canal_id):
        canal_id = None
    novo_canal = not canal_id
    if novo_canal:
        canal = await _canal_privado_venda(f"entrega-{p['jogo']}", uid, p["usuario_nome"] or uid[-6:], pid, "📦 ENTREGAS",
                                           f'Entrega do pedido {pid} • {_rotulo_jogo(j)} • {p["produto_nome"]} • só o comprador e a equipe veem')
        canal_id = canal["id"]
        with _tx() as conn:
            conn.execute("UPDATE pedidos SET canal_entrega_id = ? WHERE id = ?", (canal_id, pid))
    agora = _agora()
    expira = (agora + timedelta(days=p["dias"])) if p["dias"] else None
    # Ordem: resumo → passo a passo → login → key sozinha (com o botão de fechar), igual ao "como comprar" do painel.
    # A key fica numa mensagem só com ela, sem formatação, para "Copiar texto" pegar exatamente a key.
    instrucoes = []
    if cfg and cfg["instrucoes"]:
        instrucoes.append(cfg["instrucoes"])
    if cfg and cfg["link_download"]:
        links = [x for x in cfg["link_download"].splitlines() if x.strip()]
        instrucoes.append(f"⬇️ **Download:** {links[0]}" if len(links) == 1
                          else "⬇️ **Downloads**\n" + "\n".join(f"• {x}" for x in links))
    login = decifrar(cfg["login_cifrado"]) if cfg and cfg["login_cifrado"] else None
    arquivos, faltando = [], []
    for cfg_arquivo in _arquivos_entrega(p["jogo"], p["plano"]):
        baixado = await _baixar_arquivo_entrega(cfg_arquivo)
        if baixado:
            arquivos.append(baixado)
        else:
            faltando.append(cfg_arquivo["nome"])
    if faltando:
        aviso_arquivo = (f'⚠️ **Arquivo de entrega não foi** no pedido `{pid}` (<@{uid}>): não achei '
                         + ", ".join(f"`{n}`" for n in faltando) + f' no canal de arquivos. Mande pelo canal <#{canal_id}> e '
                         "configure de novo com `/entrega_configurar` + arquivo.")
        if not await alertar_equipe(aviso_arquivo):
            await registrar_venda_log(aviso_arquivo)
    rotulo_arq = "o arquivo" if len(arquivos) == 1 else "os arquivos"
    abaixo = [x for x, tem in (("o passo a passo", instrucoes), (rotulo_arq, arquivos), ("o login", login), ("a key", key_row)) if tem]
    resumo = (f'🎮 **{_rotulo_jogo(j)}**  •  📦 **{p["produto_nome"]}**  •  ⏳ {_duracao(p["dias"])}\n'
              f'🆔 `{pid}`  •  💰 {_reais_c(p["preco_centavos"])}')
    aviso = ("\n\n" + (", ".join(abaixo[:-1]) + " e " + abaixo[-1] if len(abaixo) > 1 else abaixo[0]).capitalize()
             + (" estão" if len(abaixo) > 1 else " está") + " logo abaixo. Guarde em um lugar seguro e **não compartilhe** com ninguém."
             if abaixo else "")
    mensagens: list[dict] = [{
        "content": f"<@{uid}>", "allowed_mentions": {"parse": [], "users": [uid]},
        "embeds": [{"title": "✅ Pagamento aprovado", "color": NEON,
                    "description": f"{resumo}\n\n🔒 Canal **privado**: só você e a equipe veem.{aviso}",
                    "footer": {"text": "ECO CHEATS • Obrigado pela compra!"}}]}]
    if instrucoes:
        mensagens.append({"embeds": [{"title": "📖 Passo a passo", "color": NEON, "description": "\n\n".join(instrucoes)[:4096]}]})
    for arquivo in arquivos:
        mensagens.append({"content": f"📎 **{arquivo[0]}**", "_arquivo": arquivo})
    if login:
        mensagens.append({"embeds": [{"title": "🔐 Seu login", "color": NEON, "description": login[:4096]}]})
    if key_row:
        mensagens.append({"content": f"Key: {decifrar(key_row['valor_cifrado'])}"})
    mensagens[-1]["components"] = [_linha(_botao("Já guardei, fechar canal", f"ecvd:fechar_entrega:{pid}", 2, "🔒"))]
    for m in mensagens:
        m.setdefault("allowed_mentions", {"parse": []})
        anexo = m.pop("_arquivo", None)
        if anexo:
            m["attachments"] = [{"id": 0, "filename": anexo[0]}]
            await dc("POST", f"/channels/{canal_id}/messages", dados={"payload_json": json.dumps(m)},
                     arquivos={"files[0]": (anexo[0], anexo[1], "application/octet-stream")})
        else:
            await dc("POST", f"/channels/{canal_id}/messages", corpo=m)
    with _tx() as conn:
        if key_row:
            conn.execute("UPDATE keys SET status = 'entregue', entregue_em = ?, validade_dias = ?, expira_em = ? WHERE id = ?",
                         (agora.isoformat(), p["dias"], expira.isoformat() if expira else None, key_row["id"]))
        conn.execute("UPDATE pedidos SET status = ?, entregue_em = ?, fechar_pagamento_em = ? WHERE id = ?",
                     (ENTREGUE, agora.isoformat(), (agora + APAGAR_PAGAMENTO_APOS_ENTREGA).isoformat(), pid))
        _auditar(conn, "entregue", pid, None, f'canal {canal_id}' + (f' key {key_row["final"]}' if key_row else ""))
    p = _pedido(pid)
    await _editar_msg_pedido(p, _embed_pedido(p, extra=(f'✅ Pagamento aprovado por <@{p["aprovado_por"]}> em {_fmt(p["aprovado_em"])}.\n'
                                                       f"📦 Entregue no canal privado <#{canal_id}>.")), [])
    if p["canal_pagamento_id"] and not p["pagamento_apagado"]:
        try:
            await dc("POST", f'/channels/{p["canal_pagamento_id"]}/messages', corpo={
                "content": (f"<@{uid}> ✅ Pagamento aprovado! Sua key foi entregue no canal privado <#{canal_id}>. "
                            "Este canal de pagamento será apagado em 30 minutos."),
                "allowed_mentions": {"parse": [], "users": [uid]}})
        except ErroDiscord:
            pass
    await _dm(uid, {"title": "✅ Compra aprovada!", "color": NEON,
                    "description": f'Seu pedido `{pid}` ({p["produto_nome"]} • {_rotulo_jogo(j)}) foi entregue no canal privado <#{canal_id}>.'})
    await registrar_venda_log(
        f'📦 Pedido `{pid}` **entregue** — {_rotulo_jogo(j)} • {p["produto_nome"]} • {_reais_c(p["preco_centavos"])} • '
        f'<@{uid}> • aprovado por <@{p["aprovado_por"]}> • ' + (f'key {key_row["final"]} • ' if key_row else "")
        + f'entrega <#{canal_id}> • {_fmt(agora)}')
    _paineis_depois(2, jogo=p["jogo"])


async def _vendas_reentregar(r: _Resposta, pid: str) -> None:
    if not _eh_fundador(r.inter):
        await r.efemera("⛔ Só o cargo **FUNDADOR** pode fazer isso.")
        return
    await r.adiar()
    resultado = await entregar_pedido(pid)
    textos = {"entregue": "✅ Entregue!", "sem estoque": "⚠️ Ainda sem keys para este plano. Use /key_adicionar.",
              "nada a fazer": "Este pedido não está esperando entrega."}
    await r.efemera(textos.get(resultado, f"⚠️ {resultado}"))


async def _vendas_fechar_entrega(r: _Resposta, pid: str, confirmado: bool) -> None:
    inter = r.inter
    p = _pedido(pid)
    if not p or str(inter.channel_id) != (p["canal_entrega_id"] or ""):
        await r.efemera("Este canal já está sendo fechado.")
        return
    if str(inter.user.id) != p["usuario_id"] and not _eh_fundador(inter):
        await r.efemera("Só quem comprou pode fechar este canal.")
        return
    if not confirmado:
        await r.enviar(4, {"content": "Tem certeza? Ao fechar, a key e as instruções somem deste canal. Confira se você guardou tudo.",
                           "flags": 64, "components": [_linha(_botao("Sim, fechar canal", f"ecvd:fechar_entrega_ok:{pid}", 4, "🔒"))]})
        return
    with _tx() as conn:
        conn.execute("UPDATE pedidos SET fechar_entrega_em = ? WHERE id = ?", ((_agora() + timedelta(seconds=3)).isoformat(), pid))
        _auditar(conn, "entrega_fechada", pid, str(inter.user.id))
    await r.enviar(7, {"content": "🔒 Fechando o canal…", "components": []})


async def rodar_vendas() -> None:
    """Rotina (a cada 20 s): expira pedidos sem pagamento, apaga canais de pagamento encerrados, retoma entregas."""
    if not _vendas["pronto"]:
        if time.time() - _vendas.get("ultima_tentativa", 0) > 30 and _cfg_estado.get("carregada"):
            _vendas["ultima_tentativa"] = time.time()
            await iniciar_vendas()
        return
    agora = _agora()
    limite = (agora - ESPERA_PAGAMENTO_VENDA).isoformat()
    for p in _q("SELECT * FROM pedidos WHERE status = ? AND criado_em < ?", (AG_PAGAMENTO, limite)):
        with _tx() as conn:
            mudou = conn.execute("UPDATE pedidos SET status = ?, fechar_pagamento_em = ? WHERE id = ? AND status = ?",
                                 (EXPIRADO, (agora + APAGAR_PAGAMENTO_APOS_EXPIRAR).isoformat(), p["id"], AG_PAGAMENTO)).rowcount
            if mudou:
                _auditar(conn, "expirado", p["id"])
        if mudou and p["canal_pagamento_id"]:
            try:
                await dc("POST", f'/channels/{p["canal_pagamento_id"]}/messages', corpo={
                    "content": f'<@{p["usuario_id"]}> ⌛ O pedido `{p["id"]}` expirou sem pagamento informado. Este canal será apagado.',
                    "allowed_mentions": {"parse": [], "users": [p["usuario_id"]]}})
            except ErroDiscord:
                pass
            _paineis_depois(2, jogo=p["jogo"])
    for p in _q("SELECT * FROM pedidos WHERE pagamento_apagado = 0 AND fechar_pagamento_em IS NOT NULL AND fechar_pagamento_em <= ?",
                (agora.isoformat(),)):
        if p["canal_pagamento_id"]:
            try:
                await dc("DELETE", f'/channels/{p["canal_pagamento_id"]}', motivo=f'Pedido {p["id"]} encerrado')
            except ErroDiscord as erro:
                if erro.status != 404 and erro.codigo != 10003:
                    log.warning("Não consegui apagar o canal de pagamento de %s: %s", p["id"], erro)
                    continue
        with _tx() as conn:
            conn.execute("UPDATE pedidos SET pagamento_apagado = 1 WHERE id = ?", (p["id"],))
    for p in _q("SELECT * FROM pedidos WHERE entrega_apagada = 0 AND fechar_entrega_em IS NOT NULL AND fechar_entrega_em <= ?",
                (agora.isoformat(),)):
        if p["canal_entrega_id"]:
            try:
                await dc("DELETE", f'/channels/{p["canal_entrega_id"]}', motivo=f'Entrega {p["id"]} fechada pelo comprador')
            except ErroDiscord as erro:
                if erro.status != 404 and erro.codigo != 10003:
                    continue
        with _tx() as conn:
            conn.execute("UPDATE pedidos SET entrega_apagada = 1 WHERE id = ?", (p["id"],))
    # retoma entregas: aprovados sem entrega (ex.: o bot reiniciou no meio) e pedidos esperando estoque
    travados = (agora - timedelta(minutes=2)).isoformat()
    for p in _q("SELECT id FROM pedidos WHERE status = ? OR (status = ? AND entregando_desde < ?) ORDER BY aprovado_em",
                (APROVADO, ENTREGANDO, travados)):
        if not _lock_pedido(p["id"]).locked():
            await entregar_pedido(p["id"])
    for p in _q("SELECT id, jogo, plano FROM pedidos WHERE status = ? ORDER BY aprovado_em", (AG_ESTOQUE,)):
        if _estoque(p["jogo"], p["plano"])["disponiveis"] > 0 and not _lock_pedido(p["id"]).locked():
            await entregar_pedido(p["id"])
    await _rechecar_backup()


# Importados no fim: estes módulos também usam este aqui (evita import circular).
from ..busca import _canal_existe
from ..central import alertar_equipe
from ..config import log
from ..discord_api import ErroDiscord, dc
from ..interface import _botao, _linha
from ..memoria import _cfg_estado
from ..util import _agora, _fmt
from .backup import _rechecar_backup, iniciar_vendas, registrar_venda_log
from .banco import (
    _agora_iso,
    _auditar,
    _cfg_vendas,
    _duracao,
    _eh_fundador,
    _estoque,
    _jogo,
    _lock_pedido,
    _produto,
    _q,
    _q1,
    _reais_c,
    _rotulo_jogo,
    _tx,
)
from .base import (
    AG_ESTOQUE,
    AG_PAGAMENTO,
    APAGAR_PAGAMENTO_APOS_ENTREGA,
    APAGAR_PAGAMENTO_APOS_EXPIRAR,
    APROVADO,
    ENTREGANDO,
    ENTREGUE,
    ESPERA_PAGAMENTO_VENDA,
    EXPIRADO,
    NEON,
    _vendas,
)
from .canais import _canal_privado_venda
from .cofre import decifrar
from .comandos import _arquivos_entrega, _baixar_arquivo_entrega
from .compra import _dm
from .paineis import _paineis_depois
from .pedido import _editar_msg_pedido, _embed_pedido, _pedido
