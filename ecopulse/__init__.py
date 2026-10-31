"""ECO PULSE — Agente do Discord
=============================
Conector MCP que deixa o Claude controlar o servidor ECO PULSE e mantém
automações rodando no próprio bot, 24 horas, mesmo com o Claude fechado.

O que o agente faz
- Canais: listar, criar, editar, apagar, permissões, trancar/destrancar
- Mensagens: enviar (texto, embed e botão de link), editar, apagar, ler,
  limpar em massa, fixar, reagir, enquete e DM
- Automações: mensagens agendadas e repetidas, boas-vindas, despedida,
  respostas automáticas, cargos por reação, canal de registros e filtro de
  palavras/convites (AutoMod nativo do Discord)
- Cargos, membros e moderação: criar/editar/apagar cargos, dar/tirar cargo,
  apelido, castigo, expulsar, banir e desbanir

Variáveis de ambiente (Render → Environment)
- DISCORD_TOKEN    obrigatória: token do bot
- GUILD_ID         opcional: ID do servidor (se o bot só estiver em um, é detectado sozinho)
- CHAVE_SECRETA    obrigatória para usar o conector: caminho secreto do endereço
                   (https://SEU-APP.onrender.com/CHAVE_SECRETA/mcp). Sem ela, o conector
                   fica desligado (o bot e as automações continuam funcionando).
- FUSO             opcional: padrão America/Sao_Paulo
- MANTER_ACORDADO  opcional: 1 (padrão) faz o serviço se cutucar a cada 10 min
                   para o plano grátis do Render não dormir
- CONFIG_CANAL_ID  opcional: canal onde as automações ficam salvas
                   (padrão: cria o canal privado #agente-config)

Loja (compra em chat privado com Pix)
- PIX_CHAVE        chave Pix que recebe os pagamentos (e-mail, celular no formato
                   +5511999999999, CPF/CNPJ só números ou chave aleatória). Com ela o
                   bot gera o QR Code e o "copia e cola" com o valor de cada produto.
- PIX_NOME         opcional: nome que aparece no Pix (padrão ECO PULSE, até 25 letras)
- PIX_CIDADE       opcional: cidade do Pix (padrão SAO PAULO, até 15 letras)
- PIX_COPIA_COLA   opcional: código Pix fixo pronto (usado no lugar da PIX_CHAVE;
                   o valor dele não muda com o preço do produto)

Comando de início no Render: python server.py
"""
