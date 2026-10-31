"""Organização do servidor: posições sem repetição, canal de regras da Comunidade e painéis via enviar_mensagem."""
import asyncio
import os
import sys

os.environ.update(DISCORD_TOKEN="token-falso", GUILD_ID="111111111111111111", CHAVE_SECRETA="x")
RASC = os.path.dirname(os.path.abspath(__file__))
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


def ok(cond, msg):
    global ok_n
    if not cond:
        raise AssertionError(msg)
    ok_n += 1
    print("✔", msg)


def novo(nome, tipo=0, pai=None, pos=0):
    cid = fake_discord.novo_id()
    fake.channels[cid] = {"id": cid, "name": nome, "type": tipo, "position": pos, "parent_id": pai, "permission_overwrites": []}
    return cid


def ordem(tipo_cat=False, pai=None, voz=False):
    cs = [c for c in fake.channels.values() if c["type"] != 1]
    if tipo_cat:
        cs = [c for c in cs if c["type"] == 4]
    else:
        cs = [c for c in cs if c["type"] != 4 and (c.get("parent_id") or None) == pai and ((c["type"] == 2) == voz)]
    return [c["name"] for c in sorted(cs, key=lambda c: (c["position"], int(c["id"])))]


async def main():
    await server.carregar_config(forcar=True)
    for c in list(fake.channels.values()):  # começa limpo para conferir as posições
        if c["type"] == 4:
            c["position"] = 50
    a, b, c = novo("A", 4, pos=0), novo("B", 4, pos=1), novo("C", 4, pos=1)  # B e C empatados de propósito
    await server.editar_canal(c, posicao=0)
    cats = ordem(tipo_cat=True)
    ok(cats[:3] == ["C", "A", "B"], f"categoria vai para o topo e as outras descem ({cats[:4]})")
    ok(len({x["position"] for x in fake.channels.values() if x["type"] == 4}) == len(cats), "sem posições repetidas entre categorias")
    t1, t2, t3 = novo("t1", 0, a, 0), novo("t2", 0, a, 1), novo("t3", 0, a, 2)
    v1 = novo("voz1", 2, a, 0)
    await server.editar_canal(t3, posicao=0)
    ok(ordem(pai=a) == ["t3", "t1", "t2"] and ordem(pai=a, voz=True) == ["voz1"], "canal sobe dentro da categoria; voz não mexe")
    x = novo("x", 0, None, 0)
    res = await server.editar_canal(x, categoria_id="A", posicao=1, nome="📌・x")
    ok(fake.channels[x]["parent_id"] == a and ordem(pai=a) == ["t3", "📌・x", "t1", "t2"] and "position" in res["mudou"],
       "move de categoria, renomeia e posiciona numa chamada só")
    await server.editar_canal(t2, posicao=99)
    ok(ordem(pai=a)[-1] == "t2", "posição maior que a lista vai para o fim")

    regras = novo("📜・regras", 0, a, 5)
    res = await server.editar_canal(regras, definir_como="regras")
    ok(fake.guild.get("rules_channel_id") == regras and "rules_channel_id" in res["mudou"], "define o canal de regras da Comunidade")
    info = await server.info_servidor()
    ok(info["canal_regras"] == regras, "info_servidor mostra o canal de regras")
    try:
        await server.editar_canal(v1, definir_como="regras")
        ok(False, "voz não pode ser canal de regras")
    except server.ErroDiscord:
        ok(True, "voz não pode ser canal de regras")
    try:
        await server.editar_canal(regras, definir_como="banana")
        ok(False, "valor inválido")
    except server.ErroDiscord as e:
        ok("regras" in str(e), "definir_como inválido explica as opções")

    verif = novo("✅・verificação", 0, a, 6)
    res = await server.enviar_mensagem(verif, painel="verificação", opcoes_painel={"cargo": "Membro", "botao_texto": "VERIFICAR-SE"})
    msg = fake.messages[verif][-1]
    ok(msg["author"]["id"] == BOT and msg["components"][0]["components"][0]["custom_id"].startswith("ecov")
       and msg["components"][0]["components"][0]["label"] == "VERIFICAR-SE", "enviar_mensagem com painel=verificação publica o painel")
    tk = novo("🎫・abrir-ticket", 0, a, 7)
    await server.enviar_mensagem(tk, painel="ticket", opcoes_painel={"categoria": "B"})
    ok(fake.messages[tk][-1]["components"][0]["components"][0]["custom_id"].startswith("ecot"), "enviar_mensagem com painel=ticket publica o painel")
    try:
        await server.enviar_mensagem(tk, painel="loja")
        ok(False, "painel inválido")
    except server.ErroDiscord:
        ok(True, "painel inválido é recusado")
    r = await server.enviar_mensagem(tk, texto="oi")
    ok(r["ok"] and fake.messages[tk][-1]["content"] == "oi", "enviar_mensagem normal continua igual")
    # ── sorteio: editar_mensagem troca a imagem e ela não some quando alguém participa ──
    sort = novo("🎉・sorteios", 0, a, 8)
    res = await server.criar_sorteio(sort, premio="Key 7 dias • CS2 (PC)", termina="daqui a 15 dias", vencedores=5,
                                     titulo="🎉 SORTEIO", descricao="texto")
    msg = fake.messages[sort][-1]
    banner = "https://discord-mcp-lbpr.onrender.com/midia/eco-cheats-banner.jpg"
    r = await server.editar_mensagem(sort, msg["id"], imagem_url=banner)
    s = server._cfg["sorteios"][res["sorteio_id"]]
    ok(r["sorteio"] == res["sorteio_id"] and s["imagem_url"] == banner and fake.messages[sort][-1]["embeds"][0]["image"]["url"] == banner,
       "editar_mensagem num sorteio troca a imagem e guarda no sorteio")
    ok(fake.messages[sort][-1]["components"][0]["components"][0]["custom_id"].startswith("ecos:entrar"), "o botão Participar continua")
    membro = next(k for k, v in fake.members.items() if v["user"]["username"] == "joao123")
    import types
    u = fake.members[membro]["user"]
    clique = types.SimpleNamespace(
        id=fake_discord.novo_id(), token="tok", application_id=BOT, type=3, data={"custom_id": f'ecos:entrar:{res["sorteio_id"]}'},
        user=types.SimpleNamespace(id=int(membro), name=u["username"], display_name=u["username"], roles=[]),
        channel_id=int(sort), guild_id=int(GID), guild=types.SimpleNamespace(owner_id=999),
        permissions=types.SimpleNamespace(administrator=False), message=types.SimpleNamespace(embeds=[]))
    await server.ao_interagir(clique)
    await server._atualizar_mensagem_sorteio(s)
    final = fake.messages[sort][-1]["embeds"][0]
    ok(final["image"]["url"] == banner and "**Participantes:** 1" in final["description"],
       "depois de alguém participar, o embed redesenhado mantém a imagem")
    try:
        await server.editar_mensagem(sort, msg["id"], botao_link="https://x.com", botao_texto="x")
        ok(False, "não troca o botão do sorteio")
    except server.ErroDiscord:
        ok(True, "não deixa trocar o botão Participar por um link")

    # ── banner servido pelo próprio bot ──
    from starlette.testclient import TestClient
    from starlette.applications import Starlette
    from starlette.routing import Route
    web = TestClient(Starlette(routes=[Route("/midia/{nome}", server.midia)]))
    resp = web.get("/midia/eco-cheats-banner.jpg")
    ok(resp.status_code == 200 and resp.headers["content-type"] == "image/jpeg" and len(resp.content) > 100000, "banner servido em /midia")
    ok(web.get("/midia/..%2Fserver.py").status_code == 404 and web.get("/midia/server.py").status_code == 404
       and web.get("/midia/nada.png").status_code == 404, "/midia só entrega imagens da pasta midia")
    print(f"\nORGANIZAR OK — {ok_n} verificações")


asyncio.run(main())
