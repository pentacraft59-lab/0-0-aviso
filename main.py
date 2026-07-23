import requests
import time
import os
import json
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

# ===================== CONFIGURAÇÕES EDITÁVEIS =====================
# A lista de ligas agora vem da variável de ambiente LIGAS, no Railway.
# Formato: números separados por vírgula, sem espaços. Exemplo:
#   71,39,2,140,135,61,78
# Consulte os IDs disponíveis rodando o listar_ligas.py ou em
# https://dashboard.api-football.com/soccer/ids/leagues
#
# Se a variável não existir (ex: rodando localmente sem configurá-la), usa
# esta lista padrão como fallback.
LIGAS_PADRAO = "71,39,2,140,135,61,78"
LIGAS = [int(x.strip()) for x in os.environ.get("LIGAS", LIGAS_PADRAO).split(",") if x.strip()]

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
ARQUIVO_PROXIMOS_JOGOS = "proximos_jogos.json"
ARQUIVO_ULTIMA_LISTA = "ultima_lista_enviada.json"


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


def buscar_proximo_jogo(liga_id):
    """Busca o próximo jogo da mesma competição que ainda NÃO começou (status 'Not Started')."""
    headers = {"x-apisports-key": obter_chave_api()}
    # Pede 5 jogos futuros como margem de segurança e filtra pelo primeiro que
    # realmente ainda não começou, em vez de confiar cegamente no primeiro da lista.
    url = f"https://v3.football.api-sports.io/fixtures?league={liga_id}&next=5"
    try:
        r = requests.get(url, headers=headers, timeout=15)
        r.raise_for_status()
        resultado = r.json().get("response", [])
    except Exception as e:
        print(f"Erro ao buscar próximo jogo da liga {liga_id}: {e}")
        return None

    agora_utc = datetime.now(timezone.utc)

    for jogo in resultado:
        status = jogo["fixture"]["status"]["short"]
        data_jogo = datetime.fromisoformat(jogo["fixture"]["date"].replace("Z", "+00:00"))

        # Só aceita jogos com status "Not Started" e horário ainda no futuro.
        # Isso evita pegar um jogo que já está em andamento (ao vivo) ou já
        # finalizado, caso a API devolva algo fora de ordem.
        if status == "NS" and data_jogo > agora_utc:
            return jogo

    return None


def formatar_proximo_jogo(proximo_jogo):
    """Monta o texto do próximo jogo, já convertendo o horário para o fuso local."""
    if not proximo_jogo:
        return ""

    casa = proximo_jogo["teams"]["home"]["name"]
    fora = proximo_jogo["teams"]["away"]["name"]

    data_utc = datetime.fromisoformat(proximo_jogo["fixture"]["date"].replace("Z", "+00:00"))
    data_local = data_utc.astimezone(FUSO_HORARIO)
    data_formatada = data_local.strftime("%d/%m às %Hh%M")

    return f"\n\nPróximo jogo da competição:\n{casa} x {fora} — {data_formatada}"


