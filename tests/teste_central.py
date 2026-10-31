"""Central da equipe: fila de atendimento ao vivo + alertas num canal só, com vários clientes ao mesmo tempo."""
import asyncio
import json
import os
import shutil
import sys
import types

RASC = os.path.dirname(os.path.abspath(__file__))
PASTA_DB = os.path.join(RASC, "db_central")
shutil.rmtree(PASTA_DB, ignore_errors=True)
os.environ.update(DISCORD_TOKEN="token-falso", GUILD_ID="111111111111111111", CHAVE_SECRETA="x",
                  PIX_CHAVE="3f8a2c1e-7b4d-4e9a-9c2f-5d6e7f8a9b0c", PIX_NOME="LOJA TESTE", PIX_CIDADE="SAO PAULO",
                  CHAVE_COFRE="8bY8rQyq3b0bq3Wk5Cq5xJx7mJ3wqv6dK0pQyZx0n1M=", VENDAS_DB=os.path.join(PASTA_DB, "vendas.db"))
sys.path.insert(0, RASC)

import httpx2 as httpx

import fake_discord
import fake_discord2
from suporte import bot as server

GID, BOT = fake_discord.GID, fake_discord.BOT
fake = fake_discord2.Fake2()
server._api = httpx.AsyncClient(base_url=server.API + "/", transport=httpx.MockTransport(fake.handler))
server._web = httpx.AsyncClient(transport=httpx.MockTransport(fake.handler))
ok_n = 0
CS2 = "1563252420497379437"


def ok(cond, msg):
    global ok_n
    if not cond:
        raise AssertionError(msg)
    ok_n += 1
    print("  ✔", msg)


def membro(usuario, nome=None):
    for k, v in fake.members.items():
        if v["user"]["username"] == usuario:
            return k
    uid = fake_discord.novo_id()
    fake.members[uid] = {"user": {"id": uid, "username": usuario, "global_name": nome or usuario}, "nick": None, "roles": [],
                         "joined_at": "2026-10-01T12:00:00+00:00"}
    return uid


def inter(uid, canal_id, data, tipo=3, cargos=(), admin=False):
    u = fake.members[uid]["user"]
    return types.SimpleNamespace(
        id=fake_discord.novo_id(), token="tok", application_id=BOT, type=tipo, data=data,
        user=types.SimpleNamespace(id=int(uid), name=u["username"], display_name=u.get("global_name") or u["username"],
                                   roles=[types.SimpleNamespace(id=int(c)) for c in cargos]),
        channel_id=int(canal_id), guild_id=int(GID), guild=types.SimpleNamespace(owner_id=999),
        permissions=types.SimpleNamespace(administrator=admin), message=types.SimpleNamespace(embeds=[]))


def cmd(uid, canal_id, nome, cargos=(), **op):
    data = {"name": nome, "type": 1, "options": [{"name": k, "type": 3, "value": v} for k, v in op.items()]}
    return inter(uid, canal_id, data, tipo=2, cargos=cargos, admin=True)


def modal(custom_id, **campos):
    return {"custom_id": custom_id, "components": [{"type": 1, "components": [{"type": 4, "custom_id": k, "value": v}]}
                                                  for k, v in campos.items()]}


def msgs(cid):
    return fake.messages.get(cid, [])


def novo_canal(nome, tipo=0, pai=None):
    cid = fake_discord.novo_id()
    fake.channels[cid] = {"id": cid, "name": nome, "type": tipo, "position": 0, "parent_id": pai, "permission_overwrites": []}
    return cid


def fila_texto(fila):
    bot_msgs = [m for m in msgs(fila) if m["author"]["id"] == BOT]
    assert len(bot_msgs) == 1, f"a fila deve ser 1 mensagem só (achei {len(bot_msgs)})"
    return json.dumps(bot_msgs[0]["embeds"], ensure_ascii=False), bot_msgs[0]


