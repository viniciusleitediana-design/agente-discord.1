import asyncio, os, sys, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.update(DISCORD_TOKEN="x", PORT="8767", CHAVE_SECRETA="chave-de-teste")
import httpx2 as httpx, uvicorn
from suporte import bot as server
async def main():
    srv = uvicorn.Server(uvicorn.Config(server.app, host="127.0.0.1", port=8767, log_level="warning"))
    t = asyncio.create_task(srv.serve())
    while not srv.started: await asyncio.sleep(0.05)
    async with httpx.AsyncClient() as h:
        for v in ["2025-03-26", "2025-06-18", "2025-11-25"]:
            r = await h.post("http://127.0.0.1:8767/chave-de-teste/mcp", headers={"Accept": "application/json, text/event-stream", "Content-Type": "application/json"},
                json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": v, "capabilities": {}, "clientInfo": {"name": "claude-ai", "version": "1"}}})
            corpo = r.text
            linha = next((l for l in corpo.splitlines() if l.startswith("data:")), corpo)
            d = json.loads(linha.removeprefix("data:").strip())
            print(v, "→", r.status_code, d.get("result", {}).get("protocolVersion"), d.get("result", {}).get("serverInfo"), d.get("error"))
            r2 = await h.post("http://127.0.0.1:8767/chave-de-teste/mcp", headers={"Accept": "application/json, text/event-stream", "Content-Type": "application/json", "mcp-protocol-version": v},
                json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
            linha = next((l for l in r2.text.splitlines() if l.startswith("data:")), r2.text)
            d2 = json.loads(linha.removeprefix("data:").strip())
            print("   tools/list:", r2.status_code, len(d2.get("result", {}).get("tools", [])), d2.get("error"))
    srv.should_exit = True; await t
asyncio.run(main())
