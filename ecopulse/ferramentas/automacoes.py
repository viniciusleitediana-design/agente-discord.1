"""Ferramentas do conector: automações (agendadas, boas-vindas, respostas, cargos por reação, filtro)."""

import secrets
from datetime import timedelta, timezone
from typing import Any

from ..conector import DESTRUTIVA, LEITURA, mcp

# ── automações ──

@mcp.tool()
async def agendar_mensagem(canal_id: str, quando: str, texto: str | None = None, titulo: str | None = None,
                           descricao: str | None = None, cor: str | None = None, imagem_url: str | None = None,
                           rodape: str | None = None, botao_texto: str | None = None, botao_link: str | None = None,
                           repetir: str = "nao", intervalo_minutos: int | None = None,
                           mencionar_todos: bool = False, nome: str | None = None) -> dict:
    """Agenda uma mensagem (horário de Brasília) e, se quiser, repete. quando: "AAAA-MM-DD HH:MM",
    "DD/MM HH:MM", "HH:MM" (hoje, ou amanhã se já passou), "amanhã 9h" ou "daqui a 30 min".
    repetir: nao, diario, semanal, dias_uteis (seg a sex) ou minutos (com intervalo_minutos, mínimo 10).
    Roda no próprio bot, mesmo com o Claude fechado."""
    await exigir_config()
    canal = await achar_canal(canal_id, tipos=TIPOS_MENSAGEM)
    payload = montar_mensagem(texto, titulo, descricao, cor, await _guardar_imagem(imagem_url), None, rodape,
                              botao_texto, botao_link, mencionar_todos)
    rep = REPETICOES.get(_norm(repetir))
    if rep is None:
        raise ErroDiscord('repetir deve ser: nao, diario, semanal, dias_uteis ou minutos.')
    if rep == "minutos":
        if not intervalo_minutos or not 10 <= int(intervalo_minutos) <= 43200:
            raise ErroDiscord("Para repetir a cada X minutos, passe intervalo_minutos entre 10 e 43200.")
    quando_dt = _ler_quando(quando)
    if quando_dt.astimezone(timezone.utc) < _agora() - timedelta(minutes=1):
        raise ErroDiscord(f"Esse horário ({_fmt(quando_dt)}) já passou.")
    if rep == "dias_uteis":
        while quando_dt.astimezone(FUSO).weekday() >= 5:
            quando_dt += timedelta(days=1)
    item = {"id": secrets.token_hex(3), "nome": (nome or titulo or texto or "mensagem")[:50],
            "canal_id": canal["id"], "canal_nome": canal["name"], "mensagem": payload,
            "proxima": quando_dt.astimezone(timezone.utc).isoformat(), "repetir": rep,
            "intervalo_minutos": int(intervalo_minutos) if rep == "minutos" else None,
            "criada": _agora().isoformat(), "envios": 0}
    _cfg["agendadas"].append(item)
    await salvar_config()
    return {"ok": True, "id": item["id"], "canal": canal["name"], "primeiro_envio": _fmt(quando_dt),
            "repete": NOMES_REPETICAO[rep].format(n=intervalo_minutos)}


