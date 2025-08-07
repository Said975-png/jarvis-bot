import requests
import time
import base64
from io import BytesIO
from PIL import Image
import os
import json
import re

# Конфигурация (используйте переменные окружения для безопасности!)
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "7634467920:AAHb4X0QUig0cfTV7bFbGyoOo235qaDrYaw")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "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")
STABILITY_API_KEY = os.getenv("STABILITY_API_KEY", "sk-hkDS8qnAnoRUN7ijUfZMonjJ1Y5ATTvLuBdwZ7LONj1cEJMJ")

# Настройки моделей
TEXT_MODEL = "openai/gpt-3.5-turbo"
VISION_MODEL = "anthropic/claude-3-haiku"
IMAGE_MODEL = "stability-ai/stable-diffusion-xl"
MAX_TOKENS = 1000
IMAGE_QUALITY = "low"

# URL API
TELEGRAM_API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"
OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"
STABILITY_API_URL = "https://api.stability.ai/v1/generation/stable-diffusion-xl-1024-v1-0/text-to-image"

# Хранилище данных
conversations = {}
image_prompts_cache = {}

# Улучшенные промпты для генерации изображений
STYLE_PROMPTS = {
    "default": "highly detailed, digital painting, concept art, sharp focus, studio lighting, ultra HD, 8K resolution",
    "realistic": "photorealistic, ultra detailed, 8K, professional photography, realistic lighting",
    "anime": "anime style, vibrant colors, detailed, studio ghibli style, anime artwork",
    "fantasy": "fantasy art, detailed, magical, dungeons and dragons style, intricate details",
    "cyberpunk": "cyberpunk style, neon lights, futuristic, blade runner style, rainy night",
    "watercolor": "watercolor painting, artistic, beautiful brush strokes, traditional art",
    "pixel": "pixel art, 8-bit style, retro gaming, low resolution, nostalgic"
}

NEGATIVE_PROMPT = (
    "blurry, low quality, low resolution, cropped, watermark, text, signature, "
    "deformed, bad anatomy, disfigured, poorly drawn face, mutation, extra limb, "
    "ugly, poorly drawn hands, missing limb, floating limbs, disconnected limbs, "
    "out of focus, long neck, long body, distorted, bad art, artifacts"
)

def compress_image(image_data, max_size=1024):
    """Сжимаем изображение до приемлемого размера"""
    try:
        img = Image.open(BytesIO(image_data))
        if max(img.size) > max_size:
            img.thumbnail((max_size, max_size))
        buffer = BytesIO()
        img.save(buffer, format="JPEG", quality=85)
        return buffer.getvalue()
    except Exception as e:
        print(f"Ошибка сжатия изображения: {e}")
        return image_data

def telegram_request(method, data=None, retry=3):
    """Улучшенный запрос к Telegram API"""
    for attempt in range(retry):
        try:
            response = requests.post(
                f"{TELEGRAM_API_URL}/{method}",
                json=data,
                headers={'Content-Type': 'application/json'},
                timeout=30
            )
            
            if response.status_code == 200:
                return response.json()
            else:
                print(f"HTTP Error {response.status_code}: {response.text}")
                
        except requests.exceptions.Timeout:
            print(f"Попытка {attempt + 1}: Таймаут запроса")
            if attempt == retry - 1:
                return None
            time.sleep(2)
            
        except requests.exceptions.RequestException as e:
            print(f"Попытка {attempt + 1} не удалась: {str(e)}")
            if attempt == retry - 1:
                return None
            time.sleep(2)
            
    return None

def send_message(chat_id, text):
    """Функция отправки сообщений"""
    try:
        data = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True
        }
        return telegram_request("sendMessage", data)
    except Exception as e:
        print(f"Ошибка отправки сообщения: {e}")
        return None

def send_photo(chat_id, image_bytes, caption=""):
    """Функция отправки фото"""
    url = f"{TELEGRAM_API_URL}/sendPhoto"
    
    try:
        files = {'photo': ('image.jpg', image_bytes, 'image/jpeg')}
        data = {'chat_id': chat_id}
        
        if caption:
            data['caption'] = caption[:1024]
            data['parse_mode'] = 'Markdown'
            
        response = requests.post(
            url,
            files=files,
            data=data,
            timeout=30
        )
        return response.json()
    except Exception as e:
        print(f"Ошибка отправки фото: {e}")
        return None

