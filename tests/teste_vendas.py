"""Vendas automáticas ECO CHEATS: painéis, pedido, Pix exato, aprovação só do FUNDADOR, entrega, comandos, reinício."""
import asyncio
import json
import os
import shutil
import sys
import types
from datetime import timedelta

RASC = os.path.dirname(os.path.abspath(__file__))
PASTA_DB = os.path.join(RASC, "db_teste")
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
CANAIS_JOGOS = {"cs2": "1563252420497379437", "roblox-emulador": "1563259646880514150", "roblox-mobile": "1563640176667005028",
                "free-fire-emulador": "1563640365561413712", "free-fire-mobile": "1563640449363869746"}


def ok(cond, msg):
    global ok_n
    if not cond:
        raise AssertionError(msg)
    ok_n += 1
    print("  ✔", msg)


def canal_nome(parte):
    return next((c for c in fake.channels.values() if c.get("name") and parte in c["name"]), None)


def membro(usuario):
    return next(k for k, v in fake.members.items() if v["user"]["username"] == usuario)


def novo_membro(usuario, global_name):
    uid = fake_discord.novo_id()
    fake.members[uid] = {"user": {"id": uid, "username": usuario, "global_name": global_name}, "nick": None, "roles": [],
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


def cmd(uid, canal_id, nome, cargos=(), resolved=None, **op):
    data = {"name": nome, "type": 1, "options": [{"name": k, "type": 3, "value": v} for k, v in op.items()]}
    if resolved:
        data["resolved"] = resolved
    return inter(uid, canal_id, data, tipo=2, cargos=cargos, admin=True)


def modal(custom_id, **campos):
    return {"custom_id": custom_id, "components": [{"type": 1, "components": [{"type": 4, "custom_id": k, "value": v}]}
                                                  for k, v in campos.items()]}


def resposta():
    return json.dumps(fake.respostas[-1], ensure_ascii=False)


def webhook():
    return json.dumps(fake.webhooks[-1][2], ensure_ascii=False) if fake.webhooks else ""


def tudo_enviado():
    return json.dumps({k: v for k, v in fake.messages.items()}, ensure_ascii=False)


def msgs(cid):
    return fake.messages.get(cid, [])


async def reiniciar():
    """Simula um deploy: apaga o banco local, zera o estado e liga de novo (restaura do backup no Discord)."""
    await server.backup_vendas("teste")
    for t in (server._tarefa_backup, server._tarefa_paineis):
        if t and not t.done():
            t.cancel()
    server._db.close()
    server._db = None
    shutil.rmtree(PASTA_DB, ignore_errors=True)
    server._vendas.update(pronto=False, restaurado=None, backup_msg=None, escritas=0, sujo=False)
    server._FERNET_CACHE.clear()
    await server.iniciar_vendas()


async def main():
    for jid, cid in CANAIS_JOGOS.items():
        fake.channels[cid] = {"id": cid, "name": f"🥇・cheat・{jid}", "type": 0, "position": 3, "parent_id": None, "permission_overwrites": []}
    logs = fake_discord.novo_id()
    fake.channels[logs] = {"id": logs, "name": "📊・registro-de-vendas", "type": 0, "position": 9,
                           "parent_id": canal_nome("STAFF")["id"], "permission_overwrites": []}
    fund = next(r for r in fake.roles.values() if r["name"] == "Fundador")["id"]
    joao, joana, vini = membro("joao123"), membro("joana"), membro("vinicius")
    await server.carregar_config(forcar=True)

    # ── início ──
    await server.iniciar_vendas()
    ok(server._vendas["pronto"], "sistema de vendas inicia (sem backup → banco novo)")
    ok(server._cfg_vendas("cargo_fundador_id") == fund, "cargo FUNDADOR detectado pelo nome")
    ok(server._cfg_vendas("canal_logs_id") == logs, "canal de registro de vendas detectado")
    backup = canal_nome("backups-bot")
    ok(backup and any(a["filename"] == server.ARQ_BACKUP_VENDAS for m in msgs(backup["id"]) for a in m["attachments"]),
       "banco copiado para o canal privado de backups")
    precos = {(p["jogo"], p["plano"]): p["preco_centavos"] for p in server._q("SELECT * FROM produtos")}
    ok(all(precos[(j, "1d")] == 390 and precos[(j, "7d")] == 1790 and precos[(j, "15d")] == 3290 and precos[(j, "30d")] == 5490
           and precos[(j, "perm")] == 9900 for j in CANAIS_JOGOS), "preços exatos nos 5 jogos (3,90 • 17,90 • 32,90 • 54,90 • 99,00)")

    # ── painéis ──
    res = await server.sincronizar_paineis(criar=True)
    ok(all("publicado" in x for x in res) and len(res) == 5, "5 painéis publicados")
    for jid, cid in CANAIS_JOGOS.items():
        painel = [m for m in msgs(cid) if m["author"]["id"] == BOT]
        ok(len(painel) == 1 and painel[0]["components"][0]["components"][0]["custom_id"] == f"ecvd:menu:{jid}",
           f"painel no canal real de {jid} (pelo ID)")
    cs2 = msgs(CANAIS_JOGOS["cs2"])[-1]
    menu = cs2["components"][0]["components"][0]
    ok([o["label"] for o in menu["options"]] == ["Key 1 dia", "Key 7 dias", "Key 15 dias", "Key 30 dias", "Key permanente"],
       "menu com as 5 opções na ordem")
    ok(menu["options"][1]["description"] == "Preço: R$ 17,90 | Esgotado" and menu["placeholder"] == "➡️ Clique aqui para ver as opções",
       "opção mostra preço e estoque como na imagem")
    ok("PLANOS" not in cs2["embeds"][0]["description"] and "R$" not in cs2["embeds"][0]["description"]
       and "o passo a passo, seu login e sua key chegam num **canal privado de entrega**" in cs2["embeds"][0]["description"],
       "descrição sem a tabela de planos e com o passo 5 novo")
    ok("CS2 PC" in cs2["embeds"][0]["title"] and "PAGAMENTO" in cs2["embeds"][0]["description"]
       and "COMO COMPRAR" in cs2["embeds"][0]["description"] and cs2["embeds"][0]["color"] == server.NEON,
       "painel com título do jogo, pagamento, instruções e verde neon")
    ok("FREE FIRE MOBILE" in msgs(CANAIS_JOGOS["free-fire-mobile"])[-1]["embeds"][0]["title"], "cada painel identifica jogo e plataforma")
    n = sum(len(msgs(c)) for c in CANAIS_JOGOS.values())
    await server.sincronizar_paineis(criar=True)
    ok(sum(len(msgs(c)) for c in CANAIS_JOGOS.values()) == n, "publicar de novo atualiza (não duplica)")
    with server._tx() as conn:
        conn.execute("UPDATE jogos SET mensagem_id = NULL WHERE id = 'cs2'")
    await server.sincronizar_paineis(criar=True)
    ok(len([m for m in msgs(CANAIS_JOGOS["cs2"]) if m["author"]["id"] == BOT]) == 1, "se perder o ID, acha o painel no canal em vez de duplicar")

    # ── sem estoque não vende ──
    await server.ao_interagir(inter(joao, CANAIS_JOGOS["cs2"], {"custom_id": "ecvd:menu:cs2", "values": ["7d"]}))
    ok(fake.respostas[-1] == {"type": 6} and "esgotado" in webhook(), "plano sem estoque: avisa esgotado e não cria pedido")
    server._cliques_menu.clear()

    # ── keys ──
    await server.ao_interagir(cmd(joana, logs, "key_adicionar", jogo="cs2", plano="7d", keys="NAO-PODE-1234"))
    ok("FUNDADOR" in webhook() and not server._q("SELECT 1 FROM keys"), "só FUNDADOR adiciona keys (validado no servidor)")
    await server.ao_interagir(cmd(vini, logs, "key_adicionar", cargos=[fund], jogo="cs2", plano="7d",
                                  keys="CS2-AAAA-1111 CS2-BBBB-2222,CS2-AAAA-1111\nCS2-CCCC-3333"))
    ok("**3** key(s)" in webhook() and "1 repetida" in webhook(), "3 keys adicionadas, repetida ignorada")
    bruto = server._q1("SELECT valor_cifrado, final FROM keys WHERE id = 1")
    ok("CS2-AAAA-1111" not in bruto["valor_cifrado"] and bruto["final"] == "••••1111", "key guardada cifrada no banco")
    fake.cdn["https://cdn.discordapp.com/attachments/1/2/keys.txt"] = b"FF-M-0001\nFF-M-0002\n"
    await server.ao_interagir(cmd(vini, logs, "key_adicionar", cargos=[fund], jogo="free-fire-mobile", plano="perm", arquivo="99",
                                  resolved={"attachments": {"99": {"url": "https://cdn.discordapp.com/attachments/1/2/keys.txt",
                                                                   "filename": "keys.txt", "size": 20}}}))
    ok("**2** key(s)" in webhook(), "keys por arquivo .txt")
    await server.sincronizar_paineis(False)
    ok(msgs(CANAIS_JOGOS["cs2"])[-1]["components"][0]["components"][0]["options"][1]["description"] == "Preço: R$ 17,90 | Estoque: 3",
       "painel mostra o estoque atualizado")

    # ── compra ──
    await server.ao_interagir(inter(joao, CANAIS_JOGOS["cs2"], {"custom_id": "ecvd:menu:cs2", "values": ["7d"]}))
    ped = server._q1("SELECT * FROM pedidos WHERE usuario_id = ? ORDER BY criado_em DESC", (joao,))
    ok(ped and ped["status"] == "AGUARDANDO_PAGAMENTO" and ped["preco_centavos"] == 1790 and ped["id"].startswith("ECO-"),
       f'pedido {ped["id"]} registrado no SQLite')
    pag = fake.channels[ped["canal_pagamento_id"]]
    ok(pag["name"] == "venda-painel-cs2-joao123", f'canal de pagamento: #{pag["name"]}')
    cat = fake.channels[pag["parent_id"]]
    ok(cat["name"].startswith("🧾 PAGAMENTOS"), "dentro da categoria privada de pagamentos")
    ow = {o["id"]: o for o in pag["permission_overwrites"]}
    ok(int(ow[GID]["deny"]) & 1024 and int(ow[joao]["allow"]) & 1024 and int(ow[fund]["allow"]) & 1024 and BOT in ow and len(ow) == 4,
       "acesso só do cliente, do bot e do FUNDADOR")
    m_ped = msgs(pag["id"])[0]
    campos = {f["name"]: f["value"] for f in m_ped["embeds"][0]["fields"]}
    pix_esperado = server.gerar_pix(17.90, ped["id"].replace("-", ""))
    ok(campos["💰 Valor"] == "**R$ 17,90**" and campos["⏳ Duração"] == "7 dias" and campos["🎮 Jogo"] == "CS2 • PC"
       and campos["📦 Produto"] == "Key 7 dias" and ped["id"] in campos["🆔 Pedido"], "embed com produto, jogo, duração, valor e ID")
    ok(pix_esperado in campos["📋 Pix copia e cola"] and "540517.90" in pix_esperado and server._crc16(pix_esperado[:-4]) == pix_esperado[-4:],
       "Pix copia e cola com o valor exato (R$ 17,90) e CRC válido")
    ok(m_ped["embeds"][0]["image"]["url"], "QR Code no embed")
    rotulos = [c.get("label") for c in m_ped["components"][0]["components"]]
    ok(rotulos == ["CONFIRMAR PAGAMENTO", "CANCELAR PEDIDO"], "botões CONFIRMAR PAGAMENTO e CANCELAR PEDIDO")
    ok(any(m["content"] == pix_esperado for m in msgs(pag["id"])), "código Pix também sozinho numa mensagem (fácil de copiar no celular)")
    ok(not any("Copiar texto" in m["content"] or "☝️" in m["content"] for m in msgs(pag["id"])) and msgs(pag["id"])[-1]["content"] == pix_esperado,
       "sem a mensagem de dica depois do código Pix")
    ok(pag["id"] in webhook(), "cliente recebe o link do canal (só para ele)")
    for plano, valor in (("1d", "3.90"), ("15d", "32.90"), ("30d", "54.90"), ("perm", "99.00")):
        pr = server._produto("cs2", plano)
        codigo = server.gerar_pix(pr["preco_centavos"] / 100, "ECO12345678")
        ok(f"54{len(valor):02d}{valor}" in codigo, f"Pix do plano {plano} sai com R$ {valor}")
    server._cliques_menu.clear()
    await server.ao_interagir(inter(joao, CANAIS_JOGOS["cs2"], {"custom_id": "ecvd:menu:cs2", "values": ["1d"]}))
    ok("já tem um pedido aberto" in webhook(), "não abre dois pedidos do mesmo jogo")
    server._cliques_menu.clear()

    # nome igual: não colide
    xara = novo_membro("joao_outro", "joao123")
    await server.ao_interagir(inter(xara, CANAIS_JOGOS["cs2"], {"custom_id": "ecvd:menu:cs2", "values": ["7d"]}))
    ped_x = server._q1("SELECT * FROM pedidos WHERE usuario_id = ?", (xara,))
    ok(fake.channels[ped_x["canal_pagamento_id"]]["name"] == f'venda-painel-cs2-joao123-{ped_x["id"][-4:].lower()}',
       "mesmo nome de outra pessoa: canal ganha sufixo do pedido")
    server._cliques_menu.clear()

    # ── confirmar pagamento ──
    await server.ao_interagir(inter(joana, pag["id"], {"custom_id": f'ecvd:pagar:{ped["id"]}'}))
    ok("Só quem fez o pedido" in resposta(), "outra pessoa não confirma o pagamento")
    await server.ao_interagir(inter(joao, pag["id"], {"custom_id": f'ecvd:pagar:{ped["id"]}'}))
    ok(fake.respostas[-1]["type"] == 9 and fake.respostas[-1]["data"]["components"][0]["components"][0]["label"] == "Nome completo do pagador",
       "CONFIRMAR PAGAMENTO abre o formulário 'Nome completo do pagador'")
    await server.ao_interagir(inter(joao, pag["id"], modal(f'ecvd:m_pagador:{ped["id"]}', nome="joao"), tipo=5))
    ok("nome completo" in resposta() and server._pedido(ped["id"])["status"] == "AGUARDANDO_PAGAMENTO", "nome incompleto é recusado")
    await server.ao_interagir(inter(joao, pag["id"], modal(f'ecvd:m_pagador:{ped["id"]}', nome="João da Silva Souza"), tipo=5))
    p = server._pedido(ped["id"])
    ok(p["status"] == "AGUARDANDO_CONFERENCIA" and "João" not in (p["pagador_cifrado"] or "")
       and server.decifrar(p["pagador_cifrado"]) == "João da Silva Souza", "status AGUARDANDO_CONFERENCIA e nome guardado cifrado")
    r7 = fake.respostas[-1]
    ok(r7["type"] == 7 and [c["label"] for c in r7["data"]["components"][0]["components"]] == ["APROVAR PAGAMENTO", "REJEITAR PAGAMENTO"]
       and "João da Silva Souza" in json.dumps(r7, ensure_ascii=False), "mensagem do pedido atualizada com o pagador e os botões da equipe")
    ok(f"<@&{fund}>" in msgs(pag["id"])[-1]["content"], "FUNDADOR é avisado")
    await server.ao_interagir(inter(joao, pag["id"], modal(f'ecvd:m_pagador:{ped["id"]}', nome="João da Silva Souza"), tipo=5))
    ok("já foi informado" in resposta(), "informar o pagamento duas vezes não muda nada")
    await server.ao_interagir(inter(joao, pag["id"], {"custom_id": f'ecvd:cancelar:{ped["id"]}'}))
    ok("não pode mais ser cancelado" in resposta(), "depois de informar, o cliente não cancela")

    # ── aprovação só do FUNDADOR ──
    await server.ao_interagir(inter(joana, pag["id"], {"custom_id": f'ecvd:aprovar:{ped["id"]}'}, admin=True))
    ok("FUNDADOR" in resposta() and server._pedido(ped["id"])["status"] == "AGUARDANDO_CONFERENCIA",
       "administrador sem o cargo FUNDADOR não aprova")
    await server.ao_interagir(inter(joana, pag["id"], modal(f'ecvd:m_aprovar:{ped["id"]}', confirmo="CONFIRMO"), tipo=5, admin=True))
    ok("FUNDADOR" in resposta() and server._pedido(ped["id"])["status"] == "AGUARDANDO_CONFERENCIA",
       "mesmo mandando o formulário direto, o servidor bloqueia quem não é FUNDADOR")
    await server.ao_interagir(inter(vini, pag["id"], {"custom_id": f'ecvd:aprovar:{ped["id"]}'}, cargos=[fund]))
    ok(fake.respostas[-1]["type"] == 9 and "CONFIRMO" in resposta(), "FUNDADOR precisa confirmar que conferiu o Pix (digitar CONFIRMO)")
    await server.ao_interagir(inter(vini, pag["id"], modal(f'ecvd:m_aprovar:{ped["id"]}', confirmo="sim"), tipo=5, cargos=[fund]))
    ok("não** feita" in resposta() and server._pedido(ped["id"])["status"] == "AGUARDANDO_CONFERENCIA", "sem CONFIRMO não aprova")
    await server.ao_interagir(inter(vini, pag["id"], modal(f'ecvd:m_aprovar:{ped["id"]}', confirmo="confirmo"), tipo=5, cargos=[fund]))
    p = server._pedido(ped["id"])
    ok(p["status"] == "ENTREGUE" and p["aprovado_por"] == vini and p["aprovado_em"] and p["entregue_em"], "aprovado (quem e quando) e entregue")
    ent = fake.channels[p["canal_entrega_id"]]
    ok(ent["name"] == "entrega-cs2-joao123" and fake.channels[ent["parent_id"]]["name"].startswith("📦 ENTREGAS"),
       f'NOVO canal privado de entrega: #{ent["name"]}')
    ow = {o["id"]: o for o in ent["permission_overwrites"]}
    ok(int(ow[GID]["deny"]) & 1024 and set(ow) == {GID, joao, BOT, fund}, "entrega visível só para comprador, bot e FUNDADOR")
    ok(any(m["content"] == "Key: CS2-AAAA-1111" for m in msgs(ent["id"])), "key entregue sozinha numa mensagem (fácil de copiar)")
    me = msgs(ent["id"])
    ok(len(me) == 2 and me[0]["embeds"][0]["title"] == "✅ Pagamento aprovado" and "Key 7 dias" in me[0]["embeds"][0]["description"]
       and "A key está logo abaixo" in me[0]["embeds"][0]["description"] and f"<@{joao}>" == me[0]["content"],
       "entrega: resumo compacto (jogo, produto, validade, pedido, valor) e aviso de que a key está abaixo")
    ok(me[-1]["content"] == "Key: CS2-AAAA-1111" and not me[-1].get("embeds")
       and me[-1]["components"][0]["components"][0]["custom_id"] == f'ecvd:fechar_entrega:{ped["id"]}',
       "key sozinha na última mensagem, com o botão de fechar junto")
    ok("Sua key" not in json.dumps(me, ensure_ascii=False) and "Copiar texto" not in json.dumps(me, ensure_ascii=False)
       and "Já guardou tudo" not in json.dumps(me, ensure_ascii=False), "sem o embed 'Sua key' nem textos de dica")
    k = server._q1("SELECT * FROM keys WHERE id = ?", (p["key_id"],))
    ok(k["status"] == "entregue" and k["validade_dias"] == 7 and k["expira_em"], "key marcada como entregue com validade (informativa)")
    ok("entregue no canal privado" in msgs(pag["id"])[-1]["content"] and p["fechar_pagamento_em"], "canal de pagamento avisa e é agendado para limpeza")
    auditoria = [a["acao"] for a in server._q("SELECT acao FROM auditoria WHERE pedido_id = ? ORDER BY id", (ped["id"],))]
    ok(auditoria == ["pedido_criado", "pagamento_informado", "aprovado", "entregue"], f"auditoria completa: {auditoria}")
    await server.ao_interagir(inter(vini, pag["id"], modal(f'ecvd:m_aprovar:{ped["id"]}', confirmo="CONFIRMO"), tipo=5, cargos=[fund]))
    ok("já foi decidido" in resposta() and server._q1("SELECT COUNT(*) n FROM keys WHERE status = 'entregue'")["n"] == 1,
       "aprovar de novo não entrega outra key")
    await server.entregar_pedido(ped["id"])
    ok(server._q1("SELECT COUNT(*) n FROM keys WHERE status = 'entregue'")["n"] == 1, "chamar a entrega de novo também não duplica")

    # ── rejeição ──
    await server.ao_interagir(inter(joana, CANAIS_JOGOS["cs2"], {"custom_id": "ecvd:menu:cs2", "values": ["7d"]}))
    pj = server._q1("SELECT * FROM pedidos WHERE usuario_id = ? ORDER BY criado_em DESC", (joana,))
    await server.ao_interagir(inter(joana, pj["canal_pagamento_id"], modal(f'ecvd:m_pagador:{pj["id"]}', nome="Joana Pereira"), tipo=5))
    await server.ao_interagir(inter(vini, pj["canal_pagamento_id"], {"custom_id": f'ecvd:rejeitar:{pj["id"]}'}, cargos=[fund]))
    ok(fake.respostas[-1]["type"] == 9 and "Motivo" in resposta(), "rejeitar pede o motivo")
    await server.ao_interagir(inter(vini, pj["canal_pagamento_id"], modal(f'ecvd:m_rejeitar:{pj["id"]}', motivo="Pix não encontrado"),
                                    tipo=5, cargos=[fund]))
    pj = server._pedido(pj["id"])
    ok(pj["status"] == "REJEITADO" and pj["motivo_rejeicao"] == "Pix não encontrado" and pj["rejeitado_por"] == vini, "rejeição registrada com motivo")
    ok("Pix não encontrado" in json.dumps(msgs("9" + joana[1:])[-1], ensure_ascii=False), "cliente avisado na DM com o motivo")
    ok(server._q1("SELECT COUNT(*) n FROM keys WHERE status = 'disponivel' AND jogo = 'cs2'")["n"] == 2, "rejeição não gasta key")
    server._cliques_menu.clear()

    # ── cancelamento e limpeza ──
    await server.ao_interagir(inter(joana, CANAIS_JOGOS["cs2"], {"custom_id": "ecvd:menu:cs2", "values": ["7d"]}))
    pc = server._q1("SELECT * FROM pedidos WHERE usuario_id = ? AND status = 'AGUARDANDO_PAGAMENTO'", (joana,))
    await server.ao_interagir(inter(joana, pc["canal_pagamento_id"], {"custom_id": f'ecvd:cancelar:{pc["id"]}'}))
    ok("Sim, cancelar" in resposta(), "cancelar pede confirmação")
    await server.ao_interagir(inter(joana, pc["canal_pagamento_id"], {"custom_id": f'ecvd:cancelar_ok:{pc["id"]}'}))
    ok(server._pedido(pc["id"])["status"] == "CANCELADO", "pedido cancelado")
    with server._tx() as conn:
        conn.execute("UPDATE pedidos SET fechar_pagamento_em = ? WHERE id IN (?, ?)", ((server._agora() - timedelta(seconds=1)).isoformat(), pc["id"], pj["id"]))
    await server.rodar_vendas()
    ok(pc["canal_pagamento_id"] not in fake.channels and pj["canal_pagamento_id"] not in fake.channels, "canais de pagamento encerrados são apagados")
    ok(ent["id"] in fake.channels, "canal de entrega NÃO é apagado sozinho")
    server._cliques_menu.clear()

    # ── expiração ──
    await server.ao_interagir(inter(joana, CANAIS_JOGOS["cs2"], {"custom_id": "ecvd:menu:cs2", "values": ["7d"]}))
    pe = server._q1("SELECT * FROM pedidos WHERE usuario_id = ? AND status = 'AGUARDANDO_PAGAMENTO'", (joana,))
    with server._tx() as conn:
        conn.execute("UPDATE pedidos SET criado_em = ? WHERE id = ?", ((server._agora() - timedelta(hours=25)).isoformat(), pe["id"]))
    await server.rodar_vendas()
    ok(server._pedido(pe["id"])["status"] == "EXPIRADO", "pedido sem pagamento expira em 24 h")
    server._cliques_menu.clear()

    # ── sem estoque na aprovação → espera → entrega automática ──
    await server.ao_interagir(inter(joana, CANAIS_JOGOS["free-fire-mobile"], {"custom_id": "ecvd:menu:free-fire-mobile", "values": ["perm"]}))
    pf = server._q1("SELECT * FROM pedidos WHERE usuario_id = ? AND jogo = 'free-fire-mobile'", (joana,))
    ok(pf["preco_centavos"] == 9900 and "venda-painel-free-fire-mobile-joana" == fake.channels[pf["canal_pagamento_id"]]["name"],
       "pedido de Free Fire Mobile permanente (R$ 99,00)")
    await server.ao_interagir(inter(joana, pf["canal_pagamento_id"], modal(f'ecvd:m_pagador:{pf["id"]}', nome="Joana Pereira"), tipo=5))
    for row in server._q("SELECT final FROM keys WHERE jogo = 'free-fire-mobile' AND status = 'disponivel'"):
        pass
    await server.ao_interagir(cmd(vini, logs, "key_revogar", cargos=[fund], key="FF-M-0001", motivo="teste"))
    await server.ao_interagir(cmd(vini, logs, "key_revogar", cargos=[fund], key="FF-M-0002", motivo="teste"))
    ok(server._estoque("free-fire-mobile", "perm")["disponiveis"] == 0, "keys revogadas saem do estoque")
    await server.ao_interagir(inter(vini, pf["canal_pagamento_id"], modal(f'ecvd:m_aprovar:{pf["id"]}', confirmo="CONFIRMO"), tipo=5, cargos=[fund]))
    pf = server._pedido(pf["id"])
    ok(pf["status"] == "AGUARDANDO_ESTOQUE" and not pf["canal_entrega_id"], "sem key: não entrega e fica aguardando estoque")
    ok("Sem keys" in msgs(pf["canal_pagamento_id"])[-1]["content"] and f"<@&{fund}>" in msgs(pf["canal_pagamento_id"])[-1]["content"],
       "FUNDADOR é avisado da falta de estoque")
    await server.ao_interagir(cmd(vini, logs, "key_adicionar", cargos=[fund], jogo="free-fire-mobile", plano="perm", keys="FF-M-NOVA-9"))
    await asyncio.sleep(0.3)
    pf = server._pedido(pf["id"])
    ok(pf["status"] == "ENTREGUE" and any(m["content"] == "Key: FF-M-NOVA-9" for m in msgs(pf["canal_entrega_id"])),
       "ao adicionar keys, o pedido esperando é entregue automaticamente")

    # ── retomada depois de queda no meio da entrega ──
    await server.ao_interagir(cmd(vini, logs, "key_adicionar", cargos=[fund], jogo="roblox-mobile", plano="30d", keys="RB-30-AAA RB-30-BBB"))
    server._cliques_menu.clear()
    await server.ao_interagir(inter(joana, CANAIS_JOGOS["roblox-mobile"], {"custom_id": "ecvd:menu:roblox-mobile", "values": ["30d"]}))
    pr_ = server._q1("SELECT * FROM pedidos WHERE usuario_id = ? AND jogo = 'roblox-mobile'", (joana,))
    with server._tx() as conn:  # simula: aprovado, key reservada, bot caiu antes de terminar
        conn.execute("UPDATE pedidos SET status = 'ENTREGANDO', aprovado_por = ?, aprovado_em = ?, entregando_desde = ?, key_id = 4 WHERE id = ?",
                     (vini, server._agora_iso(), (server._agora() - timedelta(minutes=5)).isoformat(), pr_["id"]))
        conn.execute("UPDATE keys SET status = 'reservada', pedido_id = ? WHERE id = (SELECT id FROM keys WHERE final = '••••-AAA')", (pr_["id"],))
    await server.rodar_vendas()
    pr_ = server._pedido(pr_["id"])
    ok(pr_["status"] == "ENTREGUE" and any(m["content"] == "Key: RB-30-AAA" for m in msgs(pr_["canal_entrega_id"]))
       and server._q1("SELECT status FROM keys WHERE final = '••••-BBB'")["status"] == "disponivel",
       "entrega interrompida é retomada com a MESMA key reservada")
    with server._tx() as conn:
        conn.execute("UPDATE pedidos SET status = 'APROVADO', aprovado_por = NULL WHERE id = ?", (pr_["id"],))
    ok(await server.entregar_pedido(pr_["id"]) == "pedido sem aprovação registrada", "sem aprovação registrada nada é entregue")
    with server._tx() as conn:
        conn.execute("UPDATE pedidos SET status = 'ENTREGUE', aprovado_por = ? WHERE id = ?", (vini, pr_["id"]))

    # ── fechar canal de entrega ──
    await server.ao_interagir(inter(joana, ent["id"], {"custom_id": f'ecvd:fechar_entrega:{ped["id"]}'}))
    ok("Só quem comprou" in resposta(), "outra pessoa não fecha a entrega")
    await server.ao_interagir(inter(joao, ent["id"], {"custom_id": f'ecvd:fechar_entrega_ok:{ped["id"]}'}))
    with server._tx() as conn:
        conn.execute("UPDATE pedidos SET fechar_entrega_em = ? WHERE id = ?", ((server._agora() - timedelta(seconds=1)).isoformat(), ped["id"]))
    await server.rodar_vendas()
    ok(ent["id"] not in fake.channels, "comprador fecha o próprio canal de entrega")

    # ── comandos ──
    for nome in ("key_estoque", "pedido_consultar", "pedidos_pendentes", "painel_vendas_publicar", "produto_configurar"):
        await server.ao_interagir(cmd(joana, logs, nome, jogo="cs2", plano="7d", pedido=ped["id"]))
        texto = webhook()
        ok("FUNDADOR" in texto or "não tem permissão" in texto, f"/{nome} bloqueado para quem não é FUNDADOR")
    await server.ao_interagir(cmd(vini, logs, "produto_configurar", cargos=[fund], jogo="todos", plano="7d", preco=18.9))
    ok(all(server._produto(j, "7d")["preco_centavos"] == 1890 for j in CANAIS_JOGOS), "/produto_configurar muda o preço em todos os jogos")
    await server.sincronizar_paineis(False)
    ok("R$ 18,90" in msgs(CANAIS_JOGOS["roblox-emulador"])[-1]["components"][0]["components"][0]["options"][1]["description"],
       "painéis mostram o preço novo")
    await server.ao_interagir(cmd(vini, logs, "painel_vendas_atualizar", cargos=[fund], plano="7d", preco=17.9))
    ok(all(server._produto(j, "7d")["preco_centavos"] == 1790 for j in CANAIS_JOGOS) and "atualizado" in webhook(),
       "/painel_vendas_atualizar volta o preço e atualiza os painéis")
    await server.ao_interagir(cmd(vini, logs, "painel_vendas_atualizar", cargos=[fund], plano="1d", ativo=False, jogo="cs2"))
    await server.sincronizar_paineis(False)
    ok([o["value"] for o in msgs(CANAIS_JOGOS["cs2"])[-1]["components"][0]["components"][0]["options"]] == ["7d", "15d", "30d", "perm"],
       "plano desativado some do menu")
    await server.ao_interagir(cmd(vini, logs, "key_estoque", cargos=[fund], jogo="cs2"))
    ok("Key 7 dias" in webhook() and "2 disp." in webhook(), "/key_estoque por jogo e plano")
    await server.ao_interagir(cmd(vini, logs, "key_consultar", cargos=[fund], key="CS2-AAAA-1111"))
    ok("••••1111" in webhook() and "CS2-AAAA-1111" not in webhook() and "entregue" in webhook() and ped["id"] in webhook(),
       "/key_consultar mostra a key mascarada e o pedido")
    await server.ao_interagir(cmd(vini, logs, "key_consultar", cargos=[fund], pedido=ped["id"], mostrar_completa=True))
    ok("CS2-AAAA-1111" in webhook(), "mostrar_completa revela a key só para quem pediu")
    await server.ao_interagir(cmd(vini, logs, "pedido_consultar", cargos=[fund], pedido=ped["id"].lower()))
    ok("João da Silva Souza" in webhook() and "Aprovado por" in webhook() and "Histórico" in webhook(), "/pedido_consultar com pagador e histórico")
    await server.ao_interagir(cmd(vini, logs, "pedidos_pendentes", cargos=[fund]))
    ok("Vendas de keys" in webhook(), "/pedidos_pendentes inclui as vendas de keys")
    await server.ao_interagir(cmd(joana, logs, "vendas"))
    ok("não tem permissão" in webhook() or "não tem permissão" in resposta(), "/vendas exige o cargo FUNDADOR (mesmo para administrador)")
    await server.ao_interagir(inter(joana, logs, {"name": "ticket_painel", "options": []}, tipo=2, admin=False))
    ok("não tem permissão" in resposta(), "/ticket_painel exige administrador no servidor (não só no menu do Discord)")
    await server.ao_interagir(inter(vini, logs, {"name": "pedido_consultar", "options": [{"name": "pedido", "value": "eco", "focused": True}]},
                                    tipo=4, cargos=[fund]))
    ok(fake.respostas[-1]["type"] == 8 and fake.respostas[-1]["data"]["choices"], "autocompletar de pedidos")
    await server.ao_interagir(cmd(vini, logs, "entrega_configurar", cargos=[fund], jogo="cs2"))
    ok(fake.respostas[-1]["type"] == 9 and fake.respostas[-1]["data"]["custom_id"] == "ecvd:m_entrega:cs2:*", "/entrega_configurar abre formulário")
    await server.ao_interagir(inter(vini, logs, modal("ecvd:m_entrega:cs2:*", instrucoes="1. Baixe o painel\n2. Cole a key",
                                                      login="usuario: eco / senha: 123", link="https://exemplo.com/download"), tipo=5, cargos=[fund]))
    ec = server._q1("SELECT * FROM entregas_config WHERE jogo = 'cs2'")
    ok(ec["instrucoes"].startswith("1. Baixe") and "senha" not in ec["login_cifrado"], "instruções salvas e login cifrado")
    server._cliques_menu.clear()
    await server.ao_interagir(inter(joana, CANAIS_JOGOS["cs2"], {"custom_id": "ecvd:menu:cs2", "values": ["7d"]}))
    p2 = server._q1("SELECT * FROM pedidos WHERE usuario_id = ? AND status = 'AGUARDANDO_PAGAMENTO'", (joana,))
    await server.ao_interagir(inter(joana, p2["canal_pagamento_id"], modal(f'ecvd:m_pagador:{p2["id"]}', nome="Joana Pereira"), tipo=5))

    # ── zerar o estoque de um plano ──
    await server.ao_interagir(cmd(vini, logs, "key_adicionar", cargos=[fund], jogo="cs2", plano="1d", keys="Z1 CS2-Z2X-0002 CS2-Z3X-0003 CS2-Z4X-0004"))
    await server.ao_interagir(cmd(vini, logs, "key_revogar", cargos=[fund], motivo="limpeza", zerar_estoque=True))
    ok("escolha também o **jogo**" in webhook(), "zerar sem jogo/plano pede os dois")
    await server.ao_interagir(cmd(joana, logs, "key_revogar", motivo="x", jogo="cs2", plano="1d", zerar_estoque=True))
    ok("FUNDADOR" in webhook() and server._estoque("cs2", "1d")["disponiveis"] == 3, "só FUNDADOR zera o estoque")
    entregues_antes = server._q1("SELECT COUNT(*) n FROM keys WHERE status = 'entregue'")["n"]
    await server.ao_interagir(cmd(vini, logs, "key_revogar", cargos=[fund], motivo="limpeza", jogo="cs2", plano="1d", zerar_estoque=True))
    ok("**3** key(s)" in webhook() and server._estoque("cs2", "1d")["disponiveis"] == 0
       and server._estoque("cs2", "7d")["disponiveis"] > 0
       and server._q1("SELECT COUNT(*) n FROM keys WHERE status = 'entregue'")["n"] == entregues_antes,
       "zerar tira só as disponíveis daquele jogo e plano (entregues e outros planos ficam)")
    await server.ao_interagir(cmd(vini, logs, "key_adicionar", cargos=[fund], jogo="cs2", plano="perm", keys="CS2-Z2X-0002 CS2-Z3X-0003 CS2-AAAA-1111"))
    ok("**2** key(s)" in webhook() and "voltaram ao estoque" in webhook() and "1 repetida" in webhook()
       and server._estoque("cs2", "perm")["disponiveis"] == 2,
       "keys revogadas (nunca entregues) podem voltar em outro plano; key já entregue não volta")

    # ── reinício: banco volta do backup, botões continuam funcionando ──
    n_paineis = sum(len(msgs(c)) for c in CANAIS_JOGOS.values())
    await reiniciar()
    ok(server._vendas["pronto"] and server._vendas["restaurado"], "depois de reiniciar, o banco volta do backup")
    ok(server._pedido(ped["id"])["status"] == "ENTREGUE" and server._q1("SELECT COUNT(*) n FROM keys")["n"] == 11, "pedidos e keys preservados")
    await server.sincronizar_paineis(criar=True)
    ok(sum(len(msgs(c)) for c in CANAIS_JOGOS.values()) == n_paineis, "reiniciar não cria painéis novos")
    await server.ao_interagir(inter(vini, p2["canal_pagamento_id"], modal(f'ecvd:m_aprovar:{p2["id"]}', confirmo="CONFIRMO"), tipo=5, cargos=[fund]))
    p2 = server._pedido(p2["id"])
    ok(p2["status"] == "ENTREGUE", "botões de um pedido antigo funcionam depois de reiniciar")
    textos_ent = json.dumps(msgs(p2["canal_entrega_id"]), ensure_ascii=False)
    ok("1. Baixe o painel" in textos_ent and "usuario: eco / senha: 123" in textos_ent and "exemplo.com/download" in textos_ent,
       "entrega leva instruções, login e link configurados")
    me2 = msgs(p2["canal_entrega_id"])
    ok([m["embeds"][0]["title"] if m.get("embeds") else "KEY" for m in me2] == ["✅ Pagamento aprovado", "📖 Passo a passo", "🔐 Seu login", "KEY"]
       and "O passo a passo, o login e a key estão logo abaixo" in me2[0]["embeds"][0]["description"]
       and me2[-1].get("components") and not me2[-2].get("components"),
       "ordem da entrega: resumo → passo a passo → login → key (com botão de fechar)")
    bd = open(server.VENDAS_DB, "rb").read()
    ok(b"CS2-BBBB-2222" not in bd and b"senha: 123" not in bd and "Joana Pereira".encode() not in bd, "arquivo do banco não tem keys, login nem nomes em texto puro")

    # ── arquivo .txt com título, numeração e separadores (como o do gerador) ──
    import random
    rnd = random.Random(7)
    def hx():
        return "".join(rnd.choice("0123456789ABCDEF") for _ in range(8))
    reais = [f"ECO-{hx()}-{hx()}-{hx()}-{hx()}-{hx()}" for _ in range(50)]
    linhas = ["ECO CHEATS - KEYS DE 1 DIA", "=========================", "Quantidade: 50",
              "Validade: 1 dia a partir do primeiro registro", "Filtro: keys não revogadas", "Gerado em: 29/10/2026 23:44", ""]
    for g in range(5):
        linhas += [f"GRUPO {g + 1} - KEYS {g * 10 + 1:02d} A {g * 10 + 10:02d}", "-" * 44]
        linhas += [f"{g * 10 + i + 1:02d}. {reais[g * 10 + i]}" for i in range(10)] + [""]
    arquivo = "\n".join(linhas)
    lidas, ign, fora = server._ler_keys(arquivo)
    ok(lidas == reais and ign == 16 and not fora, f"lê só as 50 keys do arquivo (ignorou {ign} linhas: título, grupos, separadores)")
    for lixo in ("GRUPO", "01.", "-----", "=====", "Quantidade:", "revogadas", "CHEATS", "29/10/2026", "23:44", "https://x.com/a1b2c3"):
        ok(not server._parece_key(lixo), f"não é key: {lixo}")
    for boa in ("ECO-5127E36A-45DECC00", "CS2-AAAA-1111", "FF-M-0001", "123456789", "ABCDEFGHIJKLMNOPQR", "`XPTO-9999`"):
        ok(server._parece_key(boa), f"é key: {boa}")
    fake.cdn["https://cdn.discordapp.com/attachments/1/3/Eco-50-keys-1-dia.txt"] = arquivo.encode()
    await server.ao_interagir(cmd(vini, logs, "key_adicionar", cargos=[fund], jogo="roblox-mobile", plano="1d", arquivo="98",
                                  resolved={"attachments": {"98": {"url": "https://cdn.discordapp.com/attachments/1/3/Eco-50-keys-1-dia.txt",
                                                                   "filename": "Eco-50-keys-1-dia.txt", "size": len(arquivo)}}}))
    w = webhook()
    ok("**50** key(s)" in w and "ignorei" in w and server._estoque("roblox-mobile", "1d")["disponiveis"] == 50
       and f"primeira ••••{reais[0][-4:]}" in w and f"última ••••{reais[-1][-4:]}" in w,
       "arquivo de 50 keys entra como 50 (não 117) e a resposta mostra primeira e última para conferir")
    ok(reais[0] not in w, "a resposta não mostra a key completa")
    await server.ao_interagir(cmd(vini, logs, "key_adicionar", cargos=[fund], jogo="roblox-mobile", plano="7d",
                                  keys=f"ECO-{hx()}-{hx()}-{hx()}-{hx()}-{hx()} ECO-{hx()}-{hx()}-{hx()}-{hx()}-{hx()} RB7-OUTRO-1234"))
    ok("**3** key(s)" in webhook(), "poucas keys de formatos diferentes entram normalmente")
    seis = [f"RB30-{hx()}-{hx()}" for _ in range(6)]
    antes30 = server._estoque("roblox-mobile", "30d")["disponiveis"]
    await server.ao_interagir(cmd(vini, logs, "key_adicionar", cargos=[fund], jogo="roblox-mobile", plano="30d",
                                  keys="\n".join(seis + ["Lote-2026-outubro"])))
    w = webhook()
    ok("**6** key(s)" in w and "`Lote-2026-outubro`" in w and "não** adicionada" in w
       and server._estoque("roblox-mobile", "30d")["disponiveis"] == antes30 + 6,
       "item fora do formato das outras keys fica de fora e aparece para conferência")

    # ── limpeza do que entrou antes da correção ──
    with server._tx() as conn:
        for lixo in ("GRUPO", "01.", "--------------------------------------------", "Quantidade:"):
            conn.execute("INSERT INTO keys (jogo, plano, valor_cifrado, hash, final, status) VALUES ('roblox-mobile', '15d', ?, ?, ?, 'disponivel')",
                         (server.cifrar(lixo), server._hash_key(lixo), server._mascarar(lixo)))
        conn.execute("INSERT INTO keys (jogo, plano, valor_cifrado, hash, final, status) VALUES ('roblox-mobile', '15d', ?, ?, ?, 'disponivel')",
                     (server.cifrar("RB15-KEYB-0001"), server._hash_key("RB15-KEYB-0001"), "••••0001"))
    ok(server._estoque("roblox-mobile", "15d")["disponiveis"] == 5, "estoque com lixo de arquivo antigo (simulado)")
    entregues_antes = server._q1("SELECT COUNT(*) n FROM keys WHERE status = 'entregue'")["n"]
    await reiniciar()
    ok(server._estoque("roblox-mobile", "15d")["disponiveis"] == 1 and server._estoque("roblox-mobile", "1d")["disponiveis"] == 50
       and server._q1("SELECT COUNT(*) n FROM keys WHERE status = 'entregue'")["n"] == entregues_antes,
       "ao ligar, o bot revoga o que não é key e deixa as keys de verdade (e as entregues) como estão")
    ok(server._q1("SELECT COUNT(*) n FROM keys WHERE motivo_revogacao LIKE 'não era key%'")["n"] == 4
       and server._q1("SELECT 1 FROM auditoria WHERE acao = 'keys_invalidas_revogadas'"), "limpeza registrada na auditoria")
    ok(server._limpar_keys_invalidas("1") == 0, "limpeza não repete nada na segunda vez")

    # ── keys nunca em canais públicos, sem 💚 ──
    entregas = {p["canal_entrega_id"] for p in server._q("SELECT canal_entrega_id FROM pedidos WHERE canal_entrega_id IS NOT NULL")}
    vazou = []
    for cid, lista in fake.messages.items():
        if cid in entregas:
            continue
        for m in lista:
            corpo = json.dumps({k: m.get(k) for k in ("content", "embeds")}, ensure_ascii=False)
            for key in ("CS2-AAAA-1111", "CS2-BBBB-2222", "CS2-CCCC-3333", "FF-M-NOVA-9", "RB-30-AAA", "usuario: eco / senha"):
                if key in corpo:
                    vazou.append((cid, key))
    ok(not vazou, f"keys e login só aparecem nos canais privados de entrega {vazou}")
    ok("💚" not in tudo_enviado() and "💚" not in json.dumps(fake.respostas, ensure_ascii=False), "nenhum 💚 em lugar nenhum")
    st = await server.status_agente()
    ok(st["vendas_keys"]["pronto"] and st["vendas_keys"]["cargo_fundador"] == fund, "status_agente mostra as vendas")
    vs = await server.vendas_status()
    ok("CS2-" not in json.dumps(vs) and vs["precos"]["cs2/7d"] == "R$ 17,90", "vendas_status (Claude) sem expor keys")
    print(f"\nVENDAS OK — {ok_n} verificações")


asyncio.run(main())
