# ECO PULSE — Agente do Discord

Conector MCP que deixa o Claude controlar o servidor ECO PULSE e mantém automações rodando no próprio bot, 24 horas.

## O que faz

- **Canais:** listar, criar (inclusive privados), editar, apagar, permissões, trancar
- **Mensagens:** enviar com embed e botão de link, editar, ler, limpar em massa, fixar, reagir, enquete, DM
- **Automações:** mensagens agendadas/repetidas, boas-vindas com cargo automático, despedida, respostas automáticas, cargos por reação, canal de registros, filtro de palavras e convites (AutoMod)
- **Cargos e moderação:** criar/editar/apagar cargos, dar/tirar cargo, apelido, castigo, expulsar, banir, desbanir

As automações ficam salvas no canal privado `#agente-config` do próprio servidor, então sobrevivem a reinícios do Render.

## Render

- Build: `pip install -r requirements.txt`
- Start: `python server.py`
- Variáveis: `DISCORD_TOKEN` (obrigatória), `GUILD_ID`, `CHAVE_SECRETA`, `FUSO`, `MANTER_ACORDADO` (opcionais; detalhes no topo do `server.py`)

## Discord

- Developer Portal → Bot: ligar **SERVER MEMBERS INTENT** e **MESSAGE CONTENT INTENT**
- Cargo do bot com **Administrador** e acima dos cargos que ele gerencia
