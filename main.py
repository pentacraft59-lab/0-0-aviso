import requests
import time
import os
import json
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

# ===================== CONFIGURAÇÕES EDITÁVEIS =====================
# Adicione ou remova os IDs das ligas/competições que quer acompanhar.
# IDs de referência (API-Football): veja a tabela no README.md
# Lista completa e atualizada: https://dashboard.api-football.com/soccer/ids/leagues
LIGAS = [
    71,   # Brasileirão Série A
    39,   # Premier League (Inglaterra)
    2,    # Champions League
    140,  # La Liga (Espanha)
    135,  # Serie A (Itália)
    61,   # Ligue 1 (França)
    78,   # Bundesliga (Alemanha)
]

# Intervalo entre cada verificação, em segundos. 600 = 10 minutos.
INTERVALO_SEGUNDOS = 600

# Fuso horário usado para decidir qual chave de API usar.
FUSO_HORARIO = ZoneInfo("America/Maceio")
# =====================================================================

# Chaves de API, uma para cada faixa de horário (contas separadas na API-Football,
# cada uma com seu próprio limite de 100 requisições/dia).
API_FOOTBALL_KEY_1 = os.environ["API_FOOTBALL_KEY_1"]  # 07h-10h
API_FOOTBALL_KEY_2 = os.environ["API_FOOTBALL_KEY_2"]  # 10h-15h
API_FOOTBALL_KEY_3 = os.environ["API_FOOTBALL_KEY_3"]  # 15h-19h
API_FOOTBALL_KEY_4 = os.environ["API_FOOTBALL_KEY_4"]  # 19h-24h

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

ARQUIVO_NOTIFICADOS = "notificados.json"


def obter_chave_api():
    """Escolhe a chave de API de acordo com a hora atual (fuso definido em FUSO_HORARIO)."""
    hora = datetime.now(FUSO_HORARIO).hour

    if 7 <= hora < 10:
        return API_FOOTBALL_KEY_1
    elif 10 <= hora < 15:
        return API_FOOTBALL_KEY_2
    elif 15 <= hora < 19:
        return API_FOOTBALL_KEY_3
    else:  # 19h-24h
        return API_FOOTBALL_KEY_4


def em_horario_de_pausa():
    """Das 00h às 07h o bot não verifica nada (período de sono)."""
    hora = datetime.now(FUSO_HORARIO).hour
    return 0 <= hora < 7


def carregar_notificados():
    try:
        with open(ARQUIVO_NOTIFICADOS, "r") as f:
            return set(json.load(f))
    except FileNotFoundError:
        return set()


def salvar_notificados(notificados):
    with open(ARQUIVO_NOTIFICADOS, "w") as f:
        json.dump(list(notificados), f)


def enviar_telegram(mensagem):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": mensagem}
    try:
        r = requests.post(url, data=payload, timeout=10)
        r.raise_for_status()
    except Exception as e:
        print(f"Erro ao enviar mensagem no Telegram: {e}")


def buscar_jogos_finalizados():
    headers = {"x-apisports-key": obter_chave_api()}
    hoje = datetime.now(timezone.utc).date()
    ontem = hoje - timedelta(days=1)

    jogos = []
    for dia in (ontem, hoje):
        url = f"https://v3.football.api-sports.io/fixtures?date={dia}&status=FT"
        try:
            r = requests.get(url, headers=headers, timeout=15)
            r.raise_for_status()
            jogos.extend(r.json().get("response", []))
        except Exception as e:
            print(f"Erro ao buscar jogos do dia {dia}: {e}")

    # Filtra só as ligas configuradas
    return [j for j in jogos if j["league"]["id"] in LIGAS]


def checar_zero_a_zero():
    notificados = carregar_notificados()
    jogos = buscar_jogos_finalizados()
    novos = 0

    for jogo in jogos:
        match_id = jogo["fixture"]["id"]
        if match_id in notificados:
            continue

        placar = jogo.get("goals", {})
        gols_casa = placar.get("home")
        gols_fora = placar.get("away")

        if gols_casa == 0 and gols_fora == 0:
            casa = jogo["teams"]["home"]["name"]
            fora = jogo["teams"]["away"]["name"]
            competicao = jogo["league"]["name"]
            mensagem = f"⚽ Terminou 0 x 0!\n{casa} x {fora}\nCompetição: {competicao}"
            enviar_telegram(mensagem)
            novos += 1

        notificados.add(match_id)

    salvar_notificados(notificados)

    if novos:
        print(f"{novos} jogo(s) 0x0 notificado(s).")
    else:
        print("Nenhum novo jogo 0x0 nesta verificação.")


if __name__ == "__main__":
    enviar_telegram("🤖 Bot de alerta 0x0 iniciado! Acompanhando: " + ", ".join(str(l) for l in LIGAS))
    while True:
        if em_horario_de_pausa():
            print("Horário de pausa (00h-07h) — nenhuma verificação será feita agora.")
        else:
            checar_zero_a_zero()
        time.sleep(INTERVALO_SEGUNDOS)
