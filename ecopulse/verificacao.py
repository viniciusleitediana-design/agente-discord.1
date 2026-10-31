"""Painel de verificação: o botão dá o cargo de membro."""

from .discord_api import _Resposta

# ── verificação ──

async def _verificar(r: _Resposta, pid: str) -> None:
    inter = r.inter
    await r.adiar()
    await exigir_config()
    painel = _cfg["paineis"].get(pid)
    if not painel or painel.get("tipo") != "verificacao":
        await r.efemera("Este painel não está mais ativo. Avise a equipe.")
        return
    uid = str(inter.user.id)
    gid = await servidor_id()
    cargos = _ids_cargos(inter.user)
    if painel["cargo_id"] in cargos and not (painel.get("tirar_cargo_id") and painel["tirar_cargo_id"] in cargos):
        await r.efemera("✅ Você já está verificado!")
        return
    await dc("PUT", f'/guilds/{gid}/members/{uid}/roles/{painel["cargo_id"]}', motivo="Verificação")
    if painel.get("tirar_cargo_id") and painel["tirar_cargo_id"] in cargos:
        try:
            await dc("DELETE", f'/guilds/{gid}/members/{uid}/roles/{painel["tirar_cargo_id"]}', motivo="Verificação")
        except ErroDiscord as erro:
            log.warning("Não consegui tirar o cargo de não verificado: %s", erro)
    await r.efemera(painel.get("mensagem_sucesso") or "✅ Verificado! Agora você tem acesso ao servidor. Seja bem-vindo(a)!")
    await registrar(f'✅ <@{uid}> se verificou e ganhou o cargo **{painel.get("cargo_nome")}**.')


# Importados no fim: estes módulos também usam este aqui (evita import circular).
from .config import log
from .discord_api import ErroDiscord, dc
from .loja import _ids_cargos
from .memoria import _cfg, exigir_config, registrar
from .util import servidor_id