@mcp.tool(annotations=LEITURA)
async def listar_automacoes() -> dict:
    """Mostra tudo que está automatizado: mensagens agendadas, boas-vindas, despedida, respostas
    automáticas, cargos por reação e canal de registros (com os IDs para remover)."""
    await garantir_config()
    bv, dp, lg = _cfg.get("boas_vindas") or {}, _cfg.get("despedida") or {}, _cfg.get("logs") or {}
    resultado: dict[str, Any] = {
        "mensagens_agendadas": [
            {"id": a["id"], "nome": a.get("nome"), "canal": a.get("canal_nome"), "proximo_envio": _fmt(a["proxima"]),
             "repete": NOMES_REPETICAO.get(a.get("repetir", "nao"), "?").format(n=a.get("intervalo_minutos")),
             "envios": a.get("envios", 0), **({"ultimo_erro": a["ultimo_erro"]} if a.get("ultimo_erro") else {})}
            for a in sorted(_cfg["agendadas"], key=lambda a: a["proxima"])],
        "boas_vindas": ({"canal": bv.get("canal_nome"), "texto": bv.get("texto"), "titulo": bv.get("titulo"),
                         "cargo_automatico": bv.get("cargo_nome"), "dm": bv.get("mandar_dm", False)}
                        if bv.get("ativo") else "desligado"),
        "despedida": {"canal": dp.get("canal_nome"), "texto": dp.get("texto")} if dp.get("ativo") else "desligado",
        "respostas_automaticas": [
            {"id": r["id"], "gatilho": r["gatilho"], "modo": r.get("modo", "contem"),
             "canal": r.get("canal_nome") or "todos", "resposta": r["resposta"][:120]} for r in _cfg["respostas"]],
        "cargos_por_reacao": [
            {"id": c["id"], "emoji": c["emoji_exibir"], "cargo": c["cargo_nome"], "canal": c.get("canal_nome"),
             "mensagem_id": c["mensagem_id"]} for c in _cfg["cargos_reacao"]],
        "registros": f'#{lg.get("canal_nome")}' if lg.get("ativo") else "desligado",
        "paineis": [
            {"id": p["id"], "tipo": "ticket" if p["tipo"] == "ticket" else "verificação", "canal": p.get("canal_nome"),
             **({"cargo": p.get("cargo_nome")} if p["tipo"] == "verificacao" else
                {"tickets_em": p.get("categoria_nome"), "equipe": [c["nome"] for c in p.get("cargos_equipe", [])],
                 "historico_em": p.get("canal_historico_nome")})} for p in _cfg.get("paineis", {}).values()],
        "tickets_abertos": [
            {"canal": f"<#{cid}>", "numero": t.get("numero"), "dono": t.get("dono_nome"), "assunto": t.get("motivo"),
             "atendido_por": t.get("assumido_nome"), "aberto": _fmt(t.get("aberto"))}
            for cid, t in _cfg.get("tickets", {}).items()],
        "sorteios": [
            {"id": x["id"], "premio": x["premio"], "canal": x.get("canal_nome"), "status": x["status"],
             "participantes": len(x.get("participantes", [])),
             ("termina" if x["status"] == "ativo" else "terminou"): _fmt(x["fim"]),
             **({"ganhadores": [f"<@{g}>" for g in x.get("ganhadores", [])]} if x["status"] == "encerrado" else {})}
            for x in sorted(_cfg.get("sorteios", {}).values(), key=lambda x: x["fim"], reverse=True)],
    }
    if not _cfg_estado["carregada"]:
        resultado["aviso"] = _cfg_estado["aviso"] or "Memória ainda não carregada."
    return resultado


@mcp.tool(annotations=DESTRUTIVA)
async def remover_automacao(automacao_id: str) -> str:
    """Remove uma mensagem agendada, resposta automática, cargo por reação ou painel (ticket/verificação) pelo ID
    (veja listar_automacoes). Remover um painel desliga o botão dele; a mensagem continua no canal."""
    await exigir_config()
    alvo = automacao_id.strip().strip("`")
    if alvo in _cfg.get("paineis", {}):
        p = _cfg["paineis"].pop(alvo)
        await salvar_config()
        return f'✅ Painel de {"ticket" if p["tipo"] == "ticket" else "verificação"} {alvo} desligado (a mensagem em #{p.get("canal_nome")} continua lá; apague se quiser).'
    if alvo in _cfg.get("sorteios", {}):
        raise ErroDiscord("Para sorteios use encerrar_sorteio ou cancelar_sorteio.")
    for lista, rotulo in (("agendadas", "Mensagem agendada"), ("respostas", "Resposta automática"),
                          ("cargos_reacao", "Cargo por reação")):
        for item in _cfg[lista]:
            if item["id"] == alvo:
                _cfg[lista].remove(item)
                await salvar_config()
                return f"✅ {rotulo} {alvo} removida."
    raise ErroDiscord(f"Não achei automação com ID {alvo}. Use listar_automacoes.")


@mcp.tool()
async def configurar_boas_vindas(canal_id: str | None = None, texto: str | None = None, titulo: str | None = None,
                                 descricao: str | None = None, cor: str | None = None, imagem_url: str | None = None,
                                 cargo_automatico: str | None = None, mandar_dm: bool = False,
                                 ativo: bool = True) -> dict:
    """Mensagem automática quando alguém entra no servidor. Textos aceitam {usuario} (menciona),
    {nome}, {servidor} e {membros}. cargo_automatico dá um cargo para quem entra. mandar_dm também
    manda a mensagem no privado. ativo=false desliga."""
    await exigir_config()
    if not ativo:
        _cfg["boas_vindas"] = {**(_cfg.get("boas_vindas") or {}), "ativo": False}
        await salvar_config()
        return {"ok": True, "boas_vindas": "desligado"}
    conf: dict[str, Any] = {"ativo": True, "texto": texto, "titulo": titulo, "descricao": descricao,
                            "cor": cor, "imagem_url": await _guardar_imagem(imagem_url), "mandar_dm": mandar_dm}
    if canal_id:
        canal = await achar_canal(canal_id, tipos=TIPOS_MENSAGEM)
        conf.update(canal_id=canal["id"], canal_nome=canal["name"])
    if cargo_automatico:
        cargo = await achar_cargo(cargo_automatico)
        conf.update(cargo_id=cargo["id"], cargo_nome=cargo["name"])
    if not (canal_id or mandar_dm or cargo_automatico):
        raise ErroDiscord("Diga o canal da mensagem (canal_id), ou mandar_dm=true, ou um cargo_automatico.")
    if canal_id or mandar_dm:
        montar_mensagem(texto, titulo, descricao, cor, imagem_url)  # valida
    _cfg["boas_vindas"] = conf
    await salvar_config()
    resultado: dict[str, Any] = {"ok": True, "boas_vindas": "ligado", "canal": conf.get("canal_nome"),
                                 "cargo_automatico": conf.get("cargo_nome"), "dm": mandar_dm}
    if _bot_estado.get("intents_privilegiadas") is False or not str(_bot_estado["status"]).startswith("conectado"):
        resultado["atencao"] = _bot_estado.get("aviso") or f'O bot em tempo real está: {_bot_estado["status"]}.'
    return resultado


