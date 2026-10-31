# Comandos

## Comandos de barra

Entre colchetes estão as opções que não são obrigatórias. Fora o `/ping`, só administradores veem estes comandos, e os de vendas exigem o cargo **FUNDADOR**.

### Geral e comunidade

| Comando | Opções | O que faz |
| --- | --- | --- |
| `/ping` | | Testa se o bot está respondendo |
| `/ticket_painel` | `[canal]` | Publica ou atualiza o painel de tickets |
| `/verificacao_painel` | `[cargo]` `[canal]` | Publica ou atualiza o painel de verificação |

### Loja simples

| Comando | Opções | O que faz |
| --- | --- | --- |
| `/loja_painel` | `[produto]` `[canal]` | Publica ou atualiza o painel de compra de um produto |
| `/vendas` | | Resumo das vendas |
| `/pedidos_pendentes` | | Pedidos esperando conferência, pagamento ou estoque |
| `/aprovar_pagamento` | `[pedido]` | Aprova um pedido depois de conferir o Pix |

### Vendas de keys

| Comando | Opções | O que faz |
| --- | --- | --- |
| `/painel_vendas_publicar` | | Publica ou atualiza os painéis de venda dos jogos |
| `/painel_vendas_atualizar` | `[jogo]` `[plano]` `[preco]` `[ativo]` `[descricao]` `[imagem]` | Muda preços, planos, textos e imagem dos painéis |
| `/produto_configurar` | `jogo` `plano` `[preco]` `[ativo]` `[dias]` `[usa_keys]` `[nome]` `[link_pagamento]` | Configura um plano |
| `/key_adicionar` | `jogo` `plano` `[keys]` `[arquivo]` | Cadastra keys no cofre. Do `.txt` só entram as keys, sem título, numeração ou separadores. |
| `/key_estoque` | `[jogo]` `[plano]` | Mostra o estoque por jogo e plano |
| `/key_consultar` | `[key]` `[pedido]` `[mostrar_completa]` | Consulta uma key ou a key de um pedido |
| `/key_revogar` | `motivo` `[key]` `[pedido]` `[jogo]` `[plano]` `[zerar_estoque]` | Revoga uma key, ou zera o estoque de um plano inteiro |
| `/entrega_configurar` | `jogo` `[plano]` `[arquivo]` `[arquivo2]` `[arquivo3]` `[remover_arquivo]` | Sem arquivo, abre o formulário de passo a passo, login e links (um por linha). Com arquivo, guarda até 5 arquivos que vão em toda entrega (até 10 MB cada sem impulso). |
| `/pedido_consultar` | `pedido` | Mostra o pedido completo, com auditoria |

## Ferramentas do conector (MCP)

São 55 ferramentas, agrupadas como no código (`ecopulse/ferramentas/` e `ecopulse/vendas/status.py`):

| Grupo | Ferramentas |
| --- | --- |
| Canais | `listar_canais` `criar_canal` `editar_canal` `apagar_canal` `permissoes_canal` `trancar_canal` |
| Mensagens | `enviar_mensagem` `editar_mensagem` `apagar_mensagem` `ler_mensagens` `limpar_mensagens` `fixar_mensagem` `reagir` `criar_enquete` `enviar_dm` |
| Automações | `agendar_mensagem` `listar_automacoes` `remover_automacao` `configurar_boas_vindas` `configurar_despedida` `adicionar_resposta_automatica` `criar_cargo_por_reacao` `configurar_logs` `configurar_filtro_palavras` |
| Cargos | `listar_cargos` `criar_cargo` `editar_cargo` `apagar_cargo` `dar_cargo` `tirar_cargo` |
| Membros | `listar_membros` `info_membro` `mudar_apelido` `castigar` `expulsar` `banir` `desbanir` |
| Leitura | `ver_mensagem` `info_canal` |
| Loja | `configurar_produto` `publicar_painel_compra` `ver_loja` `resumo_vendas` |
| Tickets | `publicar_painel_ticket` `fechar_ticket` |
| Verificação | `publicar_painel_verificacao` |
| Sorteios | `criar_sorteio` `encerrar_sorteio` `sortear_de_novo` `cancelar_sorteio` |
| Servidor | `info_servidor` `criar_convite` `status_agente` |
| Vendas | `vendas_status` `vendas_publicar_paineis` |

Ações que apagam, expulsam ou banem pedem confirmação (`confirmado=true`).
