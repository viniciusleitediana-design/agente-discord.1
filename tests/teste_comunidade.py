"""Testa tickets, verificação, sorteios, cópia de painéis e imagens contra um Discord simulado."""
import asyncio
import json
import os
import re
import sys
import types
from datetime import timedelta

os.environ.update(DISCORD_TOKEN="token-falso", GUILD_ID="111111111111111111", CHAVE_SECRETA="x")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import httpx2 as httpx

import fake_discord
from suporte import bot as server

GID, BOT = fake_discord.GID, fake_discord.BOT
OLD_BOT = "333333333333333333"
CDN = "https://cdn.discordapp.com/attachments"
IMG = b"\x89PNG\r\n\x1a\nimagem-falsa"


class Fake2(fake_discord.Fake):
    def __init__(self):
        super().__init__()
        self.respostas = []     # callbacks de interação
        self.webhooks = []      # edições/seguimentos
        self.cdn = {}           # url sem query -> bytes

    def handler(self, req):
        url = str(req.url)
        if url.startswith("https://cdn.discordapp.com/"):
            base = url.split("?")[0]
            if base in self.cdn:
                return httpx.Response(200, content=self.cdn[base])
            return httpx.Response(404, content=b"This content is no longer available.")
        return super().handler(req)

    def _multipart(self, req):
        boundary = req.headers["content-type"].split("boundary=")[1].encode()
        payload, arquivos = {}, {}
        for parte in req.content.split(b"--" + boundary):
            if b"\r\n\r\n" not in parte:
                continue
            cab, corpo = parte.split(b"\r\n\r\n", 1)
            corpo = corpo.rsplit(b"\r\n", 1)[0]
            m = re.search(rb'name="([^"]+)"', cab)
            if not m:
                continue
            nome = m.group(1).decode()
            if nome == "payload_json":
                payload = json.loads(corpo)
            elif nome.startswith("files["):
                fn = re.search(rb'filename="([^"]+)"', cab).group(1).decode()
                arquivos[int(nome[6:-1])] = (fn, corpo)
        payload["_arquivos"] = arquivos
        return payload

    def _resolver_anexos(self, msg):
        por_nome = {a["filename"]: a["url"] for a in msg["attachments"]}
        for e in msg.get("embeds", []):
            for k in ("image", "thumbnail"):
                u = (e.get(k) or {}).get("url", "")
                if u.startswith("attachment://"):
                    nome = u[len("attachment://"):]
                    assert nome in por_nome, f"attachment://{nome} sem anexo correspondente"
                    e[k] = {"url": por_nome[nome] + "?ex=abc&is=def&hm=123"}

    def _anexar(self, cid, mid, body, existentes=None):
        anexos = list(existentes or [])
        for idx, (fn, dados) in sorted((body.get("_arquivos") or {}).items()):
            url = f"{CDN}/{cid}/{mid}/{fn}"
            self.cdn[url] = dados
            anexos.append({"id": fake_discord.novo_id(), "filename": fn, "url": url + "?ex=abc", "content_type": "image/png"})
        return anexos

    def _msg(self, cid, body):
        mid = fake_discord.novo_id()
        msg = {"id": mid, "channel_id": cid, "author": {"id": BOT, "username": "EcoBot", "bot": True},
               "content": body.get("content", ""), "embeds": json.loads(json.dumps(body.get("embeds", []))),
               "components": body.get("components", []), "attachments": [], "timestamp": "2026-10-29T21:00:00+00:00",
               "pinned": False}
        if body.get("_arquivo") is not None:   # formato antigo (memória)
            body = {**body, "_arquivos": {0: ("agente-config.json", body["_arquivo"])}}
        if body.get("_arquivos"):
            msg["attachments"] = self._anexar(cid, mid, body)
            for a in msg["attachments"]:
                if a["filename"] == "agente-config.json":
                    self.files[a["url"]] = self.cdn[a["url"].split("?")[0]]
        if "message_reference" in body:
            msg["message_reference"] = body["message_reference"]
        self._resolver_anexos(msg)
        self.messages.setdefault(cid, []).append(msg)
        return msg

    def rota(self, m, p, body, req):
        J = lambda d, s=200: httpx.Response(s, json=d)
        if p.startswith("/interactions/"):
            self.respostas.append(body)
            return httpx.Response(204)
        if p.startswith("/webhooks/"):
            self.webhooks.append((m, p, body))
            return J({"id": fake_discord.novo_id()})
        if p == "/attachments/refresh-urls":
            return J({"refreshed_urls": [{"original": u, "refreshed": u.split("?")[0] + "?ex=novo"} for u in body["attachment_urls"]]})
        mm = re.fullmatch(r"/channels/(\d+)/messages/(\d+)", p)
        if mm and m == "PATCH":
            msg = next((x for x in self.messages.get(mm[1], []) if x["id"] == mm[2]), None)
            if msg is None:
                return J({"message": "Unknown Message", "code": 10008}, 404)
            if msg["author"]["id"] != BOT:
                return J({"message": "Cannot edit a message authored by another user", "code": 50005}, 403)
            if "attachments" in body:
                manter = {str(a["id"]) for a in body["attachments"] if "filename" not in a}
                existentes = [a for a in msg["attachments"] if a["id"] in manter]
                msg["attachments"] = self._anexar(mm[1], mm[2], body, existentes)
            for k in ("content", "embeds", "components"):
                if k in body:
                    msg[k] = json.loads(json.dumps(body[k]))
            self._resolver_anexos(msg)
            return J(msg)
        if mm and m == "GET":
            msg = next((x for x in self.messages.get(mm[1], []) if x["id"] == mm[2]), None)
            if msg is None:
                return J({"message": "Unknown Message", "code": 10008}, 404)
            return J(msg)
        return super().rota(m, p, body, req)


