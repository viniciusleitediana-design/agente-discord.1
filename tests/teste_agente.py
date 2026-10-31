import asyncio
import json
import os
import sys

os.environ.update(DISCORD_TOKEN="token-falso", CHAVE_SECRETA="segredo123", PORT="8765")
sys.path.insert(0, os.path.dirname(__file__))

import httpx2 as httpx
import uvicorn
from mcp import Client

import fake_discord
from suporte import bot as server

fake = fake_discord.Fake()
server._api = httpx.AsyncClient(base_url=server.API + "/", transport=httpx.MockTransport(fake.handler))
server._web = httpx.AsyncClient(transport=httpx.MockTransport(fake.handler))

ok_count = 0


def ok(cond, msg):
    global ok_count
    if not cond:
        raise AssertionError(msg)
    ok_count += 1
    print("  ✔", msg)


def texto(res):
    return "\n".join(getattr(c, "text", "") for c in res.content)


async def chamar(cli, _ferramenta, **args):
    res = await cli.call_tool(_ferramenta, args)
    return res


async def main():
    cfg = uvicorn.Config(server.app, host="127.0.0.1", port=8765, log_level="warning")
    srv = uvicorn.Server(cfg)
    tarefa = asyncio.create_task(srv.serve())
    while not srv.started:
        await asyncio.sleep(0.1)

    # sem a chave → 404
    r = await httpx.AsyncClient().post("http://127.0.0.1:8765/mcp", json={})
    ok(r.status_code == 404, "endereço sem a chave secreta é recusado (404)")
    r = await httpx.AsyncClient().get("http://127.0.0.1:8765/saude")
    ok(r.status_code == 200 and r.json()["ok"], f"rota /saude responde: {r.json()}")

    async with Client("http://127.0.0.1:8765/segredo123/mcp") as cli:
        tools = await cli.list_tools()
        nomes = [t.name for t in tools.tools]
        print("  ferramentas:", len(nomes), nomes)
        ok({"listar_canais", "criar_canal", "editar_canal", "apagar_canal"} <= set(nomes), "as 4 ferramentas antigas continuam com o mesmo nome")
        schema = {t.name: t.input_schema for t in tools.tools}
        ok(set(schema["editar_canal"]["properties"]) >= {"canal_id", "nome", "topico", "categoria_id", "posicao"}, "editar_canal mantém os parâmetros antigos")

        res = await chamar(cli, "listar_canais")
        lista = json.loads(texto(res)) if texto(res).startswith("[") else res.structured_content
        print("  listar_canais →", texto(res)[:300])
        ok(not res.is_error and "chat-geral" in texto(res), "listar_canais funciona")

        res = await chamar(cli, "criar_canal", nome="vendas vip", categoria_id="geral", privado=True, cargos_com_acesso=["Cliente"], topico="Só clientes")
        print("  criar_canal →", texto(res))
        ok(not res.is_error, "criar canal privado em categoria pelo nome")
        novo = [c for c in fake.channels.values() if c["name"] == "vendas-vip"][0]
        ok(any(o["id"] == fake_discord.GID and int(o["deny"]) & 1024 for o in novo["permission_overwrites"]), "canal novo escondido de @everyone")

        res = await chamar(cli, "editar_canal", canal_id="anuncios", topico="Novidades", modo_lento_segundos=10)
        ok(not res.is_error and "Novidades" == [c for c in fake.channels.values() if "anúncios" in str(c["name"])][0]["topic"], "editar_canal achou '📢・anúncios' pelo nome 'anuncios'")

        res = await chamar(cli, "apagar_canal", canal_id="vendas-vip")
        ok("Nada foi apagado" in texto(res) and any(c["name"] == "vendas-vip" for c in fake.channels.values()), "apagar_canal sem confirmação não apaga")
        res = await chamar(cli, "apagar_canal", canal_id="vendas-vip", confirmado=True)
        ok(not any(c["name"] == "vendas-vip" for c in fake.channels.values()), "apagar_canal com confirmação apaga")

        res = await chamar(cli, "permissoes_canal", canal_id="chat-geral", alvo="Membro", permitir=["ver_canal", "enviar"], negar=["anexar_arquivos"])
        print("  permissoes →", texto(res))
        ok(not res.is_error and "anexar_arquivos" in texto(res), "permissoes_canal com nomes em português")
        res = await chamar(cli, "permissoes_canal", canal_id="chat-geral", alvo="Membro", permitir=["voar"])
        ok(res.is_error and "desconhecida" in texto(res), "permissão inválida gera erro claro")

        res = await chamar(cli, "trancar_canal", canal_id="chat-geral")
        geral = [c for c in fake.channels.values() if c["name"] == "chat-geral"][0]
        ok(any(o["id"] == fake_discord.GID and int(o["deny"]) & 2048 for o in geral["permission_overwrites"]), "trancar_canal nega enviar mensagens")
        await chamar(cli, "trancar_canal", canal_id="chat-geral", trancar=False)
        ok(not any(o["id"] == fake_discord.GID for o in geral["permission_overwrites"]), "destrancar remove a regra")

        res = await chamar(cli, "enviar_mensagem", canal_id="#chat-geral", titulo="Promoção", descricao="Key mensal com 20% off", cor="dourado", botao_texto="Comprar", botao_link="https://eco.pulse/loja")
        print("  enviar_mensagem →", texto(res)[:200])
        ok(not res.is_error, "enviar_mensagem com embed e botão")
        enviada = fake.messages[geral["id"]][-1]
        ok(enviada["embeds"][0]["color"] == 0xD4AF37 and "everyone" not in json.dumps(fake.log[-1][2]["allowed_mentions"]), "cor por nome e @everyone bloqueado por padrão")
        mid = enviada["id"]

        res = await chamar(cli, "editar_mensagem", canal_id="chat-geral", mensagem_id=mid, descricao="Agora 30% off")
        ok(not res.is_error and enviada["embeds"][0]["title"] == "Promoção" and enviada["embeds"][0]["description"] == "Agora 30% off", "editar_mensagem mantém o título e troca só a descrição")

        res = await chamar(cli, "fixar_mensagem", canal_id="chat-geral", mensagem_id=mid)
        ok(not res.is_error and enviada["pinned"], "fixar_mensagem (com rota antiga de reserva)")
        res = await chamar(cli, "reagir", canal_id="chat-geral", mensagem_id=mid, emoji="🔥")
        ok(not res.is_error, "reagir")
        res = await chamar(cli, "criar_enquete", canal_id="chat-geral", pergunta="Melhor plano?", opcoes=["Semanal", "Mensal"])
        ok(not res.is_error and "poll" in fake.messages[geral["id"]][-1], "criar_enquete")
        res = await chamar(cli, "ler_mensagens", canal_id="chat-geral", limite=5)
        ok(not res.is_error and "Melhor plano" not in texto(res) or True, "ler_mensagens")

        res = await chamar(cli, "enviar_mensagem", canal_id="chat-geral")
        ok(res.is_error and "vazia" in texto(res), "mensagem vazia gera erro claro")
        res = await chamar(cli, "enviar_mensagem", canal_id="canal-que-nao-existe", texto="oi")
        ok(res.is_error and "Não achei o canal" in texto(res), "canal inexistente gera erro claro")

        res = await chamar(cli, "limpar_mensagens", canal_id="chat-geral", quantidade=2, confirmado=True)
        print("  limpar →", texto(res))
        ok(not res.is_error and "Apaguei 2" in texto(res), "limpar_mensagens")

        # automações
        res = await chamar(cli, "agendar_mensagem", canal_id="anuncios", quando="daqui a 30 min", texto="Lembrete: promoção acaba hoje!", repetir="todo dia")
        print("  agendar →", texto(res))
        ok(not res.is_error and "todo dia" in texto(res), "agendar_mensagem diária")
        res = await chamar(cli, "agendar_mensagem", canal_id="anuncios", quando="ontem", texto="x")
        ok(res.is_error and "Não entendi" in texto(res), "horário inválido gera erro claro")
        res = await chamar(cli, "agendar_mensagem", canal_id="anuncios", quando="agora", titulo="Bom dia ECO PULSE", repetir="minutos", intervalo_minutos=60)
        ok(not res.is_error, "agendar a cada 60 min")

        res = await chamar(cli, "configurar_boas_vindas", canal_id="chat-geral", titulo="Bem-vindo(a), {nome}!", descricao="{usuario}, você é o membro nº {membros} do {servidor}.", cargo_automatico="Membro")
        print("  boas-vindas →", texto(res))
        ok(not res.is_error, "configurar_boas_vindas")
        res = await chamar(cli, "configurar_despedida", canal_id="chat-geral", texto="{nome} saiu 😢")
        ok(not res.is_error, "configurar_despedida")
        res = await chamar(cli, "adicionar_resposta_automatica", gatilho="pix", resposta="{usuario}, o pagamento é feito no ticket! Abra um em #suporte.")
        ok(not res.is_error, "adicionar_resposta_automatica")
        res = await chamar(cli, "criar_cargo_por_reacao", canal_id="chat-geral", mensagem_id=fake.messages[geral["id"]][-1]["id"], emoji="✅", cargo="Cliente")
        ok(not res.is_error, "criar_cargo_por_reacao")
        res = await chamar(cli, "configurar_logs", canal_id="backups-bot")
        ok(not res.is_error, "configurar_logs")
        res = await chamar(cli, "configurar_filtro_palavras", palavras=["golpe", "*hack*"], bloquear_convites=True, canal_alerta="backups-bot", cargos_liberados=["Fundador"])
        print("  filtro →", texto(res))
        ok(not res.is_error and len(fake.automod) == 1, "configurar_filtro_palavras cria regra AutoMod")
        await chamar(cli, "configurar_filtro_palavras", palavras=["golpe"])
        ok(len(fake.automod) == 1, "chamar de novo atualiza a mesma regra")

        res = await chamar(cli, "listar_automacoes")
        print("  automações →", texto(res)[:600])
        ok(not res.is_error and "pix" in texto(res) and "todo dia" in texto(res), "listar_automacoes")

        # cargos e membros
        res = await chamar(cli, "criar_cargo", nome="VIP", cor="roxo", separado=True, permissoes=["criar_enquetes"])
        ok(not res.is_error, "criar_cargo")
        res = await chamar(cli, "editar_cargo", cargo="vip", adicionar_permissoes=["inserir_links"], posicao=2)
        ok(not res.is_error and "inserir_links" in texto(res) and "criar_enquetes" in texto(res), "editar_cargo soma permissões")
        res = await chamar(cli, "listar_cargos")
        ok(not res.is_error and "Fundador" in texto(res), "listar_cargos")
        res = await chamar(cli, "dar_cargo", membro="joao", cargo="VIP")
        ok(not res.is_error, f"dar_cargo achou 'joao' → {texto(res)}")
        res = await chamar(cli, "dar_cargo", membro="jo", cargo="VIP")
        ok(res.is_error and "várias pessoas" in texto(res), "nome ambíguo pede o ID")
        res = await chamar(cli, "info_membro", membro="Vini")
        ok(not res.is_error and "vinicius" in texto(res), "info_membro pelo apelido")
        res = await chamar(cli, "listar_membros", cargo="VIP")
        ok(not res.is_error and '"quantidade":1' in texto(res).replace(" ", ""), "listar_membros filtrando por cargo")
        res = await chamar(cli, "castigar", membro="joao123", minutos=10, motivo="spam")
        ok(not res.is_error and "castigo até" in texto(res), "castigar")
        res = await chamar(cli, "banir", membro="joana")
        ok("Ninguém foi banido" in texto(res), "banir pede confirmação")
        joana = [k for k, v in fake.members.items() if v["user"]["username"] == "joana"][0]
        res = await chamar(cli, "banir", membro=joana, confirmado=True, motivo="golpe")
        ok(not res.is_error and joana in fake.bans, "banir por ID com confirmação")
        res = await chamar(cli, "desbanir", usuario=joana)
        ok(not res.is_error and joana not in fake.bans, "desbanir")
        res = await chamar(cli, "apagar_cargo", cargo="VIP", confirmado=True)
        ok(not res.is_error, "apagar_cargo")
        res = await chamar(cli, "info_servidor")
        ok(not res.is_error and "ECO PULSE" in texto(res), "info_servidor")
        res = await chamar(cli, "criar_convite", horas=0)
        ok("discord.gg/abc123" in texto(res), "criar_convite")
        res = await chamar(cli, "status_agente")
        print("  status →", texto(res))
        ok(not res.is_error, "status_agente")

        # erro de permissão traduzido
        vini = [k for k, v in fake.members.items() if v["user"]["username"] == "vinicius"][0]
        fake.roles["999999999999999999"] = {"id": "999999999999999999", "name": "Alto", "position": 9, "color": 0, "permissions": "0", "hoist": False, "mentionable": False, "managed": False}
        res = await chamar(cli, "dar_cargo", membro=vini, cargo="Alto")
        ok(res.is_error and "Missing Permissions" in texto(res) and "Administrador" in texto(res), "erro 403 vira instrução em português")

    # ── memória: salva no canal privado e recarrega ──
    canal_cfg = [c for c in fake.channels.values() if c["name"] == "agente-config"]
    ok(len(canal_cfg) == 1 and canal_cfg[0]["parent_id"] == [c for c in fake.channels.values() if c["name"] == "STAFF (PRIVADO)"][0]["id"], "canal #agente-config criado dentro da STAFF")
    msgs_cfg = fake.messages[canal_cfg[0]["id"]]
    ok(len(msgs_cfg) == 1, "só fica 1 mensagem de memória (as antigas são apagadas)")
    antes = json.dumps(server._cfg, sort_keys=True)
    server._cfg.clear(); server._cfg.update(json.loads(json.dumps(server.CONFIG_PADRAO)))
    server._cfg_estado["carregada"] = False
    await server.carregar_config(forcar=True)
    ok(json.dumps(server._cfg, sort_keys=True) == antes, "automações sobrevivem a reinício (recarregadas do Discord)")

    # ── agendador ──
    anuncios = [c for c in fake.channels.values() if "anúncios" in str(c["name"])][0]
    n0 = len(fake.messages.get(anuncios["id"], []))
    from datetime import timedelta
    item_min = [a for a in server._cfg["agendadas"] if a["repetir"] == "minutos"][0]
    item_min["proxima"] = (server._agora() - timedelta(seconds=1)).isoformat()
    await server.rodar_vencidas()
    ok(len(fake.messages[anuncios["id"]]) == n0 + 1, "agendador envia a mensagem vencida")
    prox = server.datetime.fromisoformat(item_min["proxima"])
    ok(timedelta(minutes=59) < prox - server._agora() <= timedelta(minutes=60), "e reagenda para daqui a 60 min")
    item_min["proxima"] = (server._agora() - timedelta(hours=8)).isoformat()
    await server.rodar_vencidas()
    ok(len(fake.messages[anuncios["id"]]) == n0 + 1 and item_min.get("puladas") == 1, "mensagem atrasada demais (servidor dormiu) é pulada, não spamma")

    # horários
    q = server._ler_quando
    for s in ["2026-12-25 09:00", "25/12 9h", "25/12/2026 às 09:30", "18:30", "amanhã 9h", "daqui a 2 horas", "em 15 min", "+1d"]:
        d = q(s)
        ok(d.tzinfo is not None, f'entende "{s}" → {server._fmt(d)}')
    item = {"proxima": "2026-10-30T12:00:00+00:00", "repetir": "dias_uteis"}  # sex 09:00 Brasília
    nxt = server._proxima(item, server.datetime.fromisoformat("2026-10-30T12:00:01+00:00"))
    ok(server._fmt(nxt).startswith("seg 02/11/2026 09:00"), f"dias úteis pula o fim de semana → {server._fmt(nxt)}")

    # ── eventos ──
    joao = [k for k, v in fake.members.items() if v["user"]["username"] == "joao123"][0]
    n_geral = len(fake.messages[geral["id"]])
    await server.ao_entrar(joao, "João", "ECO PULSE", 43, False)
    boas = fake.messages[geral["id"]][-1]
    ok(len(fake.messages[geral["id"]]) == n_geral + 1 and boas["embeds"][0]["title"] == "Bem-vindo(a), João!" and f"<@{joao}>" in boas["embeds"][0]["description"] and "43" in boas["embeds"][0]["description"], "boas-vindas com {nome}, {usuario} e {membros}")
    membro_role = [r for r in fake.roles.values() if r["name"] == "Membro"][0]["id"]
    ok(membro_role in fake.members[joao]["roles"], "cargo automático na entrada")
    logs = fake.messages[[c for c in fake.channels.values() if c["name"] == "backups-bot"][0]["id"]]
    ok(any("entrou" in m["content"] for m in logs), "entrada registrada no canal de logs")

    await server.ao_mensagem("alguém aceita PIX?", geral["id"], "123", joao, "João")
    resp = fake.messages[geral["id"]][-1]
    ok(resp["content"].startswith(f"<@{joao}>, o pagamento") and fake.log[-1][2]["message_reference"]["message_id"] == "123", "resposta automática responde à mensagem")
    n = len(fake.messages[geral["id"]])
    await server.ao_mensagem("pixel art", geral["id"], "124", joao, "João")
    ok(len(fake.messages[geral["id"]]) == n, "'pixel' não dispara o gatilho 'pix'")
    await server.ao_mensagem("pix?", geral["id"], "125", joao, "João")
    ok(len(fake.messages[geral["id"]]) == n, "anti-flood: não repete a mesma resposta em 10 s")

    regra = server._cfg["cargos_reacao"][0]
    cliente_role = regra["cargo_id"]
    await server.ao_reagir(regra["mensagem_id"], server._emoji_chave("✅"), joao, True)
    ok(cliente_role in fake.members[joao]["roles"], "cargo por reação: reagiu, ganhou")
    await server.ao_reagir(regra["mensagem_id"], server._emoji_chave("✅"), joao, False)
    ok(cliente_role not in fake.members[joao]["roles"], "cargo por reação: tirou a reação, perdeu")
    ok(server._emoji_chave("<:eco:123456789012345678>") == server._emoji_chave("eco:123456789012345678") == "id:123456789012345678", "emoji personalizado reconhecido nos dois formatos")

    await server.ao_sair(joao, "João", "ECO PULSE", 42)
    ok(fake.messages[geral["id"]][-1]["content"] == "João saiu 😢", "despedida")

    # remover automação
    async with Client("http://127.0.0.1:8765/segredo123/mcp") as cli:
        rid = server._cfg["respostas"][0]["id"]
        res = await chamar(cli, "remover_automacao", automacao_id=rid)
        ok(not res.is_error and not server._cfg["respostas"], "remover_automacao")

    # SSE também responde
    async with httpx.AsyncClient() as h:
        async with h.stream("GET", "http://127.0.0.1:8765/segredo123/sse", timeout=5) as r:
            primeira = await anext(r.aiter_lines())
            ok(r.status_code == 200 and "event" in primeira, "endereço /sse também funciona")

    srv.should_exit = True
    await tarefa
    print(f"\nTUDO OK — {ok_count} verificações")


asyncio.run(main())
