# ECO PULSE Bot

Bot do Discord do servidor **ECO PULSE**: loja com vendas automáticas por Pix, tickets de suporte, verificação, sorteios, boas-vindas e automações. Também tem um **conector MCP**, que permite administrar o servidor por um assistente de IA.

Roda 24 horas no Render (plano grátis), em Python, sem banco externo: as configurações e o banco de vendas ficam guardados no próprio Discord.

## Funcionalidades

| Área | O que faz |
| --- | --- |
| **Vendas de keys** | Painel com menu de planos em cada canal de jogo. Gera o Pix (QR Code e copia e cola) com o valor exato num canal privado de pagamento. O cliente informa o nome de quem pagou e o FUNDADOR confere e aprova. A entrega sai num canal privado com passo a passo, arquivos, login e key. O estoque fica num cofre cifrado. |
| **Loja simples** | Produto com botão "Comprar agora", Pix e entrega automática, com conteúdo fixo ou estoque por mensagem. |
| **Central da equipe** | Fila de atendimento ao vivo, com os pedidos mais antigos primeiro: pagamentos para conferir, tickets sem responsável, pedidos sem estoque e entregas travadas. Alertas chegam num canal só. |
| **Tickets** | Canal privado com a equipe, botão de assumir e fechamento com histórico em `.txt`. |
| **Verificação** | Botão que dá o cargo de membro. |
| **Sorteios** | Botão de participar, sorteio automático na hora marcada, ressorteio e cancelamento. |
| **Automações** | Boas-vindas (canal e DM), despedida, mensagens agendadas, respostas automáticas, cargos por reação, registros e filtro de palavras. |
| **Conector MCP** | 55 ferramentas para administrar canais, mensagens, cargos, membros, painéis e vendas. |

## Estrutura

```
server.py                 ponto de entrada (python server.py)
ecopulse/
├── config.py             variáveis de ambiente e constantes
├── estado.py             estado compartilhado (conexões, banco, tarefas)
├── discord_api.py        chamadas REST ao Discord e respostas a interações
├── util.py · busca.py · interface.py · pix.py
├── memoria.py            configuração salva num canal privado do servidor
├── agendamento.py        rotinas a cada 20 s e mensagens agendadas
├── gateway.py            eventos em tempo real e roteamento das interações
├── comandos.py           comandos de barra (/)
├── central.py            fila de atendimento e alertas da equipe
├── loja.py · paineis.py · tickets.py · verificacao.py · sorteios.py
├── conector.py           servidor MCP
├── ferramentas/          ferramentas do conector (canais, mensagens, cargos…)
├── vendas/               vendas automáticas (banco, cofre, backup, compra, entrega…)
└── app.py                aplicação web, rotas e ciclo de vida
midia/                    imagens públicas (banners)
tests/                    testes com um Discord falso
docs/                     guias de configuração, comandos e arquitetura
```

## Começando

```bash
pip install -r requirements.txt
export DISCORD_TOKEN=...      # token do bot
export CHAVE_SECRETA=...      # caminho secreto do conector
python server.py
```

No Render, use o build `pip install -r requirements.txt` e o start `python server.py`. O passo a passo completo está em [docs/CONFIGURACAO.md](docs/CONFIGURACAO.md).

## Documentação

- [Configuração](docs/CONFIGURACAO.md): variáveis de ambiente, Render, Developer Portal e primeiros passos
- [Comandos](docs/COMANDOS.md): comandos de barra e as 55 ferramentas do conector
- [Arquitetura](docs/ARQUITETURA.md): como o bot é organizado e como os dados ficam salvos

## Testes

```bash
python tests/rodar_testes.py
```

Os testes usam um Discord simulado (`tests/fake_discord*.py`), então nenhuma mensagem é enviada de verdade. A bateria cobre vendas, entrega, central da equipe, tickets, sorteios, comandos, conector e reinícios do serviço.