fake = Fake2()
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


def msg_antiga(cid, embed, componentes, anexo=None):
    mid = fake_discord.novo_id()
    msg = {"id": mid, "channel_id": cid, "author": {"id": OLD_BOT, "username": "ECO PULSE BOT", "bot": True},
           "content": "", "embeds": [embed], "components": componentes, "attachments": [],
           "timestamp": "2026-10-24T15:00:00+00:00", "pinned": False}
    if anexo:
        url = f"{CDN}/{cid}/{mid}/{anexo}"
        fake.cdn[url] = IMG
        msg["attachments"] = [{"id": fake_discord.novo_id(), "filename": anexo, "url": url + "?ex=velho", "content_type": "image/jpeg"}]
    fake.messages.setdefault(cid, []).append(msg)
    return f"https://discord.com/channels/{GID}/{cid}/{mid}"


class Embed:
    def __init__(self, d):
        self.d = d

    def to_dict(self):
        return json.loads(json.dumps(self.d))


def inter(uid, custom_id, canal_id, cargos=(), admin=False, values=None, tipo=3, msg=None):
    u = fake.members[uid]["user"]
    data = {"custom_id": custom_id}
    if values is not None:
        data["values"] = values
    mensagem = types.SimpleNamespace(embeds=[Embed(e) for e in (msg or {}).get("embeds", [])], id=(msg or {}).get("id"))
    return types.SimpleNamespace(
        id=fake_discord.novo_id(), token="tok", application_id=BOT, type=tipo, data=data,
        user=types.SimpleNamespace(id=int(uid), name=u["username"], display_name=u.get("global_name") or u["username"],
                                   roles=[types.SimpleNamespace(id=int(c)) for c in cargos]),
        channel_id=int(canal_id), guild_id=int(GID), guild=types.SimpleNamespace(owner_id=999),
        permissions=types.SimpleNamespace(administrator=admin), message=mensagem)


def ultima_resposta():
    return fake.respostas[-1]


def ultimo_webhook_texto():
    return json.dumps(fake.webhooks[-1][2], ensure_ascii=False)