@mcp.tool()
async def configurar_despedida(canal_id: str | None = None, texto: str | None = None, titulo: str | None = None,
                               descricao: str | None = None, cor: str | None = None, ativo: bool = True) -> dict:
    """Mensagem automática quando alguém sai do servidor ({nome}, {usuario}, {servidor}, {membros}).
    ativo=false desliga."""
    await exigir_config()
    if not ativo:
        _cfg["despedida"] = {**(_cfg.get("despedida") or {}), "ativo": False}
        await salvar_config()
        return {"ok": True, "despedida": "desligado"}
    if not canal_id:
        raise ErroDiscord("Diga em qual canal a despedida aparece (canal_id).")
    canal = await achar_canal(canal_id, tipos=TIPOS_MENSAGEM)
    montar_mensagem(texto, titulo, descricao, cor)
    _cfg["despedida"] = {"ativo": True, "canal_id": canal["id"], "canal_nome": canal["name"], "texto": texto,
                         "titulo": titulo, "descricao": descricao, "cor": cor}
    await salvar_config()
    return {"ok": True, "despedida": "ligado", "canal": canal["name"]}


@mcp.tool()
async def adicionar_resposta_automatica(gatilho: str, resposta: str, modo: str = "contem",
                                        canal_id: str | None = None) -> dict:
    """O bot responde sozinho quando alguém escreve o gatilho. modo: contem (a palavra/frase aparece
    na mensagem), exata (a mensagem é só isso) ou comeca. canal_id limita a um canal.
    A resposta aceita {usuario} e {nome}."""
    await exigir_config()
    modo_n = {"contem": "contem", "exata": "exata", "exato": "exata", "comeca": "comeca", "comecacom": "comeca"}.get(_norm(modo))
    if not modo_n:
        raise ErroDiscord("modo deve ser contem, exata ou comeca.")
    if not _norm_frase(gatilho):
        raise ErroDiscord("O gatilho está vazio.")
    if len(_cfg["respostas"]) >= 100:
        raise ErroDiscord("Limite de 100 respostas automáticas atingido; remova alguma antes.")
    item: dict[str, Any] = {"id": secrets.token_hex(3), "gatilho": gatilho.strip(), "resposta": resposta[:2000], "modo": modo_n}
    if canal_id:
        canal = await achar_canal(canal_id, tipos=TIPOS_MENSAGEM)
        item.update(canal_id=canal["id"], canal_nome=canal["name"])
    _cfg["respostas"].append(item)
    await salvar_config()
    resultado: dict[str, Any] = {"ok": True, "id": item["id"], "gatilho": item["gatilho"], "modo": modo_n,
                                 "canal": item.get("canal_nome", "todos")}
    if _bot_estado.get("intents_privilegiadas") is False:
        resultado["atencao"] = _bot_estado.get("aviso")
    return resultado


@mcp.tool()
async def criar_cargo_por_reacao(canal_id: str, mensagem_id: str, emoji: str, cargo: str) -> dict:
    """Quem reagir com o emoji na mensagem ganha o cargo (e perde ao tirar a reação). Para montar um
    painel: envie a mensagem com enviar_mensagem e chame esta ferramenta uma vez para cada emoji."""
    await exigir_config()
    canal = await achar_canal(canal_id, tipos=TIPOS_MENSAGEM)
    await dc("GET", f'/channels/{canal["id"]}/messages/{mensagem_id}')
    c = await achar_cargo(cargo)
    if c["id"] == await servidor_id() or c.get("managed"):
        raise ErroDiscord("Esse cargo não pode ser dado por reação.")
    await dc("PUT", f'/channels/{canal["id"]}/messages/{mensagem_id}/reactions/{_emoji_url(emoji)}/@me')
    chave = _emoji_chave(emoji)
    _cfg["cargos_reacao"] = [r for r in _cfg["cargos_reacao"] if not (r["mensagem_id"] == mensagem_id and r["emoji"] == chave)]
    item = {"id": secrets.token_hex(3), "canal_id": canal["id"], "canal_nome": canal["name"], "mensagem_id": mensagem_id,
            "emoji": chave, "emoji_exibir": emoji, "cargo_id": c["id"], "cargo_nome": c["name"]}
    _cfg["cargos_reacao"].append(item)
    await salvar_config()
    return {"ok": True, "id": item["id"], "emoji": emoji, "cargo": c["name"]}


