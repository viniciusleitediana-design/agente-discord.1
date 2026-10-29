# ECO PULSE — Agente do Discord

Conector MCP que deixa o Claude controlar o servidor ECO PULSE e mantém automações rodando no próprio bot, 24 horas.

## O que faz

- **Canais:** listar, criar (inclusive privados), editar, apagar, permissões, trancar
- **Mensagens:** enviar com embed e botão de link, editar, ler, limpar em massa, fixar, reagir, enquete, DM
- **Automações:** mensagens agendadas/repetidas, boas-vindas com cargo automático, despedida, respostas automáticas, cargos por reação, canal de registros, filtro de palavras e convites (AutoMod)
- **Cargos e moderação:** criar/editar/apagar cargos, dar/tirar cargo, apelido, castigo, expulsar, banir, desbanir
- **Comunidade:** painel de **ticket** (canal privado com a equipe, assumir, fechar com histórico .txt), painel de **verificação** (botão dá cargo), **sorteios** (participar, sorteio automático na hora, ressortear) e `ver_mensagem` + `copiar_de` para copiar painéis de outros bots
- **Loja:** painel com botão **Comprar agora** → chat privado (comprador + Fundador) com QR Code e Pix copia e cola → **Confirmar pagamento** com nome completo → o Fundador confirma (produto entregue por DM na hora, tirado do canal de estoque) ou recusa (chat fechado)

As automações e as compras em andamento ficam salvas no canal privado `#agente-config` do próprio servidor, então sobrevivem a reinícios do Render.

### Loja

- Ferramentas do conector: `configurar_produto`, `publicar_painel_compra`, `ver_loja`
- Estoque: cada mensagem no canal de estoque do produto = 1 entrega (a mais antiga sai primeiro; mensagens fixadas são ignoradas)
- Chats sem pagamento informado fecham sozinhos em 24 h; depois da entrega por DM, fecham em 5 min

## Render

- Build: `pip install -r requirements.txt`
- Start: `python server.py`
- Variáveis: `DISCORD_TOKEN` (obrigatória), `GUILD_ID`, `CHAVE_SECRETA`, `FUSO`, `MANTER_ACORDADO` (opcionais; detalhes no topo do `server.py`)
- Loja: `PIX_CHAVE` (a chave Pix que recebe), `PIX_NOME` e `PIX_CIDADE` (opcionais)

## Discord

- Developer Portal → Bot: ligar **SERVER MEMBERS INTENT** e **MESSAGE CONTENT INTENT**
- Cargo do bot com **Administrador** e acima dos cargos que ele gerencia
