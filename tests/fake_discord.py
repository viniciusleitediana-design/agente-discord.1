"""Discord falso em memória para testar o agente sem internet."""
import itertools
import json
import re
import time

import httpx2 as httpx

GID = "111111111111111111"
BOT = "222222222222222222"
_seq = itertools.count(1)


def novo_id():
    # snowflake com data de agora
    ms = int(time.time() * 1000) - 1420070400000
    return str((ms << 22) + next(_seq))


class Fake:
    def __init__(self):
        self.guild = {"id": GID, "name": "ECO PULSE", "approximate_member_count": 42,
                      "approximate_presence_count": 10, "features": [], "roles": []}
        cat = {"id": novo_id(), "name": "STAFF (PRIVADO)", "type": 4, "position": 1, "permission_overwrites": []}
        cat2 = {"id": novo_id(), "name": "GERAL", "type": 4, "position": 0, "permission_overwrites": []}
        self.channels = {
            c["id"]: c for c in [
                cat, cat2,
                {"id": novo_id(), "name": "📢・anúncios", "type": 0, "position": 0, "parent_id": cat2["id"], "permission_overwrites": []},
                {"id": novo_id(), "name": "chat-geral", "type": 0, "position": 1, "parent_id": cat2["id"], "permission_overwrites": []},
                {"id": novo_id(), "name": "Call", "type": 2, "position": 2, "parent_id": cat2["id"], "permission_overwrites": []},
                {"id": novo_id(), "name": "backups-bot", "type": 0, "position": 0, "parent_id": cat["id"], "permission_overwrites": []},
            ]}
        self.roles = {GID: {"id": GID, "name": "@everyone", "position": 0, "color": 0, "permissions": "1024", "hoist": False, "mentionable": False, "managed": False}}
        for i, n in enumerate(["Fundador", "Cliente", "Membro"]):
            rid = novo_id()
            self.roles[rid] = {"id": rid, "name": n, "position": 3 - i, "color": 0x22C55E, "permissions": "8" if n == "Fundador" else "0",
                               "hoist": True, "mentionable": False, "managed": False}
        self.members = {}
        for uname, nick in [("vinicius", "Vini"), ("joao123", None), ("joana", None)]:
            uid = novo_id()
            self.members[uid] = {"user": {"id": uid, "username": uname, "global_name": uname.title()}, "nick": nick,
                                 "roles": [], "joined_at": "2026-10-01T12:00:00+00:00"}
        self.messages = {}   # cid -> list (oldest first)
        self.files = {}
        self.bans = {}
        self.automod = {}
        self.log = []

    def handler(self, req: httpx.Request) -> httpx.Response:
        url = str(req.url)
        if url.startswith("https://cdn.fake/"):
            return httpx.Response(200, content=self.files[url])
        path = req.url.path.removeprefix("/api/v10")
        m, body = req.method, None
        ctype = req.headers.get("content-type", "")
        if ctype.startswith("application/json") and req.content:
            body = json.loads(req.content)
        elif ctype.startswith("multipart/form-data"):
            body = self._multipart(req)
        self.log.append((m, path, body))
        try:
            return self.rota(m, path, body, req)
        except KeyError:
            return httpx.Response(404, json={"message": "Unknown", "code": 10003})

    def _multipart(self, req):
        raw = req.content
        boundary = req.headers["content-type"].split("boundary=")[1].encode()
        partes = raw.split(b"--" + boundary)
        payload, arquivo = None, None
        for p in partes:
            if b'name="payload_json"' in p:
                payload = json.loads(p.split(b"\r\n\r\n", 1)[1].rsplit(b"\r\n", 1)[0])
            elif b'name="files[0]"' in p:
                arquivo = p.split(b"\r\n\r\n", 1)[1].rsplit(b"\r\n", 1)[0]
        payload = payload or {}
        payload["_arquivo"] = arquivo
        return payload

    def _msg(self, cid, body):
        mid = novo_id()
        msg = {"id": mid, "channel_id": cid, "author": {"id": BOT, "username": "EcoBot", "bot": True},
               "content": body.get("content", ""), "embeds": body.get("embeds", []), "attachments": [],
               "timestamp": "2026-10-28T23:00:00+00:00", "pinned": False}
        if body.get("_arquivo") is not None:
            url = f"https://cdn.fake/attachments/{mid}/agente-config.json"
            self.files[url] = body["_arquivo"]
            msg["attachments"] = [{"id": mid, "filename": "agente-config.json", "url": url}]
        if "poll" in body:
            msg["poll"] = body["poll"]
        self.messages.setdefault(cid, []).append(msg)
        return msg

    def rota(self, m, p, body, req):
        J = lambda d, s=200: httpx.Response(s, json=d)
        N = httpx.Response(204)
        if p == "/users/@me":
            return J({"id": BOT, "username": "EcoBot", "bot": True})
        if p == "/users/@me/guilds":
            return J([{"id": GID, "name": "ECO PULSE"}])
        if p == "/users/@me/channels":
            cid = "9" + body["recipient_id"][1:]
            self.channels.setdefault(cid, {"id": cid, "type": 1, "name": None})
            return J({"id": cid, "type": 1})
        if p == f"/guilds/{GID}":
            if m == "PATCH":
                self.guild.update(body)
            g = dict(self.guild); g["roles"] = list(self.roles.values()); return J(g)
        if p == f"/guilds/{GID}/channels":
            if m == "GET":
                return J([c for c in self.channels.values() if c["type"] != 1])
            if m == "PATCH":
                for item in body:
                    self.channels[item["id"]].update({k: v for k, v in item.items() if k != "id"})
                return N
            c = {"id": novo_id(), "name": body["name"].lower().replace(" ", "-") if body["type"] != 4 else body["name"],
                 "type": body["type"], "position": 9, "parent_id": body.get("parent_id"),
                 "permission_overwrites": body.get("permission_overwrites", []), "topic": body.get("topic")}
            self.channels[c["id"]] = c
            return J(c, 201)
        mm = re.fullmatch(r"/channels/(\d+)", p)
        if mm:
            c = self.channels[mm[1]]
            if m == "GET": return J(c)
            if m == "PATCH": c.update({k: v for k, v in body.items()}); return J(c)
            if m == "DELETE": del self.channels[mm[1]]; return J(c)
        mm = re.fullmatch(r"/channels/(\d+)/permissions/(\d+)", p)
        if mm:
            c = self.channels[mm[1]]
            c["permission_overwrites"] = [o for o in c["permission_overwrites"] if o["id"] != mm[2]]
            if m == "PUT":
                c["permission_overwrites"].append({"id": mm[2], **body})
            return N
        mm = re.fullmatch(r"/channels/(\d+)/messages", p)
        if mm:
            cid = mm[1]
            if cid not in self.channels: raise KeyError
            if m == "POST":
                return J(self._msg(cid, body))
            lst = list(reversed(self.messages.get(cid, [])))
            before = req.url.params.get("before")
            if before:
                lst = [x for x in lst if int(x["id"]) < int(before)]
            return J(lst[: int(req.url.params.get("limit", 50))])
        mm = re.fullmatch(r"/channels/(\d+)/messages/bulk-delete", p)
        if mm:
            ids = set(body["messages"]); self.messages[mm[1]] = [x for x in self.messages[mm[1]] if x["id"] not in ids]; return N
        mm = re.fullmatch(r"/channels/(\d+)/messages/(\d+)", p)
        if mm:
            lst = self.messages.get(mm[1], [])
            msg = next((x for x in lst if x["id"] == mm[2]), None)
            if not msg: return J({"message": "Unknown Message", "code": 10008}, 404)
            if m == "GET": return J(msg)
            if m == "PATCH": msg.update(body); return J(msg)
            if m == "DELETE": lst.remove(msg); return N
        mm = re.fullmatch(r"/channels/(\d+)/messages/pins/(\d+)", p)
        if mm:
            return J({"message": "404: Not Found", "code": 0}, 404)   # simula rota nova inexistente
        mm = re.fullmatch(r"/channels/(\d+)/pins/(\d+)", p)
        if mm:
            msg = next(x for x in self.messages[mm[1]] if x["id"] == mm[2]); msg["pinned"] = (m == "PUT"); return N
        mm = re.fullmatch(r"/channels/(\d+)/messages/(\d+)/reactions/([^/]+)/@me", p)
        if mm:
            return N
        mm = re.fullmatch(r"/channels/(\d+)/invites", p)
        if mm:
            return J({"code": "abc123"})
        if p == f"/guilds/{GID}/roles":
            if m == "GET": return J(list(self.roles.values()))
            if m == "POST":
                rid = novo_id()
                r = {"id": rid, "name": body["name"], "position": 1, "color": body.get("color", 0), "permissions": body.get("permissions", "0"),
                     "hoist": body.get("hoist", False), "mentionable": body.get("mentionable", False), "managed": False}
                self.roles[rid] = r; return J(r)
            if m == "PATCH":
                for it in body: self.roles[it["id"]]["position"] = it["position"]
                return J(list(self.roles.values()))
        mm = re.fullmatch(rf"/guilds/{GID}/roles/(\d+)", p)
        if mm:
            r = self.roles[mm[1]]
            if m == "PATCH": r.update(body); return J(r)
            if m == "DELETE": del self.roles[mm[1]]; return N
        if p == f"/guilds/{GID}/members/search":
            q = req.url.params["query"].lower()
            return J([x for x in self.members.values() if x["user"]["username"].startswith(q) or (x["nick"] or "").lower().startswith(q)])
        if p == f"/guilds/{GID}/members":
            return J(list(self.members.values()))
        mm = re.fullmatch(rf"/guilds/{GID}/members/(\d+)", p)
        if mm:
            if mm[1] not in self.members: return J({"message": "Unknown Member", "code": 10007}, 404)
            x = self.members[mm[1]]
            if m == "GET": return J(x)
            if m == "PATCH": x.update(body); return J(x)
            if m == "DELETE": del self.members[mm[1]]; return N
        mm = re.fullmatch(rf"/guilds/{GID}/members/(\d+)/roles/(\d+)", p)
        if mm:
            x = self.members[mm[1]]
            if mm[2] == "999999999999999999":
                return J({"message": "Missing Permissions", "code": 50013}, 403)
            if m == "PUT" and mm[2] not in x["roles"]: x["roles"].append(mm[2])
            if m == "DELETE" and mm[2] in x["roles"]: x["roles"].remove(mm[2])
            return N
        mm = re.fullmatch(rf"/guilds/{GID}/bans/(\d+)", p)
        if mm:
            if m == "PUT": self.bans[mm[1]] = {"user": {"id": mm[1], "username": "banido"}}; self.members.pop(mm[1], None)
            if m == "DELETE": self.bans.pop(mm[1])
            return N
        if p == f"/guilds/{GID}/bans":
            return J(list(self.bans.values()))
        if p == f"/guilds/{GID}/auto-moderation/rules":
            if m == "GET": return J(list(self.automod.values()))
            rid = novo_id(); self.automod[rid] = {"id": rid, **body}; return J(self.automod[rid])
        mm = re.fullmatch(rf"/guilds/{GID}/auto-moderation/rules/(\d+)", p)
        if mm:
            self.automod[mm[1]].update(body); return J(self.automod[mm[1]])
        return J({"message": f"rota falsa não implementada: {m} {p}", "code": 0}, 404)