def detect_style(prompt):
    """Определяем стиль изображения по ключевым словам"""
    prompt_lower = prompt.lower()
    style_mapping = {
        'реалистичн': 'realistic',
        'аниме': 'anime',
        'фэнтези': 'fantasy',
        'киберпанк': 'cyberpunk',
        'акварель': 'watercolor',
        'пиксельн': 'pixel',
        'pixel': 'pixel',
        'anime': 'anime',
        'realistic': 'realistic',
        'fantasy': 'fantasy',
        'cyberpunk': 'cyberpunk'
    }
    
    for keyword, style in style_mapping.items():
        if keyword in prompt_lower:
            return style
    return "default"

def enhance_prompt(prompt):
    """Улучшаем промпт для генерации изображений"""
    # Определяем стиль
    style = detect_style(prompt)
    
    # Очищаем промпт от команд стиля
    clean_prompt = re.sub(
        r'\b(реалистичн|аниме|фэнтези|киберпанк|акварель|пиксельн|realistic|anime|fantasy|cyberpunk|pixel)\w*',
        '', 
        prompt, 
        flags=re.IGNORECASE
    ).strip()
    
    # Собираем финальный промпт
    enhanced = f"{clean_prompt}, {STYLE_PROMPTS[style]}"
    
    # Удаляем дубликаты и лишние запятые
    words = [word.strip() for word in enhanced.split(',') if word.strip()]
    unique_words = []
    seen = set()
    
    for word in words:
        if word not in seen:
            seen.add(word)
            unique_words.append(word)
    
    return ', '.join(unique_words)

def generate_image(prompt):
    """Генерация изображения по текстовому описанию"""
    headers = {
        "Authorization": f"Bearer {STABILITY_API_KEY}",
        "Content-Type": "application/json",
        "Accept": "image/png"
    }
    
    enhanced_prompt = enhance_prompt(prompt)
    print(f"Enhanced prompt: {enhanced_prompt}")  # Логируем для отладки
    
    payload = {
        "text_prompts": [
            {
                "text": enhanced_prompt,
                "weight": 1.0
            },
            {
                "text": NEGATIVE_PROMPT,
                "weight": -1.0
            }
        ],
        "cfg_scale": 7,
        "height": 1024,
        "width": 1024,
        "samples": 1,
        "steps": 50,
        "style_preset": "enhance",  # Используем preset для лучшего качества
        "sampler": "K_DPMPP_2M",
        "clip_guidance_preset": "FAST_BLUE",
        "seed": int(time.time() % 1000000)  # Добавляем seed для воспроизводимости
    }
    
    try:
        response = requests.post(
            STABILITY_API_URL,
            headers=headers,
            json=payload,
            timeout=120  # Увеличиваем таймаут для сложных запросов
        )
        
        if response.status_code == 200:
            return response.content
        else:
            print(f"Ошибка генерации изображения: {response.status_code} - {response.text}")
            return None
    except Exception as e:
        print(f"Ошибка запроса: {e}")
        return None

def get_file_url(file_id):
    """Получаем URL файла"""
    response = telegram_request("getFile", {"file_id": file_id})
    if response and response.get("ok"):
        return f"https://api.telegram.org/file/bot{BOT_TOKEN}/{response['result']['file_path']}"
    return None

def download_and_prepare_image(file_url):
    """Загрузка и подготовка изображения"""
    try:
        response = requests.get(file_url, timeout=30)
        if response.status_code == 200:
            compressed_image = compress_image(response.content)
            return base64.b64encode(compressed_image).decode('utf-8')
    except Exception as e:
        print(f"Ошибка загрузки изображения: {e}")
    return None

def analyze_image_with_vision(base64_image, prompt):
    """Анализ изображения через API"""
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "HTTP-Referer": "https://your-domain.com",
        "X-Title": "AI Bot",
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": VISION_MODEL,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{base64_image}",
                            "detail": IMAGE_QUALITY
                        }
                    }
                ]
            }
        ],
        "max_tokens": MAX_TOKENS
    }
    
    try:
        response = requests.post(
            OPENROUTER_API_URL,
            headers=headers,
            json=payload,
            timeout=40
        )
        
        if response.status_code == 200:
            return response.json()["choices"][0]["message"]["content"]
        else:
            print(f"Ошибка API: {response.status_code} - {response.text}")
            return None
    except Exception as e:
        print(f"Ошибка запроса: {e}")
        return None

