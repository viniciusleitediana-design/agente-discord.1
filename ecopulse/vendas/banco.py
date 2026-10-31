"""Banco SQLite das vendas: conexão, transações, consultas e auditoria."""

import asyncio
import secrets
import sqlite3
from typing import Any

from .. import estado

# ── banco ──

def _agora_iso() -> str:
    return _agora().isoformat()


def _abrir_db(caminho: str) -> sqlite3.Connection:
    conn = sqlite3.connect(caminho, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA_VENDAS)
    colunas = {c["name"] for c in conn.execute("PRAGMA table_info(entregas_config)")}
    for nome, tipo in (("arquivo_canal", "TEXT"), ("arquivo_msg", "TEXT"), ("arquivo_nome", "TEXT"), ("arquivo_tamanho", "INTEGER")):
        if nome not in colunas:  # bancos antigos (restaurados do backup) ganham as colunas novas
            conn.execute(f"ALTER TABLE entregas_config ADD COLUMN {nome} {tipo}")
    # versão 4.0 guardava 1 arquivo por plano em entregas_config: passa para a tabela de vários arquivos
    conn.execute("INSERT OR IGNORE INTO entregas_arquivos (jogo, plano, nome, canal_id, mensagem_id, tamanho, adicionado_por, "
                 "adicionado_em) SELECT jogo, plano, arquivo_nome, arquivo_canal, arquivo_msg, arquivo_tamanho, atualizado_por, "
                 "atualizado_em FROM entregas_config WHERE arquivo_msg IS NOT NULL")
    conn.execute("UPDATE entregas_config SET arquivo_canal = NULL, arquivo_msg = NULL, arquivo_nome = NULL, arquivo_tamanho = NULL "
                 "WHERE arquivo_msg IS NOT NULL")
    return conn


def _q(sql: str, args: tuple = ()) -> list[sqlite3.Row]:
    assert estado._db is not None
    return estado._db.execute(sql, args).fetchall()


def _q1(sql: str, args: tuple = ()) -> sqlite3.Row | None:
    assert estado._db is not None
    return estado._db.execute(sql, args).fetchone()


class _Transacao:
    """BEGIN IMMEDIATE … COMMIT. Nenhum await dentro: o bloco inteiro roda sem ser interrompido."""

    def __enter__(self) -> sqlite3.Connection:
        assert estado._db is not None
        estado._db.execute("BEGIN IMMEDIATE")
        return estado._db

    def __exit__(self, tipo, valor, tb) -> bool:
        assert estado._db is not None
        if tipo is None:
            estado._db.execute("COMMIT")
            _vendas["escritas"] += 1
            _backup_depois()
            _fila_depois()
        else:
            estado._db.execute("ROLLBACK")
        return False


def _tx() -> _Transacao:
    if estado._db is None or not _vendas["pronto"]:
        raise ErroDiscord("O sistema de vendas está iniciando. Tente de novo em alguns segundos.")
    return _Transacao()


def _auditar(conn: sqlite3.Connection, acao: str, pedido_id: str | None = None, ator: str | None = None, detalhe: str = "") -> None:
    conn.execute("INSERT INTO auditoria (quando, pedido_id, ator_id, acao, detalhe) VALUES (?, ?, ?, ?, ?)",
                 (_agora_iso(), pedido_id, ator, acao, detalhe[:500]))


def _cfg_vendas(chave: str, padrao: str | None = None) -> str | None:
    linha = _q1("SELECT valor FROM config WHERE chave = ?", (chave,))
    return linha["valor"] if linha and linha["valor"] else padrao


def _semear(conn: sqlite3.Connection) -> None:
    agora = _agora_iso()
    for i, (jid, nome, plat, emoji, canal) in enumerate(JOGOS_PADRAO):
        conn.execute("INSERT OR IGNORE INTO jogos (id, nome, plataforma, emoji, canal_id, ordem) VALUES (?, ?, ?, ?, ?, ?)",
                     (jid, nome, plat, emoji, canal, i))
        for pid, pnome, dias, preco in PLANOS_PADRAO:
            conn.execute("INSERT OR IGNORE INTO produtos (jogo, plano, nome, dias, preco_centavos, atualizado_em) "
                         "VALUES (?, ?, ?, ?, ?, ?)", (jid, pid, pnome, dias, preco, agora))


def _jogo(jid: str) -> sqlite3.Row:
    j = _q1("SELECT * FROM jogos WHERE id = ?", (jid,))
    if not j:
        raise ErroDiscord(f'Jogo "{jid}" não existe. Use: {", ".join(x[0] for x in JOGOS_PADRAO)}.')
    return j


def _produto(jid: str, plano: str) -> sqlite3.Row:
    p = _q1("SELECT * FROM produtos WHERE jogo = ? AND plano = ?", (jid, plano))
    if not p:
        raise ErroDiscord(f'Plano "{plano}" não existe. Use: {", ".join(x[0] for x in PLANOS_PADRAO)}.')
    return p


def _rotulo_jogo(j: sqlite3.Row) -> str:
    return f'{j["nome"]} • {j["plataforma"]}'


def _duracao(dias: int | None) -> str:
    return "Permanente" if not dias else f'{dias} dia{"s" if dias > 1 else ""}'


def _reais_c(centavos: int) -> str:
    return "R$ " + f"{centavos / 100:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _estoque(jid: str, plano: str) -> dict:
    """Disponíveis no cofre e quanto disso já está 'prometido' para pedidos em andamento."""
    disp = _q1("SELECT COUNT(*) n FROM keys WHERE jogo = ? AND plano = ? AND status = 'disponivel'", (jid, plano))["n"]
    abertos = _q1(f"SELECT COUNT(*) n FROM pedidos WHERE jogo = ? AND plano = ? AND key_id IS NULL AND status IN "
                  f"({','.join('?' * len(STATUS_ABERTOS_VENDA))})", (jid, plano, *STATUS_ABERTOS_VENDA))["n"]
    return {"disponiveis": disp, "em_aberto": abertos, "livre": max(0, disp - abertos)}


def _eh_fundador(inter: Any) -> bool:
    """Só o cargo FUNDADOR (validado aqui no servidor, em toda interação)."""
    cargo = _cfg_vendas("cargo_fundador_id")
    return bool(cargo) and cargo in _ids_cargos(inter.user)


def _lock_pedido(pid: str) -> asyncio.Lock:
    if pid not in _locks_pedido:
        _locks_pedido[pid] = asyncio.Lock()
    return _locks_pedido[pid]


def _novo_id_pedido() -> str:
    while True:
        pid = "ECO-" + secrets.token_hex(4).upper()
        if not _q1("SELECT 1 FROM pedidos WHERE id = ?", (pid,)):
            return pid


# Importados no fim: estes módulos também usam este aqui (evita import circular).
from ..central import _fila_depois
from ..discord_api import ErroDiscord
from ..loja import _ids_cargos
from ..util import _agora
from .backup import _backup_depois
from .base import JOGOS_PADRAO, PLANOS_PADRAO, SCHEMA_VENDAS, STATUS_ABERTOS_VENDA, _locks_pedido, _vendas
