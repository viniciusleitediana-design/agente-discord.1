# ECO PULSE — Agente do Discord

Conector MCP que deixa o Claude controlar o servidor ECO PULSE e mantém automações rodando no próprio bot, 24 horas.

## O que faz

- **Canais:** listar, criar (inclusive privados), editar, apagar, permissões, trancar. `editar_canal` reordena sem repetir posições (`posicao`, 0 = primeiro) e troca o canal de regras/avisos da Comunidade (`definir_como`)
- **Mensagens:** enviar com embed e botão de link, editar, ler (`completo=true` traz textos longos inteiros), limpar em massa, fixar, reagir, enquete, DM. `enviar_mensagem` com `painel` = `ticket`/`verificacao` publica esses painéis
- **Automações:** mensagens agendadas/repetidas, boas-vindas com cargo automático, despedida, respostas automáticas, cargos por reação, canal de registros, filtro de palavras e convites (AutoMod)
- **Cargos e moderação:** criar/editar/apagar cargos, dar/tirar cargo, apelido, castigo, expulsar, banir, desbanir
- **Comunidade:** painel de **ticket** (canal privado com a equipe, assumir, fechar com histórico .txt), painel de **verificação** (botão dá cargo), **sorteios** (participar, sorteio automático na hora, ressortear) e `ver_mensagem` + `copiar_de` para copiar painéis de outros bots
- **Comandos de barra** (os mesmos do bot antigo): `/ping`, `/loja_painel`, `/vendas`, `/pedidos_pendentes`, `/aprovar_pagamento`, `/ticket_painel`, `/verificacao_painel` (só administradores veem, menos o /ping)
- **Loja:** painel com botão **Comprar agora** → chat privado (comprador + Fundador) com QR Code e Pix copia e cola → **Confirmar pagamento** com nome completo → o Fundador confirma (o bot cria um **canal privado só do comprador** e manda o produto lá, tirado do canal de estoque; o canal some em 7 dias ou quando o comprador fechar) ou recusa (chat fechado)

- **Central da equipe:** com canais chamados `fila-de-atendimento` e `alertas`, o bot mantém uma fila ao vivo (pagamentos para conferir, tickets sem responsável, aprovados sem estoque, entregas travadas, tickets em atendimento; mais antigos primeiro) e manda 1 alerta por caso novo, mencionando o FUNDADOR só ali

As automações e as compras em andamento ficam salvas no canal privado `#agente-config` do próprio servidor, então sobrevivem a reinícios do Render.

### Loja

- Ferramentas do conector: `configurar_produto`, `publicar_painel_compra`, `ver_loja`
- Estoque: cada mensagem no canal de estoque do produto = 1 entrega (a mais antiga sai primeiro; mensagens fixadas são ignoradas)
- Conteúdo fixo (`conteudo_fixo=true`): a mensagem mais recente do canal vai para todos os compradores e não é apagada
- Chats sem pagamento informado fecham sozinhos em 24 h; depois da entrega, fecham em 5 min

### Vendas automáticas de keys (ECO CHEATS)

- **Painéis**: 1 por canal de jogo (pelos IDs dos canais): CS2, Roblox Emulador, Roblox Mobile, Free Fire Emulador, Free Fire Mobile. Menu com Key 1 dia (R$ 3,90), 7 dias (R$ 17,90), 15 dias (R$ 32,90), 30 dias (R$ 54,90) e permanente (R$ 99,00), com preço e estoque. Os IDs das mensagens ficam no banco: reiniciar só atualiza, nunca duplica.
- **Compra**: escolher no menu → pedido no SQLite (`ECO-XXXXXXXX`) → canal privado `venda-painel-[jogo]-[nome]` (cliente, bot e FUNDADOR) com QR Code, Pix copia e cola do valor exato, link opcional e os botões CONFIRMAR PAGAMENTO / CANCELAR PEDIDO.
- **Pagamento**: CONFIRMAR PAGAMENTO abre formulário com o nome completo do pagador → AGUARDANDO_CONFERENCIA → o FUNDADOR é avisado e vê APROVAR / REJEITAR.
- **Aprovação**: só o cargo FUNDADOR (checado no servidor em todo clique e formulário). Aprovar exige digitar CONFIRMO; fica registrado quem e quando; nunca aprova nem entrega duas vezes. Rejeitar pede o motivo e avisa o cliente.
- **Entrega**: NOVO canal privado `entrega-[jogo]-[nome]` com a key (do cofre), instruções, login, link e arquivo configurados (`/entrega_configurar` com `arquivo`: o bot guarda em `📁・arquivos-entrega` e manda em toda entrega; até 10 MB sem impulso). Sem key no estoque: o pedido fica AGUARDANDO_ESTOQUE, o FUNDADOR é avisado e a entrega sai sozinha quando keys forem adicionadas. Canais de entrega não são apagados automaticamente.
- **Comandos** (só FUNDADOR): `/produto_configurar`, `/key_adicionar`, `/key_estoque`, `/key_consultar`, `/key_revogar`, `/entrega_configurar`, `/pedido_consultar`, `/pedidos_pendentes`, `/painel_vendas_publicar`, `/painel_vendas_atualizar`.
- **Segurança**: SQLite com transações; keys, logins e nomes de pagadores cifrados (variável `CHAVE_COFRE`, não troque depois de cadastrar keys); auditoria de cada passo; pedidos sem pagamento expiram em 24 h; canais de pagamento encerrados são apagados com atraso controlado.
- **Persistência**: o disco do Render é apagado a cada deploy, então o banco é copiado para o canal privado `🗄️・backups-bot` depois de cada alteração (últimas 10 cópias) e restaurado ao ligar. Não apague esse canal.
- **Validade**: o bot não ativa nem desativa keys no programa; a validade é só informação administrativa.

## Render

- Build: `pip install -r requirements.txt`
- Start: `python server.py`
- Variáveis: `DISCORD_TOKEN` (obrigatória), `GUILD_ID`, `CHAVE_SECRETA`, `FUSO`, `MANTER_ACORDADO` (opcionais; detalhes no topo do `server.py`)
- Loja: `PIX_CHAVE` (a chave Pix que recebe), `PIX_NOME` e `PIX_CIDADE` (opcionais), `PIX_LINK` (link de pagamento opcional)
- Vendas: `CHAVE_COFRE` (chave Fernet que cifra keys, logins e nomes; não troque depois de usar)

## Discord

- Developer Portal → Bot: ligar **SERVER MEMBERS INTENT** e **MESSAGE CONTENT INTENT**
- Cargo do bot com **Administrador** e acima dos cargos que ele gerencia