def carregar_proximos_jogos():
    try:
        with open(ARQUIVO_PROXIMOS_JOGOS, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def salvar_proximos_jogos(dados):
    with open(ARQUIVO_PROXIMOS_JOGOS, "w") as f:
        json.dump(dados, f)


def registrar_proximo_jogo_no_historico(proximo_jogo):
    """Salva o próximo jogo (identificado após um 0x0) no histórico, por data/horário/liga."""
    if not proximo_jogo:
        return

    dados = carregar_proximos_jogos()
    fixture_id = str(proximo_jogo["fixture"]["id"])

    data_utc = datetime.fromisoformat(proximo_jogo["fixture"]["date"].replace("Z", "+00:00"))
    data_local = data_utc.astimezone(FUSO_HORARIO)

    dados[fixture_id] = {
        "data": data_local.strftime("%Y-%m-%d"),
        "hora": data_local.strftime("%H:%M"),
        "liga": proximo_jogo["league"]["name"],
        "casa": proximo_jogo["teams"]["home"]["name"],
        "fora": proximo_jogo["teams"]["away"]["name"],
    }
    salvar_proximos_jogos(dados)


def gerar_lista_do_dia():
    """Monta o texto da lista de jogos salvos no histórico que acontecem hoje."""
    dados = carregar_proximos_jogos()
    hoje_str = datetime.now(FUSO_HORARIO).strftime("%Y-%m-%d")

    jogos_hoje = [j for j in dados.values() if j["data"] == hoje_str]
    jogos_hoje.sort(key=lambda j: j["hora"])

    if not jogos_hoje:
        return "📋 Lista de jogos de hoje: nenhum jogo salvo no histórico até o momento."

    linhas = [f"{j['hora']} — {j['casa']} x {j['fora']} ({j['liga']})" for j in jogos_hoje]
    return "📋 Jogos de hoje (histórico de próximos jogos):\n" + "\n".join(linhas)


def carregar_ultima_data_lista():
    try:
        with open(ARQUIVO_ULTIMA_LISTA, "r") as f:
            return json.load(f).get("data")
    except FileNotFoundError:
        return None


def salvar_ultima_data_lista(data_str):
    with open(ARQUIVO_ULTIMA_LISTA, "w") as f:
        json.dump({"data": data_str}, f)


def limpar_jogos_passados():
    """Remove do histórico jogos cuja data já passou, mantendo o arquivo enxuto."""
    dados = carregar_proximos_jogos()
    hoje_str = datetime.now(FUSO_HORARIO).strftime("%Y-%m-%d")

    dados_atualizados = {
        fixture_id: jogo for fixture_id, jogo in dados.items() if jogo["data"] >= hoje_str
    }

    if len(dados_atualizados) != len(dados):
        salvar_proximos_jogos(dados_atualizados)


def enviar_lista_diaria_se_necessario():
    """Às 7h, envia (uma única vez por dia) a lista de jogos salvos no histórico para hoje."""
    agora = datetime.now(FUSO_HORARIO)
    if agora.hour != 7:
        return

    hoje_str = agora.strftime("%Y-%m-%d")
    if carregar_ultima_data_lista() == hoje_str:
        return

    enviar_telegram(gerar_lista_do_dia())
    salvar_ultima_data_lista(hoje_str)
    limpar_jogos_passados()


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
            liga_id = jogo["league"]["id"]

            proximo_jogo = buscar_proximo_jogo(liga_id)
            texto_proximo = formatar_proximo_jogo(proximo_jogo)
            registrar_proximo_jogo_no_historico(proximo_jogo)

            mensagem = (
                f"⚽ Terminou 0 x 0!\n{casa} x {fora}\nCompetição: {competicao}"
                f"{texto_proximo}\n\nhttps://bolsadeaposta.bet.br/b/exchange"
            )
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
            enviar_lista_diaria_se_necessario()
            checar_zero_a_zero()
        time.sleep(INTERVALO_SEGUNDOS)
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
ARQUIVO_PROXIMOS_JOGOS = "proximos_jogos.json"
ARQUIVO_ULTIMA_LISTA = "ultima_lista_enviada.json"


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


def buscar_proximo_jogo(liga_id):
    """Busca o próximo jogo da mesma competição que ainda NÃO começou (status 'Not Started')."""
    headers = {"x-apisports-key": obter_chave_api()}
    # Pede 5 jogos futuros como margem de segurança e filtra pelo primeiro que
    # realmente ainda não começou, em vez de confiar cegamente no primeiro da lista.
    url = f"https://v3.football.api-sports.io/fixtures?league={liga_id}&next=5"
    try:
        r = requests.get(url, headers=headers, timeout=15)
        r.raise_for_status()
        resultado = r.json().get("response", [])
    except Exception as e:
        print(f"Erro ao buscar próximo jogo da liga {liga_id}: {e}")
        return None

    agora_utc = datetime.now(timezone.utc)

    for jogo in resultado:
        status = jogo["fixture"]["status"]["short"]
        data_jogo = datetime.fromisoformat(jogo["fixture"]["date"].replace("Z", "+00:00"))

        # Só aceita jogos com status "Not Started" e horário ainda no futuro.
        # Isso evita pegar um jogo que já está em andamento (ao vivo) ou já
        # finalizado, caso a API devolva algo fora de ordem.
        if status == "NS" and data_jogo > agora_utc:
            return jogo

    return None


def formatar_proximo_jogo(proximo_jogo):
    """Monta o texto do próximo jogo, já convertendo o horário para o fuso local."""
    if not proximo_jogo:
        return ""

    casa = proximo_jogo["teams"]["home"]["name"]
    fora = proximo_jogo["teams"]["away"]["name"]

    data_utc = datetime.fromisoformat(proximo_jogo["fixture"]["date"].replace("Z", "+00:00"))
    data_local = data_utc.astimezone(FUSO_HORARIO)
    data_formatada = data_local.strftime("%d/%m às %Hh%M")

    return f"\n\nPróximo jogo da competição:\n{casa} x {fora} — {data_formatada}"


def carregar_proximos_jogos():
    try:
        with open(ARQUIVO_PROXIMOS_JOGOS, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def salvar_proximos_jogos(dados):
    with open(ARQUIVO_PROXIMOS_JOGOS, "w") as f:
        json.dump(dados, f)


def registrar_proximo_jogo_no_historico(proximo_jogo):
    """Salva o próximo jogo (identificado após um 0x0) no histórico, por data/horário/liga."""
    if not proximo_jogo:
        return

    dados = carregar_proximos_jogos()
    fixture_id = str(proximo_jogo["fixture"]["id"])

    data_utc = datetime.fromisoformat(proximo_jogo["fixture"]["date"].replace("Z", "+00:00"))
    data_local = data_utc.astimezone(FUSO_HORARIO)

    dados[fixture_id] = {
        "data": data_local.strftime("%Y-%m-%d"),
        "hora": data_local.strftime("%H:%M"),
        "liga": proximo_jogo["league"]["name"],
        "casa": proximo_jogo["teams"]["home"]["name"],
        "fora": proximo_jogo["teams"]["away"]["name"],
    }
    salvar_proximos_jogos(dados)


def gerar_lista_do_dia():
    """Monta o texto da lista de jogos salvos no histórico que acontecem hoje."""
    dados = carregar_proximos_jogos()
    hoje_str = datetime.now(FUSO_HORARIO).strftime("%Y-%m-%d")

    jogos_hoje = [j for j in dados.values() if j["data"] == hoje_str]
    jogos_hoje.sort(key=lambda j: j["hora"])

    if not jogos_hoje:
        return "📋 Lista de jogos de hoje: nenhum jogo salvo no histórico até o momento."

    linhas = [f"{j['hora']} — {j['casa']} x {j['fora']} ({j['liga']})" for j in jogos_hoje]
    return "📋 Jogos de hoje (histórico de próximos jogos):\n" + "\n".join(linhas)


def carregar_ultima_data_lista():
    try:
        with open(ARQUIVO_ULTIMA_LISTA, "r") as f:
            return json.load(f).get("data")
    except FileNotFoundError:
        return None


def salvar_ultima_data_lista(data_str):
    with open(ARQUIVO_ULTIMA_LISTA, "w") as f:
        json.dump({"data": data_str}, f)


def limpar_jogos_passados():
    """Remove do histórico jogos cuja data já passou, mantendo o arquivo enxuto."""
    dados = carregar_proximos_jogos()
    hoje_str = datetime.now(FUSO_HORARIO).strftime("%Y-%m-%d")

    dados_atualizados = {
        fixture_id: jogo for fixture_id, jogo in dados.items() if jogo["data"] >= hoje_str
    }

    if len(dados_atualizados) != len(dados):
        salvar_proximos_jogos(dados_atualizados)


def enviar_lista_diaria_se_necessario():
    """Às 7h, envia (uma única vez por dia) a lista de jogos salvos no histórico para hoje."""
    agora = datetime.now(FUSO_HORARIO)
    if agora.hour != 7:
        return

    hoje_str = agora.strftime("%Y-%m-%d")
    if carregar_ultima_data_lista() == hoje_str:
        return

    enviar_telegram(gerar_lista_do_dia())
    salvar_ultima_data_lista(hoje_str)
    limpar_jogos_passados()


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
            liga_id = jogo["league"]["id"]

            proximo_jogo = buscar_proximo_jogo(liga_id)
            texto_proximo = formatar_proximo_jogo(proximo_jogo)
            registrar_proximo_jogo_no_historico(proximo_jogo)

            mensagem = (
                f"⚽ Terminou 0 x 0!\n{casa} x {fora}\nCompetição: {competicao}"
                f"{texto_proximo}\n\nhttps://bolsadeaposta.bet.br/b/exchange"
            )
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
            enviar_lista_diaria_se_necessario()
            checar_zero_a_zero()
        time.sleep(INTERVALO_SEGUNDOS)
