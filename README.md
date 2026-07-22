# Bot de Alerta 0x0 — Passo a Passo Completo

Avisa no Telegram sempre que uma partida das ligas configuradas terminar 0 a 0.

Usa a **API-Football**, com 4 chaves alternadas por horário do dia para multiplicar o limite gratuito. Verifica a cada **10 minutos**. Das 0h às 7h o bot fica pausado.

---

## Passo 1 — Criar 4 contas gratuitas na API-Football

Cada conta grátis dá 100 requisições/dia.

1. Acesse https://dashboard.api-football.com/register
2. Cadastre-se (pode usar e-mails diferentes para cada conta — repita esse passo 4 vezes).
3. Em cada conta, vá em **"My Access"** e copie a **API Key**.
4. Guarde as 4 chaves numeradas (chave 1, 2, 3 e 4) — você vai usá-las no Passo 5.

## Passo 2 — Conferir as ligas que serão acompanhadas

Abra o arquivo `main.py` e olhe a lista `LIGAS`, no topo. Ela já vem com as principais ligas:

```python
LIGAS = [
    71,   # Brasileirão Série A
    39,   # Premier League
    2,    # Champions League
    140,  # La Liga
    135,  # Serie A (Itália)
    61,   # Ligue 1
    78,   # Bundesliga
]
```

Para adicionar ou remover uma liga, edite essa lista com os IDs da tabela abaixo (ou pesquise outros em https://dashboard.api-football.com/soccer/ids/leagues):

| ID  | Competição                  |
|-----|------------------------------|
| 71  | Brasileirão Série A          |
| 72  | Brasileirão Série B          |
| 39  | Premier League (Inglaterra)  |
| 2   | Champions League             |
| 3   | Europa League                 |
| 140 | La Liga (Espanha)             |
| 135 | Serie A (Itália)               |
| 61  | Ligue 1 (França)                |
| 78  | Bundesliga (Alemanha)           |
| 94  | Primeira Liga (Portugal)        |
| 253 | MLS (EUA)                       |
| 13  | Copa Libertadores                |
| 11  | Copa Sul-Americana                |

## Passo 3 — Criar o repositório no GitHub

1. Acesse https://github.com/new
2. Crie um repositório (pode ser privado).
3. Faça upload dos 3 arquivos deste projeto: `main.py`, `requirements.txt`, `Procfile`.

## Passo 4 — Criar o projeto no Railway

1. Acesse https://railway.app e faça login.
2. Clique em **"New Project" → "Deploy from GitHub repo"**.
3. Selecione o repositório que você criou no Passo 3.

## Passo 5 — Configurar as variáveis de ambiente

Dentro do projeto no Railway, vá na aba **Variables** e adicione, uma por uma:

| Variável              | Valor                                    |
|-----------------------|-------------------------------------------|
| `API_FOOTBALL_KEY_1`  | chave da conta 1 (usada das 07h às 10h)   |
| `API_FOOTBALL_KEY_2`  | chave da conta 2 (usada das 10h às 15h)   |
| `API_FOOTBALL_KEY_3`  | chave da conta 3 (usada das 15h às 19h)   |
| `API_FOOTBALL_KEY_4`  | chave da conta 4 (usada das 19h às 24h)   |
| `TELEGRAM_TOKEN`      | token do seu bot (do @BotFather)          |
| `TELEGRAM_CHAT_ID`    | seu chat_id                                |

## Passo 6 — Deploy

1. Railway detecta o `Procfile` automaticamente e sobe o bot como um **worker** contínuo.
2. Depois do deploy, vá na aba **Deployments → View Logs** para confirmar que está rodando — você deve ver mensagens como `Nenhum novo jogo 0x0 nesta verificação.` a cada 10 minutos.
3. Você também deve receber no Telegram a mensagem inicial: *"🤖 Bot de alerta 0x0 iniciado!"*

Pronto — o bot está no ar.

---

## Como funciona por baixo dos panos

- **A cada 10 minutos**, o script busca os jogos finalizados de ontem e de hoje (2 requisições) e filtra pelas ligas configuradas em `LIGAS`.
- **A chave usada** em cada verificação muda automaticamente de acordo com a hora (fuso de Maceió/Brasília, UTC-3):

| Horário       | Chave usada             |
|---------------|---------------------------|
| 07h às 10h    | `API_FOOTBALL_KEY_1`      |
| 10h às 15h    | `API_FOOTBALL_KEY_2`      |
| 15h às 19h    | `API_FOOTBALL_KEY_3`      |
| 19h às 24h    | `API_FOOTBALL_KEY_4`      |
| 00h às 07h    | bot pausado, nada é verificado |

- Das 0h às 7h o bot não faz nenhuma requisição. Como ele sempre olha "ontem + hoje", os jogos 0x0 da madrugada ainda são notificados quando ele volta a rodar às 7h — só chegam um pouco mais tarde.
- Jogos já notificados ficam salvos em `notificados.json`, para não repetir o aviso.

## Sobre os limites de requisições

Com verificação a cada 10 minutos (2 requisições cada), o uso por faixa de horário fica assim:

| Faixa       | Duração | Verificações | Requisições usadas | Limite da chave |
|-------------|---------|----------------|----------------------|-------------------|
| 07h-10h     | 3h      | 18             | 36                    | 100                |
| 10h-15h     | 5h      | 30             | 60                    | 100                |
| 15h-19h     | 4h      | 24             | 48                    | 100                |
| 19h-24h     | 5h      | 30             | 60                    | 100                |

Todas as faixas ficam bem abaixo do limite de 100/dia de cada conta.

## Editando parâmetros no `main.py`

- **Ligas acompanhadas:** variável `LIGAS`.
- **Intervalo de verificação:** variável `INTERVALO_SEGUNDOS` (hoje em 600 = 10 minutos).
- **Faixas de horário/chaves:** função `obter_chave_api()`.
- **Horário de pausa:** função `em_horario_de_pausa()`.
