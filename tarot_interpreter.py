import aiohttp
import uuid
import logging
import ssl
import json
from pathlib import Path
from config import Config
from typing import Optional, Dict, Any


logger = logging.getLogger(__name__)

class TarotInterpreter:
    _card_meanings: Dict[str, Any] = {}
    
    @classmethod
    async def load_meanings(cls):
        """Загрузка значений карт"""
        try:
            # Пробуем несколько возможных путей
            paths_to_try = [
                Config.MEANINGS_PATH,
                Path("data/card_meanings.json"),
                Path("../data/card_meanings.json")
            ]
            
            for path in paths_to_try:
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        cls._card_meanings = json.load(f)
                    logger.info(f"Card meanings loaded from {path}")
                    return
                except FileNotFoundError:
                    continue
            
            raise FileNotFoundError("Could not find card meanings file")
            
        except Exception as e:
            logger.error(f"Error loading card meanings: {e}")
            cls._card_meanings = {} 


    @staticmethod
    async def get_access_token() -> Optional[str]:
        """Получение токена доступа для GigaChat API"""
        url = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
        
        headers = {
            'Content-Type': 'application/x-www-form-urlencoded',
            'Accept': 'application/json',
            'RqUID': str(uuid.uuid4()),
            'Authorization': f'Basic {Config.GIGACHAT_AUTH_KEY}'
        }
        
        data = {
            'scope': Config.GIGACHAT_SCOPE
        }
        
        try:
            ssl_context = ssl.create_default_context(cafile=str(Config.SSL_CERT_PATH))
            
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url,
                    headers=headers,
                    data=data,
                    ssl=ssl_context,
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as response:
                    if response.status != 200:
                        logger.error(f"GigaChat auth failed: {response.status}")
                        return None
                    
                    json_response = await response.json()
                    return json_response.get("access_token")
        except Exception as e:
            logger.error(f"GigaChat auth error: {str(e)}")
            return None

    @staticmethod
    async def generate_interpretation(question: str, situation: str, cards: list) -> str:
        """Генерация интерпретации расклада"""
        token = await TarotInterpreter.get_access_token()
        if not token:
            return "Не удалось получить токен для доступа к GigaChat."

        url = "https://gigachat.devices.sberbank.ru/api/v1/chat/completions"
        headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'Authorization': f'Bearer {token}'
        }

        prompt = f"""Ты — опытный таролог (Таро Уэйта), отвечающий кратко, структурированно и по делу, без мистики и эзотерики. 
Вопрос пользователя: "{question}".
Ситуация: "{situation}".
Выпали карты: {", ".join(cards)}.

Оформи ответ строго по шаблону:

1. ✨Название карты✨:
⭐️ Кратко — 1 главная идея карты.
⭐️ Кратко — 1 нюанс по значению.
⭐️ Кратко — 1 ассоциация или совет.

(Продублируй этот блок для каждой карты!)

✨Разбор ситуации:✨
⭐️ 2–3 предложения по сути, что происходит с учётом вопроса, ситуации и выпавших карт (логично связать значения между собой). Без воды.

✨Совет:✨
⭐️ 2–3 предложения с конкретными действиями или мыслями для пользователя. Без эзотерики, по существу.

Общие правила:
— Сохраняй структуру и оформление, как в примере.
— Не делай ответ слишком длинным или коротким — 8–12 предложений, 120–180 слов.
— Пиши дружелюбно, но уверенно, по делу, без мистических или эзотерических штампов.
— Всегда используй эмодзи и разделители, как в примере.
"""

        payload = {
            "model": "GigaChat",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.7,
            "max_tokens": 1024
        }

        try:
            ssl_context = ssl.create_default_context(cafile=str(Config.SSL_CERT_PATH))
            
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url, 
                    headers=headers, 
                    json=payload, 
                    ssl=ssl_context,
                    timeout=aiohttp.ClientTimeout(total=30)
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        return data.get('choices', [{}])[0].get('message', {}).get('content', '')
                    logger.error(f"GigaChat API error: {await response.text()}")
                    return "Ошибка при генерации интерпретации"
        except asyncio.TimeoutError:
            logger.error("Timeout generating interpretation")
            return "Время генерации истекло, попробуйте позже"
        except Exception as e:
            logger.error(f"Request error: {str(e)}")
            return "Ошибка подключения к серверу"

    @classmethod
    async def get_card_meaning(cls, card_name: str, is_reversed: bool = False) -> str:
        """Получение значения карты с учетом положения"""
        if not cls._card_meanings:
            await cls.load_meanings()
        
        card_data = cls._card_meanings.get(card_name)
        if not card_data:
            return f"🔮 Карта '{card_name}' не найдена в базе данных."
        
        category = card_data.get("category", "Неизвестная категория")
        meaning = card_data.get("meaning", "Нет данных")
        upright = card_data.get("upright", "Нет данных")
        reversed_text = card_data.get("reversed", "Нет данных")
        
        return (
            f"📖 *{card_name}* ({category}) {'(Перевернутая)' if is_reversed else ''}\n\n"
            f"🔮 *Основное значение:*\n{meaning}\n\n"
            f"⭐ *Прямое положение:*\n{upright}\n\n"
            f"🌀 *Перевернутое положение:*\n{reversed_text}"
        )
    
    @classmethod
    async def search_cards(cls, query: str) -> list:
        """Поиск карт по названию"""
        if not cls._card_meanings:
            await cls.load_meanings()
        
        results = []
        query_lower = query.lower()
        
        for card_name, card_data in cls._card_meanings.items():
            if query_lower in card_name.lower():
                results.append((card_name, card_data.get("category", "Неизвестно")))
        
        return results