"""Vendas automáticas de keys: constantes, jogos, planos, status e esquema do banco."""

import asyncio
import os
import secrets
from datetime import timedelta
from typing import Any

from ..config import RAIZ_PROJETO, _env

#
# Fluxo: painel com menu (1 por canal de jogo) → pedido no SQLite → canal privado de pagamento com Pix exato →
# cliente confirma (formulário com nome do pagador) → só o cargo FUNDADOR aprova (digitando CONFIRMO) ou rejeita
# → a key sai do estoque (cofre cifrado) para um NOVO canal privado de entrega.
#
# O disco do Render é apagado a cada deploy, então o banco é copiado (já cifrado nas partes sensíveis) para um
# canal privado do servidor depois de cada alteração e restaurado automaticamente quando o bot liga.

NEON = 0x39FF14
VENDAS_DB = _env("VENDAS_DB") or os.path.join(RAIZ_PROJETO, "dados", "vendas.db")
ARQ_BACKUP_VENDAS = "vendas-eco.sqlite"
MANTER_BACKUPS = 10
ESPERA_PAGAMENTO_VENDA = timedelta(hours=24)
APAGAR_PAGAMENTO_APOS_ENTREGA = timedelta(minutes=30)
APAGAR_PAGAMENTO_APOS_REJEICAO = timedelta(minutes=10)
APAGAR_PAGAMENTO_APOS_CANCELAR = timedelta(seconds=20)
APAGAR_PAGAMENTO_APOS_EXPIRAR = timedelta(minutes=2)

# (id, nome, plataforma, emoji, canal) — os canais reais do servidor, pelos IDs
JOGOS_PADRAO = [
    ("cs2", "CS2", "PC", "🎯", "1563252420497379437"),
    ("roblox-emulador", "Roblox", "Emulador", "🧱", "1563259646880514150"),
    ("roblox-mobile", "Roblox", "Mobile", "📱", "1563640176667005028"),
    ("free-fire-emulador", "Free Fire", "Emulador", "🔥", "1563640365561413712"),
    ("free-fire-mobile", "Free Fire", "Mobile", "📱", "1563640449363869746"),
]
# (id, nome, dias (None = permanente), preço em centavos)
PLANOS_PADRAO = [
    ("1d", "Key 1 dia", 1, 390),
    ("7d", "Key 7 dias", 7, 1790),
    ("15d", "Key 15 dias", 15, 3290),
    ("30d", "Key 30 dias", 30, 5490),
    ("perm", "Key permanente", None, 9900),
]
_ORDEM_PLANOS = {p[0]: i for i, p in enumerate(PLANOS_PADRAO)}

AG_PAGAMENTO, AG_CONFERENCIA = "AGUARDANDO_PAGAMENTO", "AGUARDANDO_CONFERENCIA"
APROVADO, ENTREGANDO, AG_ESTOQUE, ENTREGUE = "APROVADO", "ENTREGANDO", "AGUARDANDO_ESTOQUE", "ENTREGUE"
REJEITADO, CANCELADO, EXPIRADO = "REJEITADO", "CANCELADO", "EXPIRADO"
STATUS_ABERTOS_VENDA = (AG_PAGAMENTO, AG_CONFERENCIA, APROVADO, ENTREGANDO, AG_ESTOQUE)
ROTULO_STATUS = {
    AG_PAGAMENTO: "⏳ Aguardando pagamento", AG_CONFERENCIA: "🔎 Aguardando conferência da equipe",
    APROVADO: "✅ Aprovado • preparando entrega", ENTREGANDO: "📦 Entregando", AG_ESTOQUE: "⚠️ Aprovado • aguardando estoque",
    ENTREGUE: "✅ Entregue", REJEITADO: "❌ Rejeitado", CANCELADO: "🗑️ Cancelado", EXPIRADO: "⌛ Expirado",
}
_vendas: dict[str, Any] = {"pronto": False, "aviso": "iniciando", "restaurado": None, "escritas": 0,
                           "instancia": secrets.token_hex(3), "backup_msg": None, "rechecagens": 0, "iniciado": 0.0}
