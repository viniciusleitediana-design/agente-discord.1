"""Arquivo de entrega: o FUNDADOR manda 1 arquivo pelo /entrega_configurar e ele vai junto em toda entrega."""
import asyncio
import json
import os
import shutil
import sqlite3
import sys
import types

RASC = os.path.dirname(os.path.abspath(__file__))
PASTA_DB = os.path.join(RASC, "db_arquivo")
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
CDN = "https://cdn.discordapp.com/attachments"


def ok(cond, msg):
    global ok_n
    if not cond:
        raise AssertionError(msg)
    ok_n += 1
    print("  ✔", msg)


def membro(usuario):
    for k, v in fake.members.items():
        if v["user"]["username"] == usuario:
            return k
    uid = fake_discord.novo_id()
    fake.members[uid] = {"user": {"id": uid, "username": usuario, "global_name": usuario}, "nick": None, "roles": [],
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
    tipos = {"arquivo": 11, "remover_arquivo": 5}
    data = {"name": nome, "type": 1, "options": [{"name": k, "type": tipos.get(k, 3), "value": v} for k, v in op.items()]}
    if resolved:
        data["resolved"] = resolved
    return inter(uid, canal_id, data, tipo=2, cargos=cargos, admin=True)


def modal(custom_id, **campos):
    return {"custom_id": custom_id, "components": [{"type": 1, "components": [{"type": 4, "custom_id": k, "value": v}]}
                                                  for k, v in campos.items()]}


def msgs(cid):
    return fake.messages.get(cid, [])


def webhook():
    return json.dumps(fake.webhooks[-1][2], ensure_ascii=False) if fake.webhooks else ""


def anexo(aid, nome, conteudo, tamanho=None):
    url = f"{CDN}/9/{aid}/{nome}"
    fake.cdn[url] = conteudo
    fake.cdn[url.replace(" ", "%20")] = conteudo
    fake.cdn[str(httpx.URL(url))] = conteudo
    return {"attachments": {aid: {"id": aid, "url": url + "?ex=1", "filename": nome, "size": tamanho or len(conteudo),
                                  "content_type": "application/zip"}}}


async def comprar(cliente, fund, vini):
    server._cliques_menu.clear()
    await server.ao_interagir(inter(cliente, CS2, {"custom_id": "ecvd:menu:cs2", "values": ["1d"]}))
    p = server._q1("SELECT * FROM pedidos WHERE usuario_id = ? ORDER BY criado_em DESC", (cliente,))
    await server.ao_interagir(inter(cliente, p["canal_pagamento_id"], modal(f'ecvd:m_pagador:{p["id"]}', nome="Fulano de Tal"), tipo=5))
    await server.ao_interagir(inter(vini, p["canal_pagamento_id"], modal(f'ecvd:m_aprovar:{p["id"]}', confirmo="CONFIRMO"),
                                    tipo=5, cargos=[fund]))
    return server._pedido(p["id"])


async def main():
    fake.channels[CS2] = {"id": CS2, "name": "🥇・cheat・cs2", "type": 0, "position": 3, "parent_id": None, "permission_overwrites": []}
    logs = fake_discord.novo_id()
    fake.channels[logs] = {"id": logs, "name": "📊・registro-de-vendas", "type": 0, "position": 9, "parent_id": None,
                           "permission_overwrites": []}
    fund = next(r for r in fake.roles.values() if r["name"] == "Fundador")["id"]
    vini, joana = membro("vinicius"), membro("joana")
    await server.carregar_config(forcar=True)
    await server.iniciar_vendas()
    await server.ao_interagir(cmd(vini, logs, "key_adicionar", cargos=[fund], jogo="cs2", plano="1d",
                                  keys="ECO-AAAA-0001 ECO-AAAA-0002 ECO-AAAA-0003 ECO-AAAA-0004"))

    # texto para o jogo todo (plano vazio)
    await server.ao_interagir(inter(vini, logs, modal("ecvd:m_entrega:cs2:*", instrucoes="1. Baixe\n2. Abra", login="", link=""),
                                    tipo=5, cargos=[fund]))

    # ── só FUNDADOR ──
    zip_ = b"PK\x03\x04" + os.urandom(3000)
    pdf = b"%PDF-1.4 " + os.urandom(2000)
    await server.ao_interagir(cmd(joana, logs, "entrega_configurar", jogo="cs2", plano="1d", arquivo="77",
                                  resolved=anexo("77", "painel.zip", zip_)))
    ok("FUNDADOR" in json.dumps(fake.respostas[-1], ensure_ascii=False) and not server._arquivos_entrega("cs2", "1d"),
       "só FUNDADOR configura arquivos")

    # ── grande demais: nada é salvo ──
    res = anexo("78", "grande.zip", b"x", tamanho=11 * 1024 * 1024)
    res["attachments"].update(anexo("781", "ok.pdf", pdf)["attachments"])
    await server.ao_interagir(cmd(vini, logs, "entrega_configurar", cargos=[fund], jogo="cs2", plano="1d", arquivo="78", arquivo2="781",
                                  resolved=res))
    ok("máximo 10,0 MB" in webhook() and "grande.zip" in webhook() and "Nada foi salvo" in webhook()
       and not server._arquivos_entrega("cs2", "1d"), "se um arquivo passa do limite, nenhum é salvo e sugere link de download")

    # ── 2 arquivos de uma vez ──
    res = anexo("79", "Painel ECO (v2).zip", zip_)
    res["attachments"].update(anexo("791", "Guia de instalação.pdf", pdf)["attachments"])
    n_respostas = len(fake.respostas)
    await server.ao_interagir(cmd(vini, logs, "entrega_configurar", cargos=[fund], jogo="cs2", plano="1d", arquivo="79", arquivo2="791",
                                  resolved=res))
    ok(fake.respostas[n_respostas]["type"] == 5, "com arquivo, o comando não abre o formulário (responde depois)")
    lista = server._arquivos_entrega("cs2", "1d")
    guarda = next(c for c in fake.channels.values() if c.get("name") == "📁・arquivos-entrega")
    ow = {o["id"]: o for o in guarda["permission_overwrites"]}
    ok([x["nome"] for x in lista] == ["Painel_ECO_v2.zip", "Guia_de_instalacao.pdf"] and lista[0]["tamanho"] == len(zip_)
       and int(ow[GID]["deny"]) & server.VER and fund in ow and len(msgs(guarda["id"])) == 2,
       "2 arquivos guardados (1 mensagem cada) no canal privado 📁・arquivos-entrega")
    ok("**2** arquivo(s)" in webhook() and "Painel_ECO_v2.zip" in webhook() and "Guia_de_instalacao.pdf" in webhook(),
       "resposta lista os 2 arquivos")
    ok(server._config_entrega("cs2", "1d")["instrucoes"] == "1. Baixe\n2. Abra",
       "o plano com arquivos continua herdando o passo a passo do jogo todo")

    # ── entrega leva os 2 ──
    cliente = membro("cliente1")
    p = await comprar(cliente, fund, vini)
    me = msgs(p["canal_entrega_id"])
    ok(p["status"] == "ENTREGUE", "pedido entregue")
    ordem = [("arquivo" if m.get("attachments") else m["embeds"][0]["title"] if m.get("embeds") else "key") for m in me]
    ok(ordem == ["✅ Pagamento aprovado", "📖 Passo a passo", "arquivo", "arquivo", "key"],
       f"ordem: resumo → passo a passo → 2 arquivos → key ({ordem})")
    arqs = [m for m in me if m.get("attachments")]
    ok([a["attachments"][0]["filename"] for a in arqs] == ["Painel_ECO_v2.zip", "Guia_de_instalacao.pdf"]
       and fake.cdn[arqs[0]["attachments"][0]["url"].split("?")[0]] == zip_ and fake.cdn[arqs[1]["attachments"][0]["url"].split("?")[0]] == pdf
       and arqs[1]["content"] == "📎 **Guia_de_instalacao.pdf**", "os 2 arquivos chegam inteiros, com nome, no canal de entrega")
    ok("O passo a passo, os arquivos e a key estão logo abaixo" in me[0]["embeds"][0]["description"], "resumo avisa que os arquivos estão abaixo")
    ok(me[-1].get("components") and me[-1]["content"].startswith("Key: "), "botão de fechar continua na key (última mensagem)")
    ok(server._arquivos_entrega("cs2", "7d") == [], "arquivos de um plano não vão para os outros")

    # ── mandar de novo: adiciona; mesmo nome: substitui ──
    pdf2 = b"%PDF-1.4 nova versao"
    await server.ao_interagir(cmd(vini, logs, "entrega_configurar", cargos=[fund], jogo="cs2", plano="1d", arquivo="792",
                                  resolved=anexo("792", "Guia de instalação.pdf", pdf2)))
    lista = server._arquivos_entrega("cs2", "1d")
    ok(len(lista) == 2 and lista[1]["tamanho"] == len(pdf2) and "Substituído" in webhook(), "arquivo com o mesmo nome substitui o antigo")
    await server.ao_interagir(cmd(vini, logs, "entrega_configurar", cargos=[fund], jogo="cs2", plano="1d", arquivo="793",
                                  resolved=anexo("793", "leia-me.txt", b"ola")))
    ok([x["nome"] for x in server._arquivos_entrega("cs2", "1d")][-1] == "leia-me.txt" and len(server._arquivos_entrega("cs2", "1d")) == 3,
       "arquivo novo é adicionado à lista")
    res = {"attachments": {}}
    for i in range(3):
        res["attachments"].update(anexo(f"80{i}", f"extra{i}.txt", b"x")["attachments"])
    await server.ao_interagir(cmd(vini, logs, "entrega_configurar", cargos=[fund], jogo="cs2", plano="1d", arquivo="800", arquivo2="801",
                                  arquivo3="802", resolved=res))
    ok("até 5 arquivos" in webhook() and len(server._arquivos_entrega("cs2", "1d")) == 3, "limite de 5 arquivos por jogo/plano")
    await server.ao_interagir(cmd(vini, logs, "entrega_configurar", cargos=[fund], jogo="cs2", plano="1d", arquivo="800",
                                  remover_arquivo=True, resolved=res))
    ok([x["nome"] for x in server._arquivos_entrega("cs2", "1d")] == ["extra0.txt"], "remover_arquivo + arquivo troca a lista inteira")

    # ── arquivo apagado do canal: entrega sai mesmo assim e a equipe é avisada ──
    fake.messages[guarda["id"]] = []
    cliente2 = membro("cliente2")
    p2 = await comprar(cliente2, fund, vini)
    me2 = msgs(p2["canal_entrega_id"])
    ok(p2["status"] == "ENTREGUE" and not any(m.get("attachments") for m in me2) and me2[-1]["content"].startswith("Key: ECO-"),
       "sem o arquivo guardado, a key é entregue normalmente")
    ok(any("Arquivo de entrega não foi" in m["content"] and "extra0.txt" in m["content"] for m in msgs(logs)),
       "a equipe é avisada de qual arquivo não foi")

    # ── remover todos ──
    await server.ao_interagir(cmd(vini, logs, "entrega_configurar", cargos=[fund], jogo="cs2", plano="1d", remover_arquivo=True))
    ok("1 arquivo(s) tirado(s)" in webhook() and server._arquivos_entrega("cs2", "1d") == []
       and server._config_entrega("cs2", "1d")["instrucoes"], "remover_arquivo tira os arquivos e mantém o resto")

    # ── arquivos do jogo todo + do plano ──
    await server.ao_interagir(cmd(vini, logs, "entrega_configurar", cargos=[fund], jogo="cs2", arquivo="81",
                                  resolved=anexo("81", "guia.pdf", b"%PDF-1.4 geral")))
    await server.ao_interagir(cmd(vini, logs, "entrega_configurar", cargos=[fund], jogo="cs2", plano="30d", arquivo="82",
                                  resolved=anexo("82", "bonus.zip", b"PK bonus")))
    ok("todos os planos** deste jogo também vão" in webhook(), "resposta avisa que os do jogo todo também vão")
    ok([x["nome"] for x in server._arquivos_entrega("cs2", "30d")] == ["guia.pdf", "bonus.zip"]
       and [x["nome"] for x in server._arquivos_entrega("cs2", "7d")] == ["guia.pdf"],
       "o arquivo de todos os planos vai em todos; o do plano só nele")

    # ── vários links de download (para arquivos grandes demais para o Discord) ──
    await server.ao_interagir(inter(vini, logs, modal("ecvd:m_entrega:cs2:7d", instrucoes="Siga o vídeo", login="",
                                                      link="Programa: https://drive.google.com/abc\n\n  Vídeo tutorial: https://youtu.be/xyz  "),
                                    tipo=5, cargos=[fund]))
    ok(server._config_entrega("cs2", "7d")["link_download"] == "Programa: https://drive.google.com/abc\nVídeo tutorial: https://youtu.be/xyz",
       "aceita vários links, um por linha (linhas vazias e espaços somem)")
    await server.ao_interagir(inter(vini, logs, modal("ecvd:m_entrega:cs2:15d", instrucoes="", login="", link="Programa: drive"),
                                    tipo=5, cargos=[fund]))
    ok("Linha sem link" in (webhook() + json.dumps(fake.respostas[-1], ensure_ascii=False)) and server._config_entrega("cs2", "15d")["instrucoes"] == "1. Baixe\n2. Abra",
       "linha sem https:// é recusada e nada muda")
    await server.ao_interagir(cmd(vini, logs, "key_adicionar", cargos=[fund], jogo="cs2", plano="7d", keys="ECO-BBBB-0001"))
    server._cliques_menu.clear()
    c7 = membro("cliente7")
    await server.ao_interagir(inter(c7, CS2, {"custom_id": "ecvd:menu:cs2", "values": ["7d"]}))
    p7 = server._q1("SELECT * FROM pedidos WHERE usuario_id = ?", (c7,))
    await server.ao_interagir(inter(c7, p7["canal_pagamento_id"], modal(f'ecvd:m_pagador:{p7["id"]}', nome="Fulano de Tal"), tipo=5))
    await server.ao_interagir(inter(vini, p7["canal_pagamento_id"], modal(f'ecvd:m_aprovar:{p7["id"]}', confirmo="CONFIRMO"), tipo=5, cargos=[fund]))
    passo = next(m for m in msgs(server._pedido(p7["id"])["canal_entrega_id"]) if m.get("embeds") and m["embeds"][0]["title"] == "📖 Passo a passo")
    ok("⬇️ **Downloads**\n• Programa: https://drive.google.com/abc\n• Vídeo tutorial: https://youtu.be/xyz" in passo["embeds"][0]["description"],
       "na entrega, os links aparecem em lista no passo a passo")

    # ── banco da versão 4.0 (1 arquivo por plano em entregas_config) é convertido ──
    velho = os.path.join(PASTA_DB, "velho.db")
    c = sqlite3.connect(velho)
    c.execute("CREATE TABLE entregas_config (jogo TEXT NOT NULL, plano TEXT NOT NULL, instrucoes TEXT, login_cifrado TEXT, "
              "link_download TEXT, atualizado_por TEXT, atualizado_em TEXT, arquivo_canal TEXT, arquivo_msg TEXT, arquivo_nome TEXT, "
              "arquivo_tamanho INTEGER, PRIMARY KEY (jogo, plano))")
    c.execute("INSERT INTO entregas_config VALUES ('cs2', '1d', 'antigo', NULL, NULL, '1', '2026-10-30T10:00:00', '55', '66', 'a.zip', 9)")
    c.commit(); c.close()
    novo = server._abrir_db(velho)
    mig = [dict(r) for r in novo.execute("SELECT * FROM entregas_arquivos")]
    ok(len(mig) == 1 and mig[0]["nome"] == "a.zip" and mig[0]["mensagem_id"] == "66"
       and novo.execute("SELECT arquivo_msg, instrucoes FROM entregas_config").fetchone()[:] == (None, "antigo"),
       "arquivo da versão anterior passa para a lista nova sem perder nada")
    novo.close()
    novo = server._abrir_db(velho)
    ok(novo.execute("SELECT COUNT(*) FROM entregas_arquivos").fetchone()[0] == 1, "abrir de novo não duplica")
    novo.close()
    print(f"\nARQUIVO OK — {ok_n} verificações")


asyncio.run(main())
