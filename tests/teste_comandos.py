"""Testa os comandos de barra (/ping, /loja_painel, /vendas, /pedidos_pendentes, /aprovar_pagamento,
/ticket_painel, /verificacao_painel) contra o Discord simulado, com uma compra completa."""
import asyncio
import json
import os
import sys
import types

os.environ.update(DISCORD_TOKEN="token-falso", GUILD_ID="111111111111111111", CHAVE_SECRETA="x",
                  PIX_CHAVE="pix@ecopulse.com")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import httpx2 as httpx

import fake_discord
import fake_discord2
from suporte import bot as server

GID, BOT = fake_discord.GID, fake_discord.BOT
fake = fake_discord2.Fake2()
server._api = httpx.AsyncClient(base_url=server.API + "/", transport=httpx.MockTransport(fake.handler))
server._web = httpx.AsyncClient(transport=httpx.MockTransport(fake.handler))
server.FECHAR_TICKET_EM = 0
ok_n = 0


def ok(cond, msg):
    global ok_n
    if not cond:
        raise AssertionError(msg)
    ok_n += 1
    print("  ✔", msg)


def canal(nome):
    return next(c for c in fake.channels.values() if c.get("name") and nome in c["name"])


def cargo(nome):
    return next(r for r in fake.roles.values() if r["name"] == nome)


def membro(usuario):
    return next(k for k, v in fake.members.items() if v["user"]["username"] == usuario)


def novo_canal(nome, tipo=0, parent=None):
    cid = fake_discord.novo_id()
    fake.channels[cid] = {"id": cid, "name": nome, "type": tipo, "position": 5, "parent_id": parent, "permission_overwrites": []}
    return cid


def inter(uid, canal_id, *, tipo=3, data=None, cargos=(), admin=False):
    u = fake.members[uid]["user"]
    return types.SimpleNamespace(
        id=fake_discord.novo_id(), token="tok", application_id=BOT, type=tipo, data=data or {},
        user=types.SimpleNamespace(id=int(uid), name=u["username"], display_name=u.get("global_name") or u["username"],
                                   roles=[types.SimpleNamespace(id=int(c)) for c in cargos]),
        channel_id=int(canal_id), guild_id=int(GID), guild=types.SimpleNamespace(owner_id=999),
        permissions=types.SimpleNamespace(administrator=admin), message=types.SimpleNamespace(embeds=[]))


def comando(uid, canal_id, nome, cargos=(), admin=True, **opcoes):
    return inter(uid, canal_id, tipo=2, cargos=cargos, admin=admin,
                 data={"name": nome, "type": 1, "options": [{"name": k, "type": 3, "value": v} for k, v in opcoes.items()]})


def texto_resposta():
    """Texto final mostrado para quem usou o comando (resposta imediata ou edição da 'pensando…')."""
    ultimos = [json.dumps(fake.respostas[-1], ensure_ascii=False)]
    if fake.webhooks:
        ultimos.append(json.dumps(fake.webhooks[-1][2], ensure_ascii=False))
    return " ".join(ultimos)