_vendas_lock = asyncio.Lock()
_locks_pedido: dict[str, asyncio.Lock] = {}
_cliques_menu: dict[str, float] = {}

SCHEMA_VENDAS = """
CREATE TABLE IF NOT EXISTS config (chave TEXT PRIMARY KEY, valor TEXT);
CREATE TABLE IF NOT EXISTS jogos (
    id TEXT PRIMARY KEY, nome TEXT NOT NULL, plataforma TEXT NOT NULL, emoji TEXT, canal_id TEXT,
    mensagem_id TEXT, descricao TEXT, imagem_url TEXT, ordem INTEGER DEFAULT 0, ativo INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS produtos (
    jogo TEXT NOT NULL, plano TEXT NOT NULL, nome TEXT NOT NULL, dias INTEGER, preco_centavos INTEGER NOT NULL,
    ativo INTEGER NOT NULL DEFAULT 1, usa_keys INTEGER NOT NULL DEFAULT 1, link_pagamento TEXT, atualizado_em TEXT,
    PRIMARY KEY (jogo, plano));
CREATE TABLE IF NOT EXISTS keys (
    id INTEGER PRIMARY KEY AUTOINCREMENT, jogo TEXT NOT NULL, plano TEXT NOT NULL, valor_cifrado TEXT NOT NULL,
    hash TEXT NOT NULL UNIQUE, final TEXT, status TEXT NOT NULL DEFAULT 'disponivel', pedido_id TEXT,
    adicionada_por TEXT, adicionada_em TEXT, entregue_em TEXT, validade_dias INTEGER, expira_em TEXT,
    revogada_por TEXT, revogada_em TEXT, motivo_revogacao TEXT);
CREATE INDEX IF NOT EXISTS keys_estoque ON keys (jogo, plano, status);
CREATE TABLE IF NOT EXISTS pedidos (
    id TEXT PRIMARY KEY, usuario_id TEXT NOT NULL, usuario_nome TEXT, jogo TEXT NOT NULL, plano TEXT NOT NULL,
    produto_nome TEXT, dias INTEGER, preco_centavos INTEGER NOT NULL, status TEXT NOT NULL,
    canal_pagamento_id TEXT, mensagem_pedido_id TEXT, canal_entrega_id TEXT, pagador_cifrado TEXT,
    criado_em TEXT NOT NULL, informado_em TEXT, aprovado_por TEXT, aprovado_em TEXT, rejeitado_por TEXT,
    rejeitado_em TEXT, motivo_rejeicao TEXT, cancelado_por TEXT, entregue_em TEXT, key_id INTEGER,
    entregando_desde TEXT, fechar_pagamento_em TEXT, pagamento_apagado INTEGER NOT NULL DEFAULT 0,
    fechar_entrega_em TEXT, entrega_apagada INTEGER NOT NULL DEFAULT 0, link_pagamento TEXT);
CREATE INDEX IF NOT EXISTS pedidos_status ON pedidos (status);
CREATE INDEX IF NOT EXISTS pedidos_usuario ON pedidos (usuario_id, status);
CREATE TABLE IF NOT EXISTS entregas_config (
    jogo TEXT NOT NULL, plano TEXT NOT NULL, instrucoes TEXT, login_cifrado TEXT, link_download TEXT,
    atualizado_por TEXT, atualizado_em TEXT, PRIMARY KEY (jogo, plano));
CREATE TABLE IF NOT EXISTS entregas_arquivos (
    jogo TEXT NOT NULL, plano TEXT NOT NULL, nome TEXT NOT NULL, canal_id TEXT NOT NULL, mensagem_id TEXT NOT NULL,
    tamanho INTEGER, adicionado_por TEXT, adicionado_em TEXT, PRIMARY KEY (jogo, plano, nome));
CREATE TABLE IF NOT EXISTS auditoria (
    id INTEGER PRIMARY KEY AUTOINCREMENT, quando TEXT NOT NULL, pedido_id TEXT, ator_id TEXT, acao TEXT NOT NULL,
    detalhe TEXT);
"""
