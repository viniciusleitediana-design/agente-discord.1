# Arquitetura

## Visão geral

Um único processo Python roda três coisas juntas:

1. **API web** (Starlette + Uvicorn), com o conector MCP, a rota `/saude` e as imagens em `/midia`.
2. **Gateway do Discord** (discord.py), que recebe entradas, mensagens, reações e cliques em botões, menus e formulários.
3. **Agendador**, que roda a cada 20 segundos: mensagens agendadas, sorteios, tickets, canais temporários, vendas e a fila da equipe.

Todas as chamadas ao Discord passam por `discord_api.dc()`, que respeita o limite de requisições e traduz os erros para português.

## Onde os dados ficam

O disco do Render é apagado a cada deploy, por isso tudo é guardado no próprio Discord:

| O quê | Onde | Como |
| --- | --- | --- |
| Configuração (painéis, tickets, sorteios, automações, loja) | `#agente-config` | JSON anexado numa mensagem, regravado a cada mudança |
| Banco de vendas (SQLite) | `🗄️・backups-bot` | Cópia anexada depois de cada alteração (ficam as últimas 10), restaurada ao ligar |
| Arquivos de entrega | `📁・arquivos-entrega` | Uma mensagem por arquivo, copiada para cada entrega |
| Imagens de painéis | `#agente-config` | Reenviadas como anexo para não expirar |

Keys, logins e nomes de pagadores ficam **cifrados** no banco (Fernet, `CHAVE_COFRE`). Repetições são detectadas por HMAC, sem guardar a key em texto puro.

## Fluxo de uma venda

```
menu do painel ─► pedido (SQLite) ─► canal privado de pagamento com Pix exato
      ─► cliente: CONFIRMAR PAGAMENTO + nome do pagador ─► AGUARDANDO_CONFERENCIA ─► alerta na central
      ─► FUNDADOR: APROVAR (digitando CONFIRMO) ─► key reservada numa transação
      ─► canal privado de entrega: resumo → passo a passo/links → arquivos → login → "Key: …"
```

- As mudanças de status usam `UPDATE … WHERE status = ?` e transações `BEGIN IMMEDIATE`, então nada é aprovado nem entregue duas vezes.
- Sem estoque, o pedido fica em `AGUARDANDO_ESTOQUE` e sai sozinho quando entram keys.
- Uma entrega interrompida (queda, deploy) é retomada com a **mesma** key reservada.
- Os botões usam `custom_id` sem estado (`ecvd:…`, `ecot:…`, `ecos:…`), por isso continuam funcionando depois de reinícios.

## Módulos

- **Base:** `config`, `estado`, `discord_api`, `util`, `busca`, `interface`, `pix`
- **Comunidade:** `paineis`, `tickets`, `verificacao`, `sorteios`, `gateway`, `agendamento`, `memoria`
- **Loja e vendas:** `loja`, `vendas/` (`base`, `cofre`, `banco`, `backup`, `paineis`, `canais`, `pedido`, `compra`, `entrega`, `comandos`, `status`)
- **Equipe:** `central` (fila ao vivo e alertas)
- **Conector:** `conector` e `ferramentas/`
- **Aplicação:** `app`

Os módulos de base não dependem dos outros. Quem é importado só para chamar funções vem no fim do arquivo, o que evita import circular entre módulos que se chamam (por exemplo, `vendas.entrega` ↔ `central`).
