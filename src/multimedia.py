import os
import re
import json
import uuid
import logging
import requests
import genanki
from src.config import settings

logger = logging.getLogger(__name__)

def clean_text_for_speech(text: str) -> str:
    """Strip HTML tags and markdown symbols so TTS reads smoothly in natural language."""
    if not text:
        return ""
    # Remove HTML tags
    clean = re.sub(r'<[^>]+>', ' ', text)
    # Remove Markdown formatting characters (*, #, _, `, ~, >, [, ], etc.)
    clean = re.sub(r'[*#_`~>\[\]\(\)]', ' ', clean)
    clean = re.sub(r'\s+', ' ', clean).strip()
    return clean

# ---------------------------------------------------------------------------
# OpenAI TTS API Integration (Voice Audio Generation & Realtime Streaming)
# ---------------------------------------------------------------------------
import hashlib
from pathlib import Path

_AUDIO_CACHE_DIR = Path(__file__).resolve().parent / "web" / "static" / "audio_cache"
_AUDIO_CACHE_DIR.mkdir(parents=True, exist_ok=True)

def stream_openai_audio(text: str, voice: str = "alloy"):
    """
    Yields audio MP3 byte chunks for streaming. Uses an MD5 disk cache for instant (<10ms) playback on repeated phrases.
    """
    clean_input = clean_text_for_speech(text)[:4000]
    if not clean_input:
        return

    # Check MD5 cache
    cache_key = hashlib.md5(f"{voice}:{clean_input}".encode("utf-8")).hexdigest()
    cache_path = _AUDIO_CACHE_DIR / f"{cache_key}.mp3"

    if cache_path.exists():
        logger.info(f"Serving TTS stream from audio cache: {cache_key}.mp3")
        try:
            with open(cache_path, "rb") as f:
                while chunk := f.read(1024):
                    yield chunk
            return
        except Exception as e:
            logger.warning(f"Failed to read cached audio file: {e}")

    api_key = settings.openai_api_key or os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        logger.warning("OpenAI API Key not found for streaming TTS.")
        return

    url = "https://api.openai.com/v1/audio/speech"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    data = {
        "model": "tts-1",
        "input": clean_input,
        "voice": voice,
        "response_format": "mp3"
    }

    try:
        response = requests.post(url, json=data, headers=headers, stream=True, timeout=20)
        if response.status_code == 200:
            bytes_acc = bytearray()
            for chunk in response.iter_content(chunk_size=1024):
                if chunk:
                    bytes_acc.extend(chunk)
                    yield chunk
            # Save to disk cache
            try:
                with open(cache_path, "wb") as f:
                    f.write(bytes_acc)
            except Exception as cache_err:
                logger.warning(f"Could not save TTS to cache: {cache_err}")
        else:
            logger.error(f"OpenAI TTS Stream Error [{response.status_code}]: {response.text}")
    except Exception as e:
        logger.error(f"Unexpected error in stream_openai_audio: {e}")


def generate_openai_audio(text: str, output_path: str, voice: str = "alloy") -> bool:
    """
    Generates text-to-speech using OpenAI Audio API (tts-1 model) and saves to output_path.
    Voices available: alloy (warm/natural), shimmer (expressive female), echo (smooth male), nova, onyx, fable.
    """
    api_key = settings.openai_api_key or os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        logger.warning("OpenAI API Key not found for TTS.")
        return False

    url = "https://api.openai.com/v1/audio/speech"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    clean_input = clean_text_for_speech(text)[:4000]

    data = {
        "model": "tts-1",
        "input": clean_input,
        "voice": voice
    }

    try:
        response = requests.post(url, json=data, headers=headers, timeout=20)
        if response.status_code == 200:
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            with open(output_path, "wb") as f:
                f.write(response.content)
            logger.info(f"OpenAI TTS audio generated successfully at {output_path}")
            return True
        else:
            logger.error(f"OpenAI TTS API Error [{response.status_code}]: {response.text}")
            return False
    except Exception as e:
        logger.error(f"Unexpected error calling OpenAI TTS API: {e}")
        return False


def generate_elevenlabs_audio(text: str, output_path: str, voice_id: str = "pNInz6obpgDQGcFmaJgB", voice_name: str = "alloy") -> bool:
    """
    Generates text-to-speech audio. Uses OpenAI TTS if OPENAI_API_KEY is available,
    falling back to ElevenLabs.
    """
    # Primary preference: OpenAI TTS
    if settings.openai_api_key or os.getenv("OPENAI_API_KEY"):
        return generate_openai_audio(text, output_path, voice=voice_name)

    # Fallback to ElevenLabs
    api_key = settings.elevenlabs_api_key
    if not api_key:
        logger.warning("Neither OpenAI nor ElevenLabs API Key found. Skipping audio generation.")
        return False
        
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
    
    headers = {
        "Accept": "audio/mpeg",
        "Content-Type": "application/json",
        "xi-api-key": api_key
    }
    
    data = {
        "text": text,
        "model_id": "eleven_multilingual_v2",
        "voice_settings": {
            "stability": 0.5,
            "similarity_boost": 0.5
        }
    }
    
    try:
        response = requests.post(url, json=data, headers=headers, timeout=15)
        if response.status_code == 200:
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            with open(output_path, "wb") as f:
                f.write(response.content)
            return True
        else:
            logger.error(f"ElevenLabs API Error [{response.status_code}]: {response.text}")
            return False
    except Exception as e:
        logger.error(f"Error calling ElevenLabs API: {e}")
        return False

