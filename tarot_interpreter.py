import requests
import uuid
import json

# Данные для авторизации
AUTHORIZATION_KEY = "ZWEwMmMyZDctMThiNC00MWFlLTkxY2YtZmQ4M2EzMjdlZjY1OjIxMDgxYzA0LTM0MWItNDcwZC1iOGRmLTE2ZGE4Zjk1MzkwMw=="
SCOPE = "GIGACHAT_API_PERS"

def get_access_token():
    """
    Получает токен доступа для GigaChat API с использованием собственного сертификата.
    """
    url = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
    
    # Генерация уникального идентификатора для запроса
    rq_uid = str(uuid.uuid4())

    # Параметры запроса
    payload = 'scope=' + SCOPE  # ело запроса как строка

    # Заголовки запроса
    headers = {
        'Content-Type': 'application/x-www-form-urlencoded',
        'Accept': 'application/json',
        'RqUID': rq_uid,  
        'Authorization': f'Basic {AUTHORIZATION_KEY}'  
    }

    # Путь к сертификату для проверки SSL
    verify_path = r'C:\Users\DICK\Desktop\TarotBot\russian_trusted_root_ca.cer'

    try:
        # Отправка POST запроса для получения токена
        response = requests.post(url, headers=headers, data=payload, verify=verify_path)

        # Печатаем статус код и текст ответа для отладки
        print(f"Response Status Code: {response.status_code}")
        print(f"Response Text: {response.text}")

        # Проверка на успешный ответ
        response.raise_for_status()

        # Извлекаем токен из ответа
        response_json = response.json()
        return response_json.get("access_token")
    
    except requests.exceptions.SSLError as e:
        print("Ошибка SSL-сертификата. Проверьте соединение или сертификат.")
        return None
    except requests.exceptions.RequestException as e:
        print(f"Ошибка при получении токена: {e}")
        return None



def generate_tarot_interpretation(question, situation, selected_cards):
    """
    Генерирует интерпретацию расклада на основе вопроса, предыстории и выбранных карт, используя GigaChat API.
    """
    # Получаем актуальный токен доступа
    token = get_access_token()

    if not token:
        return "Не удалось получить токен для доступа к GigaChat."
    
    prompt = f"""Вы являетесь опытным тарологом (Таро Уэйта). Вопрошающий задал следующий вопрос: "{question}". 
    Предыстория ситуации: "{situation}". 
    Вопрощающий вытянул следующие карты: {", ".join(selected_cards)}.  
    Отправь краткий ответ именно с таким оформлением как в примере, но текст измени под карты и ситуацию вопрошающего("{question}", "{situation}", {", ".join(selected_cards)}). Пример:

1. ✨Жрица✨:
⭐️ Символизирует интуицию, внутренний мир и эмоции.
⭐️ Может указывать на скрытые чувства или тайны.
⭐️ Часто ассоциируется с женской энергией и интуицией.

2. ✨Дурак✨:
⭐️ Символизирует начало нового пути, беззаботность и открытость.
⭐️ Может указывать на непредвзятость и готовность к новым приключениям.
⭐️ Часто ассоциируется с неопытностью и спонтанностью.

✨Разбор ситуации:✨

⭐️Жрица может указывать на скрытые чувства Данила к вопрошающему, которые он не осознает или не выражает, что может быть связано с его интуицией и внутренними переживаниями, а Дурак может говорить о том, что он находится на пороге новых отношений или чувств, и его отношение к пользователю может быть связано с этим новым началом.

✨Совет для вопрошающего:✨

⭐️Не спешите с выводами⭐️, так как чувства могут быть скрытыми, и важно дать Данилу время и пространство для осознания своих эмоций, а также развивайте свою интуицию, чтобы понять, что он чувствует, и не бойтесь задавать ему вопросы напрямую."""

    url = "https://gigachat.devices.sberbank.ru/api/v1/chat/completions"
    
    headers = {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'Authorization': f'Bearer {token}'
    }
    
    payload = {
        "model": "GigaChat",
        "messages": [
            {"role": "user", "content": prompt}
        ],
        "stream": False,
        "repetition_penalty": 1
    }

    try:
        response = requests.post(url, headers=headers, json=payload, verify='russian_trusted_root_ca.cer')
        
        if response.status_code == 200:
            data = response.json()
            interpretation = data.get('choices', [{}])[0].get('message', {}).get('content', '').strip()
            return interpretation
        else:
            print(f"Ошибка при запросе к GigaChat: {response.text}")
            return "Произошла ошибка при генерации интерпретации. Попробуйте снова."
    except requests.exceptions.RequestException as e:
        print(f"Ошибка запроса: {e}")
        return "Произошла ошибка при подключении к серверу."
