"""Conteúdo fixo: o mesmo conteúdo para todos, sem apagar do canal."""
import asyncio, os, sys, types
os.environ.update(DISCORD_TOKEN="x", GUILD_ID="111111111111111111", CHAVE_SECRETA="x", PIX_CHAVE="3f8a2c1e-7b4d-4e9a-9c2f-5d6e7f8a9b0c")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import httpx2 as httpx, fake_discord, fake_discord2
from suporte import bot as server
fake = fake_discord2.Fake2()
server._api = httpx.AsyncClient(base_url=server.API + "/", transport=httpx.MockTransport(fake.handler))
server._web = httpx.AsyncClient(transport=httpx.MockTransport(fake.handler))
n = 0
def ok(c, m):
    global n
    assert c, m
    n += 1; print("  ✔", m)
def novo(nome, tipo=0, parent=None):
    cid = fake_discord.novo_id(); fake.channels[cid] = {"id": cid, "name": nome, "type": tipo, "position": 5, "parent_id": parent, "permission_overwrites": []}; return cid
def membro(u): return next(k for k, v in fake.members.items() if v["user"]["username"] == u)
def inter(uid, cid, data, tipo=3, cargos=()):
    u = fake.members[uid]["user"]
    return types.SimpleNamespace(id=fake_discord.novo_id(), token="t", application_id=fake_discord.BOT, type=tipo, data=data,
        user=types.SimpleNamespace(id=int(uid), name=u["username"], display_name=u["username"], roles=[types.SimpleNamespace(id=int(c)) for c in cargos]),
        channel_id=int(cid), guild_id=int(fake_discord.GID), guild=types.SimpleNamespace(owner_id=1), permissions=types.SimpleNamespace(administrator=True),
        message=types.SimpleNamespace(embeds=[]))
async def main():
    await server.carregar_config(forcar=True)
    novo("🎟️ TICKETS", 4); loja = novo("astra"); est = novo("📦・conteudo-astra")
    fund = next(r for r in fake.roles.values() if r["name"] == "Fundador")["id"]
    joao, joana = membro("joao123"), membro("joana")
    r = await server.configurar_produto("chatgpt-astra", nome="ChatGPT Astra", preco="10,90", canal_estoque=est, conteudo_fixo=True)
    ok("conteúdo fixo" in r["produto"]["tipo_de_estoque"], "configurar_produto aceita conteudo_fixo")
    loja_info = await server.ver_loja()
    ok(loja_info["produtos"][0]["itens_no_estoque"].startswith("VAZIO"), "estoque vazio avisa para mandar o conteúdo")
    fixada = fake._msg(est, {"content": "instruções (fixada)"}); fixada["pinned"] = True
    fake._msg(est, {"content": "Acesso: https://astra.exemplo/login • senha ABC"})
    ok((await server.ver_loja())["produtos"][0]["itens_no_estoque"].startswith("conteúdo fixo pronto"), "com a mensagem, mostra conteúdo pronto")
    for u in (joao, joana):
        await server.ao_interagir(inter(u, loja, {"custom_id": "ecop:comprar:chatgpt-astra"}))
        cid, c = next((k, v) for k, v in server._cfg["compras"].items() if v["comprador"] == u and v["status"] == "aguardando")
        await server.ao_interagir(inter(membro("vinicius"), cid, {"name": "aprovar_pagamento", "options": []}, tipo=2, cargos=[fund]))
        ent = next(k for k, e in server._cfg["entregas"].items() if e["comprador"] == u)
        ok(any("astra.exemplo" in (m.get("content") or "") for m in fake.messages[ent]), f"comprador {fake.members[u]['user']['username']} recebe o conteúdo no canal privado")
    ok(any("astra.exemplo" in (m.get("content") or "") for m in fake.messages[est]), "conteúdo continua no canal (não é apagado)")
    fake._msg(est, {"content": "Acesso NOVO: https://astra.exemplo/v2"})
    fake.members[joao]["roles"] = []
    await server.ao_interagir(inter(joao, loja, {"custom_id": "ecop:comprar:chatgpt-astra"}))
    cid, c = next((k, v) for k, v in server._cfg["compras"].items() if v["status"] == "aguardando")
    await server.ao_interagir(inter(membro("vinicius"), cid, {"name": "aprovar_pagamento", "options": []}, tipo=2, cargos=[fund]))
    ent = [k for k, e in server._cfg["entregas"].items() if e["comprador"] == joao][-1]
    ok(any("/v2" in (m.get("content") or "") for m in fake.messages[ent]), "mensagem mais nova vira o conteúdo entregue")
    # Fundador testando a própria compra com o canal vazio: não pode travar
    fake.members[membro("vinicius")]["roles"] = []
    for mid in [m["id"] for m in fake.messages[est] if not m.get("pinned")]:
        fake.messages[est] = [m for m in fake.messages[est] if m["id"] != mid]
    vini = membro("vinicius")
    await server.ao_interagir(inter(vini, loja, {"custom_id": "ecop:comprar:chatgpt-astra"}))
    cid, c = next((k, v) for k, v in server._cfg["compras"].items() if v["comprador"] == vini and v["status"] == "aguardando")
    await server.ao_interagir(inter(vini, cid, {"name": "aprovar_pagamento", "options": []}, tipo=2, cargos=[fund]))
    ok(c["status"] == "analise" and "acabou o estoque" in fake.messages[cid][-1]["content"]
       and "Mande o conteúdo" in fake.messages[cid][-1]["content"], "sem conteúdo: avisa no chat (mesmo quando o Fundador é o comprador)")
    print(f"\nFIXO OK — {n} verificações")
asyncio.run(main())