def process_image_message(file_id, chat_id, caption=None):
    """Обработка изображений"""
    file_url = get_file_url(file_id)
    if not file_url:
        return "Не удалось получить изображение"
    
    base64_image = download_and_prepare_image(file_url)
    if not base64_image:
        return "Ошибка обработки изображения"
    
    prompt = caption or "Опиши что изображено на фото"
    analysis = analyze_image_with_vision(base64_image, prompt)
    
    return analysis or "Не удалось проанализировать изображение"

def generate_text_response(text, chat_id):
    """Генерация текстового ответа"""
    if chat_id not in conversations:
        conversations[chat_id] = [
            {
                "role": "system", 
                "content": "Ты полезный AI ассистент. Отвечай информативно и по делу."
            }
        ]
    
    conversations[chat_id].append({"role": "user", "content": text})
    
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "HTTP-Referer": "https://your-domain.com",
        "X-Title": "AI Bot",
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": TEXT_MODEL,
        "messages": conversations[chat_id],
        "max_tokens": MAX_TOKENS,
        "temperature": 0.7
    }
    
    try:
        response = requests.post(
            OPENROUTER_API_URL,
            headers=headers,
            json=payload,
            timeout=40
        )
        
        if response.status_code == 200:
            reply = response.json()["choices"][0]["message"]["content"]
            conversations[chat_id].append({"role": "assistant", "content": reply})
            
            if len(conversations[chat_id]) > 6:
                conversations[chat_id] = conversations[chat_id][-6:]
            
            return reply
        else:
            print(f"Ошибка API: {response.status_code} - {response.text}")
            return "Произошла ошибка при обработке запроса"
    except Exception as e:
        print(f"Ошибка соединения: {e}")
        return "Сервис временно недоступен"

def handle_message(message):
    """Обработка входящих сообщений"""
    chat_id = message["chat"]["id"]
    
    try:
        if "photo" in message:
            photo = message["photo"][-1]
            response = process_image_message(photo["file_id"], chat_id, message.get("caption"))
            send_message(chat_id, response)
            
        elif "text" in message:
            text = message["text"].strip()
            
            # Обработка команд генерации изображений
            if text.lower().startswith(("нарисуй", "сгенерируй", "создай", "draw", "generate")) or \
               any(word in text.lower() for word in ["арт", "рисунок", "изображение", "art", "image"]):
                
                # Извлекаем промпт из сообщения
                prompt = re.sub(
                    r'^(нарисуй|сгенерируй|создай|draw|generate|арт|рисунок|изображение|art|image)[\s:;-]*', 
                    '', 
                    text, 
                    flags=re.IGNORECASE
                ).strip()
                
                if not prompt:
                    send_message(chat_id, "🎨 Пожалуйста, укажите что нарисовать. Например: \"Нарисуй космического кота\"")
                    return
                
                # Сохраняем оригинальный промпт для подписи
                image_prompts_cache[chat_id] = prompt
                
                send_message(chat_id, "🎨 Создаю изображение... Это может занять до 1 минуты...")
                
                image_data = generate_image(prompt)
                
                if image_data:
                    caption = f"🖼️ {image_prompts_cache.get(chat_id, 'Ваше изображение готово')}"
                    send_photo(chat_id, image_data, caption)
                else:
                    send_message(chat_id, "❌ Не удалось сгенерировать изображение. Попробуйте изменить описание.")
            else:
                response = generate_text_response(text, chat_id)
                send_message(chat_id, response)
                
    except Exception as e:
        print(f"Ошибка обработки сообщения: {e}")
        send_message(chat_id, "⚠️ Произошла ошибка при обработке запроса")

def main():
    print("🤖 Бот запущен и готов к работе...")
    last_update_id = 0
    
    # Проверка соединения
    try:
        me = telegram_request("getMe")
        if not me or not me.get("ok"):
            print("❌ Ошибка подключения к Telegram API. Проверьте токен бота.")
            return
        
        print(f"✅ Бот @{me['result']['username']} успешно подключен!")
        
        while True:
            try:
                updates = telegram_request("getUpdates", {
                    "offset": last_update_id + 1,
                    "timeout": 30,
                    "allowed_updates": ["message"]
                })
                
                if not updates or not updates.get("result"):
                    time.sleep(2)
                    continue
                    
                for update in updates["result"]:
                    last_update_id = update["update_id"]
                    handle_message(update["message"])
                    
            except Exception as e:
                print(f"⚠️ Ошибка в главном цикле: {e}")
                time.sleep(5)
                
    except KeyboardInterrupt:
        print("🚫 Бот остановлен пользователем")
    except Exception as e:
        print(f"🛑 Критическая ошибка: {e}")

if __name__ == "__main__":
    main()