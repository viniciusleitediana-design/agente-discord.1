"""Testa a ligação com o gateway usando um 'discord' falso que imita a API do discord.py."""
import asyncio
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import types

os.environ.update(DISCORD_TOKEN="token-falso", GUILD_ID="111111111111111111")

# ── discord.py falso ──
fake = types.ModuleType("discord")


class ClientException(Exception): ...
class PrivilegedIntentsRequired(ClientException): ...
class LoginFailure(ClientException): ...


class Intents:
    @classmethod
    def none(cls):
        i = cls()
        i.guilds = i.members = i.guild_messages = i.guild_reactions = i.message_content = False
        return i


class MemberCacheFlags:
    @classmethod
    def none(cls):
        return cls()


class UsuarioBot:
    id = 222
    def __str__(self):
        return "EcoBot#0001"


criados = []


class Client:
    def __init__(self, *, intents, max_messages, chunk_guilds_at_startup, member_cache_flags):
        self.intents, self.user, self.fechado = intents, UsuarioBot(), False
        self.guilds = [types.SimpleNamespace(name="Outro servidor", id=555)]
        criados.append(self)

    def event(self, fn):
        assert asyncio.iscoroutinefunction(fn)
        setattr(self, fn.__name__, fn)
        return fn

    async def start(self, token):
        if self.intents.members or self.intents.message_content:
            raise PrivilegedIntentsRequired("4014")
        await self.on_ready()
        await asyncio.sleep(3600)

    async def close(self):
        self.fechado = True


fake.ClientException, fake.PrivilegedIntentsRequired, fake.LoginFailure = ClientException, PrivilegedIntentsRequired, LoginFailure
fake.Intents, fake.MemberCacheFlags, fake.Client = Intents, MemberCacheFlags, Client
sys.modules["discord"] = fake

from suporte import bot as server

chamadas = []
server.ao_entrar = lambda *a: chamadas.append(("entrar", a)) or asyncio.sleep(0)
server.ao_mensagem = lambda *a: chamadas.append(("msg", a)) or asyncio.sleep(0)
server.ao_reagir = lambda *a: chamadas.append(("reacao", a)) or asyncio.sleep(0)


async def main():
    tarefa = asyncio.create_task(server.rodar_bot())
    await asyncio.sleep(0.2)
    print("status:", server._bot_estado)
    assert len(criados) == 2 and criados[0].fechado, "tentou com intents privilegiadas e caiu para o modo reduzido"
    assert server._bot_estado["intents_privilegiadas"] is False and "SERVER MEMBERS INTENT" in server._bot_estado["aviso"]
    assert server._bot_estado["status"].startswith("conectado")
    c = criados[1]
    for nome in ("on_ready", "on_member_join", "on_member_remove", "on_message", "on_raw_reaction_add", "on_raw_reaction_remove"):
        assert hasattr(c, nome), nome
    guild = types.SimpleNamespace(id=111111111111111111, name="ECO PULSE", member_count=50)
    outro = types.SimpleNamespace(id=999, name="Outro", member_count=5)
    membro = types.SimpleNamespace(id=333, display_name="Ana", guild=guild, bot=False)
    await c.on_member_join(membro)
    await c.on_member_join(types.SimpleNamespace(id=334, display_name="X", guild=outro, bot=False))
    autor = types.SimpleNamespace(id=333, bot=False, display_name="Ana")
    await c.on_message(types.SimpleNamespace(author=autor, guild=guild, content="pix", channel=types.SimpleNamespace(id=5), id=6))
    await c.on_message(types.SimpleNamespace(author=types.SimpleNamespace(id=1, bot=True, display_name="b"), guild=guild, content="pix", channel=types.SimpleNamespace(id=5), id=7))
    emoji = types.SimpleNamespace(id=None, name="✅️")
    await c.on_raw_reaction_add(types.SimpleNamespace(guild_id=111111111111111111, user_id=333, message_id=8, emoji=emoji))
    await c.on_raw_reaction_add(types.SimpleNamespace(guild_id=111111111111111111, user_id=222, message_id=8, emoji=emoji))
    print("chamadas:", chamadas)
    assert chamadas == [("entrar", ("333", "Ana", "ECO PULSE", 50, False)),
                        ("msg", ("pix", "5", "6", "333", "Ana")),
                        ("reacao", ("8", "✅", "333", True))]
    tarefa.cancel()
    print("GATEWAY OK")


asyncio.run(main())