# ---------------------------------------------------------------------------
# HeyGen API Integration (Visual Profile Avatar)
# ---------------------------------------------------------------------------
def generate_heygen_video(text: str) -> str | None:
    """
    Generates a talking avatar video using HeyGen API.
    Returns the video ID or URL if successful, None otherwise.
    """
    api_key = settings.heygen_api_key
    if not api_key:
        logger.warning("HeyGen API Key not found. Skipping video generation.")
        return None
        
    url = "https://api.heygen.com/v2/video/generate"
    headers = {
        "accept": "application/json",
        "content-type": "application/json",
        "x-api-key": api_key
    }
    
    # Placeholder standard avatar setup
    data = {
        "video_inputs": [
            {
                "character": {
                    "type": "avatar",
                    "avatar_id": "Anna_public_3_20240108", # Using a newer valid public avatar
                    "avatar_style": "normal"
                },
                "voice": {
                    "type": "text",
                    "input_text": text[:2000], # API text limit handling
                    "voice_id": "5fbecc8a2585441aab29ca46a5cd9356" # Lively Laura (Spanish Female)
                }
            }
        ]
    }
    
    try:
        response = requests.post(url, json=data, headers=headers, timeout=15)
        if response.status_code == 200:
            res_data = response.json()
            video_id = res_data.get("data", {}).get("video_id")
            return video_id
        elif response.status_code == 401:
            logger.error("HeyGen API Error [401 Unauthorized]: Invalid or expired API Key.")
            return None
        elif response.status_code == 402:
            logger.error("HeyGen API Error [402 Payment Required]: Insufficient credits on HeyGen account.")
            return None
        elif response.status_code == 429:
            logger.error("HeyGen API Error [429 Too Many Requests]: Rate limit exceeded.")
            return None
        else:
            logger.error(f"HeyGen API Error [{response.status_code}]: {response.text}")
            return None
    except requests.exceptions.RequestException as e:
        logger.error(f"Network error while calling HeyGen API: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error calling HeyGen API: {e}")
        return None

def check_heygen_video_status(video_id: str) -> dict | None:
    """
    Checks the status of a HeyGen video and returns the video URL if completed.
    Returns a dict with 'status' and 'video_url', or None on error.
    """
    api_key = settings.heygen_api_key
    if not api_key:
        return None
        
    url = f"https://api.heygen.com/v1/video_status.get?video_id={video_id}"
    headers = {
        "accept": "application/json",
        "x-api-key": api_key
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=15)
        if response.status_code == 200:
            res_data = response.json()
            data_block = res_data.get("data", {})
            status = data_block.get("status")
            video_url = data_block.get("video_url")
            return {"status": status, "video_url": video_url}
        else:
            logger.error(f"HeyGen status API Error [{response.status_code}]: {response.text}")
            return None
    except Exception as e:
        logger.error(f"Error checking HeyGen video status: {e}")
        return None

# ---------------------------------------------------------------------------
# GenAnki Integration (Kinesthetic Profile Flashcards)
# ---------------------------------------------------------------------------
def generate_anki_deck(html_content: str, deck_name: str, output_path: str) -> bool:
    """
    Parses HTML content for <details class="flashcard"> tags, 
    extracts Q&A, and generates a downloadable Anki .apkg deck.
    """
    # Regex to find flashcard structures: 
    # <details class="flashcard"><summary>QUESTION</summary><div class="flashcard-body">ANSWER</div></details>
    pattern = r'<details[^>]*class="flashcard"[^>]*>.*?<summary>(.*?)</summary>.*?<div[^>]*class="flashcard-body"[^>]*>(.*?)</div>.*?</details>'
    
    matches = re.findall(pattern, html_content, re.IGNORECASE | re.DOTALL)
    
    if not matches:
        logger.warning("No flashcards found in HTML to generate Anki deck.")
        return False
        
    # Create the model (card format)
    my_model = genanki.Model(
        1607392319,
        'Modelo Adaptativo Kinestésico',
        fields=[
            {'name': 'Pregunta'},
            {'name': 'Respuesta'},
        ],
        templates=[
            {
                'name': 'Tarjeta 1',
                'qfmt': '<div style="font-family: Arial; text-align: center; font-size: 20px;">{{Pregunta}}</div>',
                'afmt': '{{FrontSide}}<hr id="answer"><div style="font-family: Arial; text-align: left; font-size: 18px;">{{Respuesta}}</div>',
            },
        ])
        
    # Create the deck
    # Use a deterministic random ID based on deck_name to group them if re-generated
    deck_id = hash(deck_name) % (10**10) 
    my_deck = genanki.Deck(deck_id, deck_name)
    
    for question, answer in matches:
        # Clean up text
        q = question.strip()
        a = answer.strip()
        
        note = genanki.Note(
            model=my_model,
            fields=[q, a]
        )
        my_deck.add_note(note)
        
    try:
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        genanki.Package(my_deck).write_to_file(output_path)
        logger.info(f"Anki deck successfully saved to {output_path}")
        return True
    except Exception as e:
        logger.error(f"Failed to write Anki deck: {e}")
        return False
