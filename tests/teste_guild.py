import asyncio, os, sys
os.environ.update(DISCORD_TOKEN="x", GUILD_ID="333333333333333333")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import httpx2 as httpx, fake_discord
from suporte import bot as server
f = fake_discord.Fake()
server._api = httpx.AsyncClient(base_url=server.API + "/", transport=httpx.MockTransport(f.handler))
async def main():
    try:
        await server.servidor_id(); print("ERRO: deveria falhar")
    except server.ErroDiscord as e:
        print("mensagem:", e)
        assert "não está no servidor 333333333333333333" in str(e) and "ECO PULSE (ID 111111111111111111)" in str(e)
    server._servidor, server._servidor_ok = fake_discord.GID, False
    assert await server.servidor_id() == fake_discord.GID and server._servidor_ok
    print("GUILD OK")
asyncio.run(main())