async def main():
    await server.carregar_config(forcar=True)
    fundador, membro_r = cargo("Fundador"), cargo("Membro")
    for nome in ("Suporte", "Moderador"):
        rid = fake_discord.novo_id()
        fake.roles[rid] = {"id": rid, "name": nome, "position": 2, "color": 0, "permissions": "0", "hoist": False,
                           "mentionable": False, "managed": False}
    cat_tickets = novo_canal("🎟️ TICKETS", 4)
    abrir = novo_canal("🎫・abrir-ticket")
    verif = novo_canal("✅・verificação")
    loja = novo_canal("💎・chatgpt-astra")
    estoque = novo_canal("estoque-astra", parent=canal("STAFF")["id"])
    hist = novo_canal("📁・tickets-fechados", parent=canal("STAFF")["id"])
    novo_canal("📊・registro-de-vendas", parent=canal("STAFF")["id"])
    vini, joao = membro("vinicius"), membro("joao123")

    # ── registro dos comandos ──
    await server.registrar_comandos(BOT)
    nomes = [c["name"] for c in fake.comandos]
    ok(nomes[:7] == ["ping", "loja_painel", "vendas", "pedidos_pendentes", "aprovar_pagamento", "ticket_painel", "verificacao_painel"],
       "os 7 comandos do bot antigo são registrados com os mesmos nomes")
    ok(all(c.get("default_member_permissions") == "8" for c in fake.comandos if c["name"] != "ping"),
       "comandos de administração só aparecem para administradores")
    st = await server.status_agente()
    ok(st["comandos_de_barra"].startswith("registrados"), "status mostra que os comandos estão registrados")

    # ── /ping ──
    await server.ao_interagir(comando(joao, abrir, "ping", admin=False))
    ok(fake.respostas[-1]["type"] == 4 and "Pong" in texto_resposta() and fake.respostas[-1]["data"]["flags"] == 64, "/ping responde só para quem usou")

    # ── /ticket_painel sem nada configurado: usa padrões do servidor ──
    await server.ao_interagir(comando(vini, abrir, "ticket_painel"))
    ok(fake.respostas[-1] == {"type": 5, "data": {"flags": 64}}, "/ticket_painel responde 'pensando' na hora")
    painel = fake.messages[abrir][-1]
    ok(painel["components"][0]["components"][0]["custom_id"].startswith("ecot:abrir:"), "/ticket_painel publica o painel no canal")
    p = next(x for x in server._cfg["paineis"].values() if x["tipo"] == "ticket")
    ok(p["categoria_id"] == cat_tickets and p["canal_historico_id"] == hist, "usa a categoria de tickets e o canal de histórico do servidor")
    ok({c["nome"] for c in p["cargos_equipe"]} == {"Suporte", "Moderador", "Fundador"}, "equipe padrão: Suporte, Moderador e Fundador")
    ok("publicado" in texto_resposta(), "confirma a publicação")
    # personaliza pelo Claude e atualiza pelo comando: mantém texto e botão
    await server.publicar_painel_ticket("abrir-ticket", titulo="🎟️ SUPORTE ECO PULSE", descricao="Fale com a equipe!",
                                        botao_texto="Falar com a equipe", botao_emoji="💬", mensagem_id=painel["id"],
                                        categoria="TICKETS", cargos_equipe=["Suporte"], canal_historico="tickets-fechados")
    n_msgs = len(fake.messages[abrir])
    await server.ao_interagir(comando(vini, abrir, "ticket_painel"))
    painel = next(m for m in fake.messages[abrir] if m["id"] == painel["id"])
    ok(len(fake.messages[abrir]) == n_msgs and "atualizado" in texto_resposta(), "/ticket_painel de novo atualiza o mesmo painel")
    ok(painel["embeds"][0]["title"] == "🎟️ SUPORTE ECO PULSE" and painel["components"][0]["components"][0]["label"] == "Falar com a equipe",
       "atualizar mantém título e botão personalizados")

    # ── /verificacao_painel ──
    await server.ao_interagir(comando(vini, verif, "verificacao_painel"))
    pv = fake.messages[verif][-1]
    ok(pv["components"][0]["components"][0]["custom_id"].startswith("ecov:") and "Membro" in texto_resposta(),
       "/verificacao_painel publica dando o cargo Membro por padrão")
    outro = fake_discord.novo_id()
    fake.roles[outro] = {"id": outro, "name": "Verificado", "position": 1, "color": 0, "permissions": "0", "hoist": False,
                         "mentionable": False, "managed": False}
    await server.ao_interagir(inter(vini, verif, tipo=2, admin=True, data={"name": "verificacao_painel", "options": [
        {"name": "cargo", "type": 8, "value": outro}]}))
    ok("Verificado" in texto_resposta() and next(x for x in server._cfg["paineis"].values() if x["tipo"] == "verificacao")["cargo_id"] == outro,
       "opção cargo troca o cargo dado")

    # ── loja: produto, painel, compra completa ──
    await server.ao_interagir(comando(vini, loja, "loja_painel"))
    ok("Nenhum produto cadastrado" in texto_resposta(), "/loja_painel sem produto explica o que fazer")
    await server.configurar_produto("chatgpt-astra", nome="ChatGPT Astra", preco="19,90", canal_estoque="estoque-astra",
                                    cargo_cliente="Cliente")
    fake._msg(estoque, {"content": "conta: astra1@mail.com / senha 123"})
    await server.ao_interagir(comando(vini, loja, "loja_painel"))
    pl = fake.messages[loja][-1]
    ok(pl["components"][0]["components"][0]["custom_id"] == "ecop:comprar:chatgpt-astra" and "19,90" in pl["embeds"][0]["description"],
       "/loja_painel publica o painel do único produto")
    await server.ao_interagir(inter(joao, loja, tipo=4, data={"name": "loja_painel", "options": [
        {"name": "produto", "type": 3, "value": "astra", "focused": True}]}))
    ok(fake.respostas[-1] == {"type": 8, "data": {"choices": [{"name": "ChatGPT Astra", "value": "chatgpt-astra"}]}},
       "autocompletar sugere os produtos")

    await server.ao_interagir(inter(joao, loja, data={"custom_id": "ecop:comprar:chatgpt-astra"}))
    compra_canal, c = next(iter(server._cfg["compras"].items()))
    ok(c["status"] == "aguardando" and compra_canal in fake.channels, "cliente abre a compra")
    await server.ao_interagir(inter(vini, compra_canal, tipo=2, admin=True, data={"name": "pedidos_pendentes"}))
    ok(c["txid"] in texto_resposta() and "aguardando pagamento" in texto_resposta(), "/pedidos_pendentes lista a compra aguardando")
    await server.ao_interagir(inter(joao, compra_canal, tipo=5, data={"custom_id": "ecop:modal_pago", "components": [
        {"type": 1, "components": [{"type": 4, "custom_id": "nome", "value": "João da Silva"}]}]}))
    ok(c["status"] == "analise", "cliente informa que pagou")
    await server.ao_interagir(inter(vini, loja, tipo=4, data={"name": "aprovar_pagamento", "options": [
        {"name": "pedido", "type": 3, "value": "", "focused": True}]}))
    ok(fake.respostas[-1]["data"]["choices"][0]["value"] == c["txid"] and "João da Silva" in fake.respostas[-1]["data"]["choices"][0]["name"],
       "autocompletar do /aprovar_pagamento mostra o pedido com o nome")

    await server.ao_interagir(comando(joao, loja, "aprovar_pagamento", admin=False, pedido=c["txid"]))
    ok("Só quem tem o cargo" in texto_resposta() and c["status"] == "analise", "quem não é Fundador não aprova")
    await server.ao_interagir(comando(vini, loja, "aprovar_pagamento", cargos=[fundador["id"]], pedido="ecop-xxxx"))
    ok("Não achei esse pedido" in texto_resposta(), "código errado avisa")
    await server.ao_interagir(comando(vini, loja, "aprovar_pagamento", cargos=[fundador["id"]], pedido=c["txid"].lower()))
    ok(c["status"] == "entregue", "/aprovar_pagamento entrega o pedido")
    entrega = canal("entrega-joao123")
    ok(entrega["parent_id"] == cat_tickets, f'canal privado de entrega criado: #{entrega["name"]}')
    ow = {o["id"]: o for o in entrega["permission_overwrites"]}
    ok(int(ow[GID]["deny"]) & 1024 and int(ow[joao]["allow"]) & 1024 and int(ow[fundador["id"]]["allow"]) & 1024,
       "canal de entrega: só o comprador (e o Fundador) veem")
    msgs_e = fake.messages[entrega["id"]]
    ok(any("astra1@mail.com" in (m.get("content") or "") for m in msgs_e), "produto é enviado no canal privado")
    ok("<t:" in msgs_e[0]["embeds"][0]["description"] and f"<@{joao}>" in msgs_e[0]["content"], "canal avisa o comprador e quando será apagado")
    dm = fake.messages["9" + joao[1:]]
    ok(not any("astra1@mail.com" in (m.get("content") or "") for m in dm) and entrega["id"] in json.dumps(dm[-1]["embeds"]),
       "DM recebe só o aviso com o link do canal (sem o conteúdo)")
    ok(entrega["id"] in fake.messages[compra_canal][-1]["content"], "chat da compra aponta para o canal de entrega")
    ok(entrega["id"] in fake.messages[canal("registro-de-vendas")["id"]][-1]["content"], "registro de vendas diz onde foi entregue")
    ok(not [m for m in fake.messages[estoque] if "astra1" in (m.get("content") or "")], "item sai do estoque")
    ok(cargo("Cliente")["id"] in fake.members[joao]["roles"], "cliente ganha o cargo de cliente")
    ok("Confirmado por" in texto_resposta(), "Fundador vê a confirmação")

    await server.ao_interagir(comando(vini, loja, "vendas"))
    t = texto_resposta()
    ok("canal privado" in pl["embeds"][0]["description"], "painel explica que a entrega é num canal privado")
    ok("Hoje:** 1 venda(s) • R$ 19,90" in t and "ChatGPT Astra: 1 • R$ 19,90" in t and c["txid"] in t, "/vendas mostra a venda de hoje com valor e produto")
    rv = await server.resumo_vendas()
    ok(rv["desde_o_inicio"] == {"vendas": 1, "total": "R$ 19,90"}, "resumo_vendas (para o Claude) bate com o /vendas")
    await server.ao_interagir(comando(vini, loja, "pedidos_pendentes"))
    ok("Nenhum pedido pendente" in texto_resposta(), "pedido aprovado sai dos pendentes")
    await server.ao_interagir(comando(vini, compra_canal, "aprovar_pagamento", cargos=[fundador["id"]]))
    ok("já foi decidido" in texto_resposta(), "aprovar duas vezes não entrega de novo")

    # fechar o canal de entrega
    await server.ao_interagir(inter(vini, entrega["id"], data={"custom_id": "ecop:fechar_entrega"}))
    ok("Só quem comprou" in texto_resposta(), "outra pessoa não fecha o canal de entrega")
    await server.ao_interagir(inter(joao, entrega["id"], data={"custom_id": "ecop:fechar_entrega"}))
    ok(fake.respostas[-1]["data"]["components"][0]["components"][0]["custom_id"] == "ecop:fechar_entrega_ok", "fechar pede confirmação")
    await server.ao_interagir(inter(joao, entrega["id"], data={"custom_id": "ecop:fechar_entrega_ok"}))
    server._cfg["entregas"][entrega["id"]]["fechar_em"] = (server._agora() - server.timedelta(seconds=1)).isoformat()
    await server.fechar_entregas()
    ok(entrega["id"] not in fake.channels and not server._cfg["entregas"], "comprador fecha o canal de entrega")

    # aviso 1 dia antes e apagar sozinho
    fake._msg(estoque, {"content": "conta: astra2@mail.com / senha 456"})
    await server.ao_interagir(inter(joao, loja, data={"custom_id": "ecop:comprar:chatgpt-astra"}))
    cc2, c2 = next((k, v) for k, v in server._cfg["compras"].items() if v["status"] == "aguardando")
    await server.ao_interagir(comando(vini, cc2, "aprovar_pagamento", cargos=[fundador["id"]]))
    e2_id, e2 = next(iter(server._cfg["entregas"].items()))
    ok(any("astra2@mail.com" in (m.get("content") or "") for m in fake.messages[e2_id]), "aprovar mesmo sem o cliente clicar em 'paguei' entrega")
    e2["criado"] = (server._agora() - server.timedelta(days=6, hours=12)).isoformat()
    e2["fechar_em"] = (server._agora() + server.timedelta(hours=12)).isoformat()
    await server.fechar_entregas()
    ok(e2.get("avisado") and "será apagado" in fake.messages[e2_id][-1]["content"], "avisa 1 dia antes de apagar")
    e2["fechar_em"] = (server._agora() - server.timedelta(seconds=1)).isoformat()
    await server.fechar_entregas()
    ok(e2_id not in fake.channels, "canal de entrega some sozinho no prazo")

    # modo DM
    await server.configurar_produto("chatgpt-astra", entrega="dm")
    fake._msg(estoque, {"content": "conta: astra3@mail.com / senha 789"})
    await server.ao_interagir(inter(joao, loja, data={"custom_id": "ecop:comprar:chatgpt-astra"}))
    cc3, c3 = next((k, v) for k, v in server._cfg["compras"].items() if v["status"] == "aguardando")
    await server.ao_interagir(comando(vini, cc3, "aprovar_pagamento", cargos=[fundador["id"]]))
    ok(any("astra3@mail.com" in (m.get("content") or "") for m in fake.messages["9" + joao[1:]]) and not server._cfg["entregas"],
       'com entrega="dm" o produto vai na DM')
    await server.configurar_produto("chatgpt-astra", entrega="canal")
    loja_info = await server.ver_loja()
    ok("canal privado" in loja_info["produtos"][0]["entrega"], "ver_loja mostra o modo de entrega")

    # comando de outro bot / desconhecido é ignorado
    n = len(fake.respostas)
    await server.ao_interagir(inter(vini, loja, tipo=2, data={"name": "wordle"}))
    ok(len(fake.respostas) == n, "comandos de outros apps são ignorados")

    # memória guarda as vendas
    antes = json.dumps(server._cfg, sort_keys=True)
    server._cfg.clear()
    server._cfg.update(json.loads(json.dumps(server.CONFIG_PADRAO)))
    server._cfg_estado["carregada"] = False
    await server.carregar_config(forcar=True)
    ok(json.dumps(server._cfg, sort_keys=True) == antes and len(server._cfg["vendas"]) == 3, "histórico de vendas sobrevive a reinício")
    print(f"\nCOMANDOS OK — {ok_n} verificações")


asyncio.run(main())