@mcp.tool()
async def configurar_logs(canal_id: str | None = None, ativo: bool = True) -> str:
    """Define um canal de registros: entradas, saídas e ações do agente (apagar, banir, expulsar...)."""
    await exigir_config()
    if not ativo:
        _cfg["logs"] = {**(_cfg.get("logs") or {}), "ativo": False}
        await salvar_config()
        return "Registros desligados."
    if not canal_id:
        raise ErroDiscord("Diga qual canal recebe os registros.")
    canal = await achar_canal(canal_id, tipos=TIPOS_MENSAGEM)
    _cfg["logs"] = {"ativo": True, "canal_id": canal["id"], "canal_nome": canal["name"]}
    await salvar_config()
    await registrar("✅ Este canal agora recebe os registros do agente ECO PULSE.")
    return f'✅ Registros indo para #{canal["name"]}.'


NOME_REGRA_FILTRO = "ECO PULSE • Filtro"


@mcp.tool()
async def configurar_filtro_palavras(palavras: list[str] | None = None, bloquear_convites: bool = False,
                                     mensagem_bloqueio: str | None = None, canal_alerta: str | None = None,
                                     cargos_liberados: list[str] | None = None, ativo: bool = True) -> dict:
    """Usa o AutoMod nativo do Discord (funciona até com o bot desligado) para bloquear mensagens com
    palavras proibidas e/ou convites de outros servidores. 'golpe' bloqueia a palavra inteira; '*golpe*'
    bloqueia em qualquer parte. Cada chamada substitui a configuração anterior. canal_alerta recebe um
    aviso a cada bloqueio; cargos_liberados (ex.: staff) não são filtrados. ativo=false desliga."""
    gid = await servidor_id()
    regras = await dc("GET", f"/guilds/{gid}/auto-moderation/rules")
    atual = next((r for r in regras if r["name"] == NOME_REGRA_FILTRO), None)
    if not ativo:
        if atual:
            await dc("PATCH", f'/guilds/{gid}/auto-moderation/rules/{atual["id"]}', corpo={"enabled": False})
        return {"ok": True, "filtro": "desligado"}
    lista = [p.strip()[:60] for p in (palavras or []) if p.strip()][:1000]
    regex = [r"discord(?:app)?\.(?:gg|io|me|li|com/invite)/\S+", r"dsc\.gg/\S+"] if bloquear_convites else []
    if not lista and not regex:
        raise ErroDiscord("Passe palavras e/ou bloquear_convites=true.")
    acoes: list[dict[str, Any]] = [{"type": 1, "metadata": {"custom_message": (mensagem_bloqueio or "Mensagem bloqueada pelo filtro do ECO PULSE.")[:150]}}]
    if canal_alerta:
        acoes.append({"type": 2, "metadata": {"channel_id": (await achar_canal(canal_alerta, tipos={0, 5}))["id"]}})
    isentos = [(await achar_cargo(c))["id"] for c in (cargos_liberados or [])][:20]
    corpo = {"name": NOME_REGRA_FILTRO, "event_type": 1, "trigger_type": 1,
             "trigger_metadata": {"keyword_filter": lista, "regex_patterns": regex},
             "actions": acoes, "enabled": True, "exempt_roles": isentos}
    if atual:
        corpo.pop("trigger_type")
        corpo.pop("event_type")
        await dc("PATCH", f'/guilds/{gid}/auto-moderation/rules/{atual["id"]}', corpo=corpo, motivo="Agente ECO PULSE")
    else:
        await dc("POST", f"/guilds/{gid}/auto-moderation/rules", corpo=corpo, motivo="Agente ECO PULSE")
    return {"ok": True, "filtro": "ligado", "palavras": len(lista), "bloqueia_convites": bloquear_convites,
            "alerta_em": canal_alerta, "cargos_liberados": len(isentos)}


# Importados no fim: estes módulos também usam este aqui (evita import circular).
from ..agendamento import NOMES_REPETICAO, REPETICOES, _ler_quando
from ..busca import achar_canal, achar_cargo
from ..config import FUSO
from ..discord_api import ErroDiscord, dc
from ..gateway import _bot_estado
from ..memoria import _cfg, _cfg_estado, exigir_config, garantir_config, registrar, salvar_config
from ..paineis import _guardar_imagem
from ..util import (
    TIPOS_MENSAGEM,
    _agora,
    _emoji_chave,
    _emoji_url,
    _fmt,
    _norm,
    _norm_frase,
    montar_mensagem,
    servidor_id,
)