async def main():
    fake.channels[CS2] = {"id": CS2, "name": "🥇・cheat・cs2", "type": 0, "position": 3, "parent_id": None, "permission_overwrites": []}
    logs = novo_canal("📊・registro-de-vendas")
    fund = next(r for r in fake.roles.values() if r["name"] == "Fundador")["id"]
    vini = membro("vinicius")
    await server.carregar_config(forcar=True)
    await server.iniciar_vendas()
    tk_cat = novo_canal("🎟️ TICKETS", 4)
    abrir = novo_canal("🎫・abrir-ticket")
    res = await server.publicar_painel_ticket(abrir, categoria=tk_cat, cargos_equipe=["Fundador"])
    pid_painel = res["painel_id"]

    # ── sem central: comportamento antigo (equipe mencionada no próprio canal) ──
    ana = membro("ana", "Ana")
    await server.ao_interagir(inter(ana, abrir, {"custom_id": f"ecot:abrir:{pid_painel}"}))
    t_ana = next(cid for cid, t in server._cfg["tickets"].items() if t["dono"] == ana)
    ok(f"<@&{fund}>" in msgs(t_ana)[0]["content"], "sem canal de alertas: a equipe é mencionada dentro do ticket, como antes")
    await server.atualizar_fila()
    ok(server._central["fila"] is None, "sem canal de fila: nada é publicado")

    # ── cria a central ──
    cat = novo_canal("📋 CENTRAL DA EQUIPE", 4)
    fila = novo_canal("📋・fila-de-atendimento", 0, cat)
    alertas = novo_canal("🔔・alertas", 0, cat)
    await server._canais_central(forcar=True)
    await server.atualizar_fila()
    txt, m_fila = fila_texto(fila)
    ok("TICKETS SEM RESPONSÁVEL (1)" in txt and f"<#{t_ana}>" in txt and "**1** precisa de resposta" in txt,
       "fila mostra o ticket já aberto, com link para o canal")

    # ── 3 tickets e 3 compras ao mesmo tempo ──
    clientes = [membro(f"cliente{i}", f"Cliente {i}") for i in range(3)]
    for c in clientes:
        await server.ao_interagir(inter(c, abrir, {"custom_id": f"ecot:abrir:{pid_painel}"}))
    tks = [next(cid for cid, t in server._cfg["tickets"].items() if t["dono"] == c) for c in clientes]
    ok(all(f"<@&{fund}>" not in msgs(t)[0]["content"] and f"<@{c}>" in msgs(t)[0]["content"] for t, c in zip(tks, clientes)),
       "com canal de alertas: dentro do ticket só o cliente é mencionado")
    alerta_tk = [m for m in msgs(alertas) if "Novo ticket" in m["content"]]
    ok(len(alerta_tk) == 3 and all(f"<@&{fund}>" in m["content"] and fund in m["_am"].get("roles", []) for m in alerta_tk)
       and all(f"<#{t}>" in json.dumps(alerta_tk) for t in tks), "cada ticket novo gera 1 alerta com menção ao FUNDADOR e link")
    ok(all(not m["_am"].get("users") for m in msgs(alertas)), "alerta não menciona (pinga) o cliente")

    await server.ao_interagir(cmd(vini, logs, "key_adicionar", cargos=[fund], jogo="cs2", plano="1d",
                                  keys="ECO-AAAA-0001 ECO-AAAA-0002 ECO-AAAA-0003"))
    pedidos = []
    for c in clientes:
        server._cliques_menu.clear()
        await server.ao_interagir(inter(c, CS2, {"custom_id": "ecvd:menu:cs2", "values": ["1d"]}))
        pedidos.append(server._q1("SELECT * FROM pedidos WHERE usuario_id = ? ORDER BY criado_em DESC", (c,)))
    await server.atualizar_fila()
    txt, _ = fila_texto(fila)
    ok("3 pedido(s) esperando o cliente pagar" in txt and "PAGAMENTOS PARA CONFERIR" not in txt,
       "pedidos sem pagamento só aparecem como contagem (não precisam de resposta)")
    for p in pedidos[:2]:
        await server.ao_interagir(inter(int(p["usuario_id"]) and p["usuario_id"], p["canal_pagamento_id"],
                                        modal(f'ecvd:m_pagador:{p["id"]}', nome="Fulano de Tal"), tipo=5))
    alerta_pg = [m for m in msgs(alertas) if "Pagamento para conferir" in m["content"]]
    ok(len(alerta_pg) == 2 and all(f'`{p["id"]}`' in json.dumps(alerta_pg) and f'<#{p["canal_pagamento_id"]}>' in json.dumps(alerta_pg)
                                   for p in pedidos[:2]) and "R$ 3,90" in alerta_pg[0]["content"],
       "pagamento informado gera alerta com pedido, valor e link do canal")
    aviso_canal = msgs(pedidos[0]["canal_pagamento_id"])[-1]
    ok("Pagamento informado" in aviso_canal["content"] and f"<@&{fund}>" not in aviso_canal["content"]
       and not aviso_canal["_am"].get("roles"), "no canal do pedido o aviso continua, mas sem pingar a equipe de novo")
    await server.atualizar_fila()
    txt, m2 = fila_texto(fila)
    ok(m2["id"] == m_fila["id"], "a fila é sempre a MESMA mensagem (editada, não repostada)")
    ok("PAGAMENTOS PARA CONFERIR (2)" in txt and "1 pedido(s) esperando o cliente pagar" in txt
       and "TICKETS SEM RESPONSÁVEL (4)" in txt and "**6** precisam de resposta" in txt,
       "fila soma 2 pagamentos para conferir + 4 tickets sem responsável")
    primeiro = txt.index(pedidos[0]["id"]) < txt.index(pedidos[1]["id"])
    ok(primeiro, "mais antigos aparecem primeiro")

    # ── assumir ticket e aprovar pagamento tiram itens da fila ──
    await server.ao_interagir(inter(vini, t_ana, {"custom_id": "ecot:assumir"}, cargos=[fund]))
    await server.ao_interagir(inter(vini, pedidos[0]["canal_pagamento_id"],
                                    modal(f'ecvd:m_aprovar:{pedidos[0]["id"]}', confirmo="CONFIRMO"), tipo=5, cargos=[fund]))
    await server.atualizar_fila()
    txt, _ = fila_texto(fila)
    ok("TICKETS SEM RESPONSÁVEL (3)" in txt and "TICKETS EM ATENDIMENTO (1)" in txt and f"<@{vini}>" in txt,
       "ticket assumido sai de 'sem responsável' e mostra quem está atendendo")
    ok("PAGAMENTOS PARA CONFERIR (1)" in txt and pedidos[0]["id"] not in txt, "pagamento aprovado sai da fila")

    # ── sem estoque e entrega travada ──
    await server.ao_interagir(inter(vini, pedidos[1]["canal_pagamento_id"],
                                    modal(f'ecvd:m_aprovar:{pedidos[1]["id"]}', confirmo="CONFIRMO"), tipo=5, cargos=[fund]))
    await server.ao_interagir(inter(clientes[2], pedidos[2]["canal_pagamento_id"],
                                    modal(f'ecvd:m_pagador:{pedidos[2]["id"]}', nome="Beltrano Silva"), tipo=5))
    await server.ao_interagir(cmd(vini, logs, "key_revogar", cargos=[fund], motivo="teste", jogo="cs2", plano="1d", zerar_estoque=True))
    await server.ao_interagir(inter(vini, pedidos[2]["canal_pagamento_id"],
                                    modal(f'ecvd:m_aprovar:{pedidos[2]["id"]}', confirmo="CONFIRMO"), tipo=5, cargos=[fund]))
    ok(server._pedido(pedidos[2]["id"])["status"] == "AGUARDANDO_ESTOQUE", "3º pedido fica sem estoque (estoque zerado antes de aprovar)")
    ok(any("Sem keys" in m["content"] and pedidos[2]["id"] in m["content"] for m in msgs(alertas)),
       "falta de estoque vira alerta")
    sem = msgs(pedidos[2]["canal_pagamento_id"])[-1]
    ok("Sem keys" in sem["content"] and f"<@&{fund}>" not in sem["content"], "no canal do pedido, aviso sem pingar a equipe de novo")
    await server.atualizar_fila()
    txt, _ = fila_texto(fila)
    ok("APROVADOS SEM ESTOQUE (1)" in txt and "/key_adicionar" in txt, "fila mostra aprovado sem estoque")
    with server._tx() as conn:
        conn.execute("UPDATE pedidos SET status = 'APROVADO', entregando_desde = ? WHERE id = ?",
                     ((server._agora() - server.timedelta(minutes=10)).isoformat(), pedidos[2]["id"]))
    await server.atualizar_fila()
    txt, _ = fila_texto(fila)
    ok("ENTREGAS TRAVADAS (1)" in txt and "APROVADOS SEM ESTOQUE" not in txt, "entrega parada há mais de 3 min aparece como travada")
    with server._tx() as conn:
        conn.execute("UPDATE pedidos SET status = 'AGUARDANDO_ESTOQUE' WHERE id = ?", (pedidos[2]["id"],))

    # ── muita coisa ao mesmo tempo: a mensagem nunca passa do limite do Discord ──
    for i in range(60):
        cid = novo_canal(f"ticket-{i}", 0, tk_cat)
        server._cfg["tickets"][cid] = {"painel": pid_painel, "dono": vini, "dono_nome": "x" * 30, "numero": 100 + i,
                                       "motivo": "Problema com a compra " + "y" * 60, "aberto": server._agora().isoformat(),
                                       "status": "aberto"}
    embeds = server._montar_fila()
    total = sum(len(e.get("title", "")) + len(e.get("description", "")) + len((e.get("footer") or {}).get("text", "")) for e in embeds)
    ok(total <= 6000 and all(len(e["description"]) <= 4096 for e in embeds) and len(embeds) <= 10,
       f"com 64 tickets a fila respeita o limite do Discord ({total} caracteres)")
    ok("… e mais" in json.dumps(embeds, ensure_ascii=False), "o que não cabe vira '… e mais N'")
    for cid in [c for c, t in server._cfg["tickets"].items() if t["numero"] >= 100]:
        server._cfg["tickets"].pop(cid)

    # ── tudo resolvido ──
    for cid in list(server._cfg["tickets"]):
        server._cfg["tickets"][cid]["status"] = "fechado"
    with server._tx() as conn:
        conn.execute("UPDATE pedidos SET status = 'ENTREGUE' WHERE status != 'ENTREGUE'")
    await server.atualizar_fila()
    txt, m3 = fila_texto(fila)
    ok("Tudo em dia" in txt and m3["embeds"][0]["color"] == server.NEON and len(m3["embeds"]) == 1, "fila zerada mostra 'Tudo em dia'")
    n_edicoes = len(fake.webhooks)
    antes = json.dumps(m3)
    await server.atualizar_fila()
    ok(json.dumps(fila_texto(fila)[1]) == antes, "sem mudanças, a fila não é editada à toa")

    # ── a mensagem da fila foi apagada: o bot publica de novo ──
    fake.messages[fila] = []
    server._central["assinatura"] = None
    await server.atualizar_fila()
    ok(len([m for m in msgs(fila) if m["author"]["id"] == BOT]) == 1, "se apagarem a fila, o bot publica de novo")
    ok("💚" not in json.dumps(fake.messages, ensure_ascii=False), "nenhum 💚")
    print(f"\nCENTRAL OK — {ok_n} verificações")


asyncio.run(main())