async def main():
    await server.carregar_config(forcar=True)
    ok(server._cfg_estado["carregada"], "memória carregada")
    suporte, moderador, membro_r = cargo("Fundador"), cargo("Cliente"), cargo("Membro")
    # cargos de exemplo do servidor real
    for nome in ("Suporte", "Moderador"):
        rid = fake_discord.novo_id()
        fake.roles[rid] = {"id": rid, "name": nome, "position": 2, "color": 0, "permissions": "0", "hoist": False, "mentionable": False, "managed": False}
    suporte = cargo("Suporte")
    staff = cargo("STAFF (PRIVADO)") if False else None
    cat_tickets = novo_canal("🎟️ TICKETS", 4)
    abrir = novo_canal("🎫・abrir-ticket")
    verif = novo_canal("✅・verificação")
    sorteios = novo_canal("🎉・sorteios")
    historico = novo_canal("📁・tickets-fechados", parent=canal("STAFF")["id"])

    link_ticket = msg_antiga(abrir, {
        "title": "🎟️ SUPORTE ECO PULSE", "description": "Precisa de ajuda? Abra um ticket!", "color": 0x22C55E,
        "image": {"url": f"{CDN}/{abrir}/1/banner.png?ex=velho", "proxy_url": "https://media...", "width": 800, "height": 200},
        "footer": {"text": "ECO PULSE • Suporte"}, "type": "rich"},
        [{"type": 1, "components": [{"type": 2, "style": 1, "label": "Abrir Ticket", "custom_id": "old:ticket", "emoji": {"name": "🎫"}}]}])
    fake.cdn[f"{CDN}/{abrir}/1/banner.png"] = IMG
    link_verif = msg_antiga(verif, {"title": "🔐 VERIFICAÇÃO ECO PULSE", "description": "Clique para se verificar.", "color": 0x3B82F6},
                            [{"type": 1, "components": [{"type": 2, "style": 3, "label": "Verificar", "custom_id": "old:verify"}]}])
    link_sorteio = msg_antiga(sorteios, {"title": "🎉 SORTEIO ECO PULSE • ECO CHEATS", "description": "Concorra a uma key!", "color": 0x8B5CF6},
                              [{"type": 1, "components": [{"type": 2, "style": 1, "label": "Participar", "custom_id": "old:join"}]}],
                              anexo="eco-cheats-sorteio.jpeg")

    # ── ver_mensagem ──
    v = await server.ver_mensagem(link_ticket)
    ok(v["embeds"][0]["title"] == "🎟️ SUPORTE ECO PULSE" and v["embeds"][0]["cor_hex"] == "#22c55e", "ver_mensagem mostra o embed completo")
    ok(v["botoes_e_menus"][0] == {"tipo": "botão", "texto": "Abrir Ticket", "emoji": "🎫", "cor": "azul", "custom_id": "old:ticket"}, "ver_mensagem mostra os botões")
    ok("outro bot" in v.get("obs", ""), "avisa que os botões são de outro bot")
    v2 = await server.ver_mensagem(link_ticket.rsplit("/", 1)[-1], canal_id="abrir-ticket")
    ok(v2["id"] == v["id"], "ver_mensagem aceita ID + canal")
    info = await server.info_canal("abrir-ticket")
    ok(info["permissoes"] == "segue a categoria/servidor", "info_canal sem regras")

    # ── painel de ticket copiando o antigo ──
    res = await server.publicar_painel_ticket("abrir-ticket", copiar_de=link_ticket, categoria="TICKETS",
                                              cargos_equipe=["Suporte"], canal_historico="tickets-fechados",
                                              motivos=["Dúvida", "Compra", "Problema com key"], botao_texto="Escolha o assunto")
    painel = fake.messages[abrir][-1]
    ok(painel["author"]["id"] == BOT and painel["embeds"][0]["title"] == "🎟️ SUPORTE ECO PULSE", "painel novo copia o título do antigo")
    ok(painel["embeds"][0]["footer"]["text"] == "ECO PULSE • Suporte" and painel["embeds"][0]["color"] == 0x22C55E, "copia rodapé e cor")
    img = painel["embeds"][0]["image"]["url"]
    ok(img.startswith(f"{CDN}/{abrir}/{painel['id']}/") and painel["attachments"], "imagem do painel antigo foi reenviada (não depende do link velho)")
    menu = painel["components"][0]["components"][0]
    ok(menu["type"] == 3 and [o["label"] for o in menu["options"]] == ["Dúvida", "Compra", "Problema com key"], "motivos viram menu")
    pid = res["painel_id"]

    joao, joana, vini = membro("joao123"), membro("joana"), membro("vinicius")
    # abrir ticket escolhendo "Compra"
    await server.ao_interagir(inter(joao, f"ecot:abrir:{pid}", abrir, values=["1"]))
    ok(fake.respostas[-1] == {"type": 5, "data": {"flags": 64}}, "abrir ticket responde 'pensando' na hora")
    ticket = canal("ticket-joao123")
    ok(ticket["parent_id"] == cat_tickets, f'ticket criado na categoria TICKETS: #{ticket["name"]}')
    ow = {o["id"]: o for o in ticket["permission_overwrites"]}
    ok(int(ow[GID]["deny"]) & 1024 and int(ow[joao]["allow"]) & 1024 and int(ow[suporte["id"]]["allow"]) & 1024,
       "ticket: escondido de todos, visível para o dono e a equipe")
    boas = fake.messages[ticket["id"]][0]
    ok(f"<@{joao}>" in boas["content"] and f'<@&{suporte["id"]}>' in boas["content"] and "Compra" in boas["embeds"][0]["description"],
       "mensagem do ticket marca o dono, a equipe e mostra o assunto")
    ok(ticket["id"] in ultimo_webhook_texto(), "pessoa recebe o link do ticket")
    t = server._cfg["tickets"][ticket["id"]]
    ok(t["motivo"] == "Compra" and t["numero"] == 1, "ticket salvo na memória com assunto e número")

    await server.ao_interagir(inter(joao, f"ecot:abrir:{pid}", abrir, values=["0"]))
    ok("já tem um ticket aberto" in ultimo_webhook_texto(), "não deixa abrir dois tickets")

    # assumir
    await server.ao_interagir(inter(joana, "ecot:assumir", ticket["id"], msg=boas))
    ok("Só a equipe" in json.dumps(ultima_resposta(), ensure_ascii=False), "membro comum não assume ticket")
    await server.ao_interagir(inter(vini, "ecot:assumir", ticket["id"], cargos=[suporte["id"]], msg=boas))
    ok(ultima_resposta()["type"] == 7 and len(ultima_resposta()["data"]["components"][0]["components"]) == 1, "equipe assume: botão Assumir some")
    ok("assumiu o seu atendimento" in fake.messages[ticket["id"]][-1]["content"], "avisa no ticket quem assumiu")

    # alguém escreve e depois fecha
    fake._msg(ticket["id"], {"content": "quero comprar a key mensal"})
    await server.ao_interagir(inter(joana, "ecot:fechar", ticket["id"]))
    ok("Só quem abriu" in json.dumps(ultima_resposta(), ensure_ascii=False), "estranho não fecha ticket")
    await server.ao_interagir(inter(joao, "ecot:fechar", ticket["id"]))
    ok(ultima_resposta()["data"]["components"][0]["components"][0]["custom_id"] == "ecot:confirmar", "fechar pede confirmação")
    n_hist = len(fake.messages.get(historico, []))
    await server.ao_interagir(inter(joao, "ecot:confirmar", ticket["id"]))
    ok(ticket["id"] not in fake.channels, "ticket apagado depois de confirmar")
    h = fake.messages[historico][-1]
    ok(len(fake.messages[historico]) == n_hist + 1 and h["attachments"][0]["filename"].startswith("ticket-0001"), "histórico .txt enviado ao canal da equipe")
    txt = fake.cdn[h["attachments"][0]["url"].split("?")[0]].decode()
    ok("quero comprar a key mensal" in txt and "Atendido por" in h["embeds"][0]["description"], "histórico tem a conversa e o resumo")
    dm = fake.messages["9" + joao[1:]][-1]
    ok(dm["attachments"] and "fechado" in dm["embeds"][0]["title"], "dono recebe aviso + histórico na DM")
    ok(not server._cfg["tickets"], "ticket some da memória")

    # fechar_ticket pela ferramenta
    await server.ao_interagir(inter(joana, f"ecot:abrir:{pid}", abrir, values=["2"]))
    t2 = canal("ticket-joana")
    r = await server.fechar_ticket(t2["name"])
    ok("Nada foi fechado" in r and t2["id"] in fake.channels, "fechar_ticket pede confirmação")
    r = await server.fechar_ticket(t2["name"], confirmado=True)
    ok(t2["id"] not in fake.channels, "fechar_ticket com confirmação fecha")

    # ── verificação ──
    res = await server.publicar_painel_verificacao("verificação", cargo="Membro", copiar_de=link_verif)
    pv = fake.messages[verif][-1]
    ok(pv["embeds"][0]["title"] == "🔐 VERIFICAÇÃO ECO PULSE" and pv["components"][0]["components"][0]["custom_id"] == f'ecov:{res["painel_id"]}',
       "painel de verificação copiado com botão novo")
    await server.ao_interagir(inter(joana, f'ecov:{res["painel_id"]}', verif))
    ok(membro_r["id"] in fake.members[joana]["roles"] and "Verificado" in ultimo_webhook_texto(), "clicar dá o cargo Membro")
    await server.ao_interagir(inter(joana, f'ecov:{res["painel_id"]}', verif, cargos=[membro_r["id"]]))
    ok("já está verificado" in ultimo_webhook_texto(), "quem já tem o cargo é avisado")
    try:
        await server.publicar_painel_verificacao("verificação", cargo="Membro", mensagem_id=link_verif.rsplit("/", 1)[-1])
        ok(False, "editar mensagem de outro bot deveria falhar")
    except server.ErroDiscord as e:
        ok("outro usuário ou bot" in str(e), "editar painel de outro bot dá erro claro")

    # ── sorteio ──
    res = await server.criar_sorteio("sorteios", premio="Key 30 dias", termina="daqui a 2 dias", vencedores=1, copiar_de=link_sorteio)
    sid = res["sorteio_id"]
    ms = fake.messages[sorteios][-1]
    s = server._cfg["sorteios"][sid]
    ok(ms["embeds"][0]["title"] == "🎉 SORTEIO ECO PULSE • ECO CHEATS" and "Concorra a uma key!" in ms["embeds"][0]["description"],
       "sorteio copia título e texto do antigo")
    ok(ms["attachments"] and s.get("image_arquivo") == ms["attachments"][0]["filename"], "imagem anexada do sorteio antigo vira imagem do embed")
    ok("<t:" in ms["embeds"][0]["description"], "mostra contagem regressiva do Discord")
    for u in (joao, joana, vini):
        await server.ao_interagir(inter(u, f"ecos:entrar:{sid}", sorteios))
    ok(len(s["participantes"]) == 3 and "participando" in json.dumps(ultima_resposta(), ensure_ascii=False), "3 pessoas entram no sorteio")
    await server.ao_interagir(inter(joana, f"ecos:entrar:{sid}", sorteios))
    ok(ultima_resposta()["data"]["components"][0]["components"][0]["custom_id"] == f"ecos:sair:{sid}", "clicar de novo oferece sair")
    await server.ao_interagir(inter(joana, f"ecos:sair:{sid}", sorteios))
    ok(joana not in s["participantes"], "sair do sorteio funciona")
    await asyncio.sleep(3.5)
    ms = next(x for x in fake.messages[sorteios] if x["id"] == s["mensagem_id"])
    ok("**Participantes:** 2" in ms["embeds"][0]["description"], "contador de participantes atualiza na mensagem")
    ok(ms["attachments"] and ms["embeds"][0]["image"]["url"].startswith(CDN), "imagem continua depois de editar")
    # vini sai do servidor: não pode ganhar
    del fake.members[vini]
    res = await server.encerrar_sorteio(sid)
    ok(res["ganhadores"] == [f"<@{joao}>"], "ganhador sorteado só entre quem ainda está no servidor")
    anuncio = fake.messages[sorteios][-1]
    ok(f"<@{joao}>" in anuncio["content"] and anuncio["message_reference"]["message_id"] == s["mensagem_id"], "anuncia o ganhador respondendo o sorteio")
    ms = next(x for x in fake.messages[sorteios] if x["id"] == s["mensagem_id"])
    ok(ms["components"][0]["components"][0].get("disabled") and "Ganhador" in ms["embeds"][0]["description"], "mensagem vira 'encerrado' com botão desligado")
    res = await server.sortear_de_novo(sid)
    ok(res["novos_ganhadores"] == "não sobrou ninguém para sortear", "ressortear sem candidatos avisa")
    await server.ao_interagir(inter(joana, f"ecos:entrar:{sid}", sorteios))
    ok("encerrado" in json.dumps(ultima_resposta(), ensure_ascii=False), "não entra em sorteio encerrado")

    # fim automático
    res = await server.criar_sorteio("sorteios", premio="VIP", termina="daqui a 5 min", cargo_obrigatorio="Membro")
    s2 = server._cfg["sorteios"][res["sorteio_id"]]
    await server.ao_interagir(inter(joao, f'ecos:entrar:{s2["id"]}', sorteios))
    ok(joao not in s2["participantes"] and "precisa ter o cargo" in json.dumps(ultima_resposta(), ensure_ascii=False), "requisito de cargo funciona")
    await server.ao_interagir(inter(joana, f'ecos:entrar:{s2["id"]}', sorteios, cargos=[membro_r["id"]]))
    s2["fim"] = (server._agora() - timedelta(seconds=1)).isoformat()
    await server.rodar_sorteios()
    ok(s2["status"] == "encerrado" and s2["ganhadores"] == [joana], "sorteio encerra sozinho na hora marcada")

    # ── boas-vindas com imagem de anexo ──
    fake.cdn[f"{CDN}/{verif}/9/bemvindo.png"] = IMG
    await server.configurar_boas_vindas(canal_id="verificação", titulo="💚 BEM-VINDO AO ECO PULSE!", texto="{usuario}",
                                        imagem_url=f"{CDN}/{verif}/9/bemvindo.png?ex=velho")
    guardada = server._cfg["boas_vindas"]["imagem_url"]
    ok(guardada.startswith(f'{CDN}/{server._cfg_estado["canal_id"]}/'),
       "imagem de boas-vindas guardada no canal de memória")
    del fake.cdn[f"{CDN}/{verif}/9/bemvindo.png"]   # original apagado
    await server.ao_entrar(joana, "Joana", "ECO PULSE", 10, False)
    bv = fake.messages[verif][-1]
    ok(bv["attachments"] and bv["embeds"][0]["image"]["url"].startswith(CDN) and f"<@{joana}>" in bv["content"],
       "boas-vindas sai com a imagem mesmo depois do original apagado")

    # ── listagens, remoção, memória ──
    auto = await server.listar_automacoes()
    ok(len(auto["paineis"]) == 2 and len(auto["sorteios"]) == 2 and auto["tickets_abertos"] == [], "listar_automacoes mostra painéis e sorteios")
    st = await server.status_agente()
    ok(st["comunidade"] == {"paineis_ticket": 1, "tickets_abertos": 0, "paineis_verificacao": 1, "sorteios_ativos": 0}, "status_agente conta a comunidade")
    antes = json.dumps(server._cfg, sort_keys=True)
    server._cfg.clear()
    server._cfg.update(json.loads(json.dumps(server.CONFIG_PADRAO)))
    server._cfg_estado["carregada"] = False
    await server.carregar_config(forcar=True)
    ok(json.dumps(server._cfg, sort_keys=True) == antes, "painéis, tickets e sorteios sobrevivem a reinício")
    r = await server.remover_automacao(pid)
    ok("desligado" in r and pid not in server._cfg["paineis"], "remover painel de ticket")
    await server.ao_interagir(inter(joao, f"ecot:abrir:{pid}", abrir, values=["0"]))
    ok("não está mais ativo" in ultimo_webhook_texto(), "botão de painel removido avisa")

    # loja continua respondendo
    await server.ao_interagir(inter(joao, "ecop:pago", abrir))
    ok("encerrada" in json.dumps(ultima_resposta(), ensure_ascii=False), "botões da loja continuam funcionando")
    # botões de outros bots são ignorados
    n = len(fake.respostas)
    await server.ao_interagir(inter(joao, "old:ticket", abrir))
    ok(len(fake.respostas) == n, "cliques de outros bots são ignorados")

    print(f"\nCOMUNIDADE OK — {ok_n} verificações")


asyncio.run(main())
