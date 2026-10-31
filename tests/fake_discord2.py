"""Discord simulado com interações, anexos e edição de mensagens."""
import json
import re

import httpx2 as httpx

import fake_discord

GID, BOT = fake_discord.GID, fake_discord.BOT
CDN = "https://cdn.discordapp.com/attachments"


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
               "pinned": False, "_am": body.get("allowed_mentions") or {}}
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
        am = (body or {}).get("allowed_mentions") if isinstance(body, dict) else None
        for k in ("users", "roles"):
            lista = (am or {}).get(k) or []
            if len(lista) != len(set(lista)):   # o Discord real recusa repetidos
                return J({"code": 50035, "message": "Invalid Form Body", "errors": {"allowed_mentions": {k: {"1": {
                    "_errors": [{"code": "SET_TYPE_ALREADY_CONTAINS_VALUE", "message": "The set already contains this value"}]}}}}}, 400)
        if p.startswith("/applications/"):
            self.comandos = body
            return J(body)
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


