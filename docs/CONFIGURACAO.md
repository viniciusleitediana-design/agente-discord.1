# Configuração

## 1. Discord Developer Portal

1. Crie a aplicação e o bot em <https://discord.com/developers/applications>.
2. Em **Bot**, ligue **SERVER MEMBERS INTENT** e **MESSAGE CONTENT INTENT**.
3. Convide o bot com o escopo `bot applications.commands` e a permissão **Administrador**.
4. No servidor, arraste o cargo do bot para cima dos cargos que ele vai gerenciar.

## 2. Render

| Campo | Valor |
| --- | --- |
| Build Command | `pip install -r requirements.txt` |
| Start Command | `python server.py` |

O serviço se cutuca a cada 10 minutos (`MANTER_ACORDADO`) para o plano grátis não dormir. Como o disco do Render é apagado a cada deploy, o bot guarda tudo no Discord (veja [ARQUITETURA.md](ARQUITETURA.md)).

## 3. Variáveis de ambiente

| Variável | Obrigatória | Para que serve |
| --- | --- | --- |
| `DISCORD_TOKEN` | sim | Token do bot |
| `CHAVE_SECRETA` | para o conector | Caminho secreto do endereço do conector: `https://SEU-APP.onrender.com/CHAVE_SECRETA/mcp`. Sem ela, o conector fica desligado. **Nunca coloque no código.** |
| `GUILD_ID` | não | ID do servidor. Só precisa se o bot estiver em mais de um. |
| `CHAVE_COFRE` | vendas | Chave Fernet que cifra keys, logins e nomes de pagadores. **Não troque depois de cadastrar keys.** |
| `PIX_CHAVE` | loja e vendas | Chave Pix que recebe os pagamentos |
| `PIX_NOME` / `PIX_CIDADE` | não | Nome (até 25 letras) e cidade (até 15) que aparecem no Pix |
| `PIX_LINK` | não | Link de pagamento extra mostrado no pedido |
| `PIX_COPIA_COLA` | não | Código Pix fixo pronto. O valor dele não muda com o preço. |
| `FUSO` | não | Padrão `America/Sao_Paulo` |
| `MANTER_ACORDADO` | não | `1` (padrão) ou `0` |
| `CONFIG_CANAL_ID` | não | Canal onde a configuração fica salva (padrão: cria `#agente-config`) |
| `VENDAS_DB` | não | Caminho do banco SQLite das vendas (padrão `dados/vendas.db`) |

Para gerar a `CHAVE_COFRE`:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

## 4. Primeiros passos no servidor

1. `/painel_vendas_publicar` publica os painéis de venda nos canais dos jogos.
2. `/produto_configurar` ajusta preço, duração e se o plano está à venda.
3. `/key_adicionar` cadastra keys, digitadas ou por arquivo `.txt` (uma por linha; títulos e numeração são ignorados).
4. `/entrega_configurar` cadastra o passo a passo, o login, os links e até 5 arquivos que vão junto em toda entrega.
5. `/ticket_painel` e `/verificacao_painel` publicam os painéis de suporte e de verificação.
6. Crie os canais `📋・fila-de-atendimento` e `🔔・alertas`, visíveis só para a equipe, e o bot passa a usá-los sozinho.

Só o cargo **FUNDADOR** aprova pagamentos e mexe nas vendas. A permissão é conferida no servidor a cada clique, e não só pela visibilidade do botão.
