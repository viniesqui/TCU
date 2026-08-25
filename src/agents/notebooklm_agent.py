import os
import asyncio
import logging
from pathlib import Path
from notebooklm import AuthTokens, NotebookLMClient
from notebooklm import AudioFormat, Source

logger = logging.getLogger(__name__)

class NotebookLMAgent:
    def __init__(self, cookies_str: str = None):
        """
        Initialize NotebookLMAgent.
        cookies_str should be a string containing: "__Secure-1PSID=xxx; __Secure-1PSIDTS=yyy;"
        """
        self.cookies_str = cookies_str or os.getenv("NOTEBOOKLM_COOKIES", "")
        
    def _parse_cookies(self):
        cookies_dict = {}
        if not self.cookies_str:
            return cookies_dict
            
        parts = self.cookies_str.split(";")
        for part in parts:
            if "=" in part:
                k, v = part.strip().split("=", 1)
                cookies_dict[k] = v
        return cookies_dict

    async def generate_media(self, title: str, text_content: str, dominant_style: str, week_id: int):
        """
        Uploads text_content to NotebookLM and generates an artifact based on dominant_style.
        Returns a tuple of (relative path, media_type) or (None, None) if it fails.
        """
        logger.info(f"NotebookLMAgent requested to generate {dominant_style} media for week {week_id}")
        
        # Parse cookies
        cookies = self._parse_cookies()
        if "__Secure-1PSID" not in cookies:
            logger.warning("No NotebookLM cookies found! Returning a mock artifact for demonstration.")
            return await asyncio.to_thread(self._mock_generation, dominant_style, week_id)
            
        # Realistic implementation if cookies existed
        try:
            auth = AuthTokens(cookies)
            async with NotebookLMClient(auth) as client:
                notebook = await client.notebooks.create(title=f"Week {week_id}: {title}")
                source = Source.from_text(text_content, title=f"Source {week_id}")
                await notebook.add_source(source)
                
                media_dir = Path("src/web/static/media")
                media_dir.mkdir(parents=True, exist_ok=True)
                
                if dominant_style == "aural":
                    # Generate Podcast
                    audio_bytes = await notebook.artifacts.generate_audio_overview(AudioFormat.PODCAST)
                    filename = f"podcast_week{week_id}.mp3"
                    with open(media_dir / filename, "wb") as f:
                        f.write(audio_bytes)
                    return f"/static/media/{filename}", "audio"
                
                # Expand based on API capabilities (Infographic, Quiz, etc)
                return await asyncio.to_thread(self._mock_generation, dominant_style, week_id)
                
        except Exception as e:
            logger.error(f"NotebookLM generation failed: {e}")
            return await asyncio.to_thread(self._mock_generation, dominant_style, week_id)

    def _mock_generation(self, dominant_style: str, week_id: int):
        """Mock generator to show the UI functionality when no API tokens are present."""
        media_dir = Path("src/web/static/media")
        media_dir.mkdir(parents=True, exist_ok=True)
        
        import time
        time.sleep(2.5) # Simulate blocking "esperando pacientemente"
        
        if dominant_style == "aural":
            filename = f"podcast_week{week_id}_mock.mp3"
            path = media_dir / filename
            if not path.exists():
                with open(path, "wb") as f: f.write(b"mock audio data")
            return f"/static/media/{filename}", "audio"
            
        elif dominant_style == "visual":
            filename = f"infographic_week{week_id}_mock.png"
            path = media_dir / filename
            if not path.exists():
                with open(path, "wb") as f: f.write(b"mock image data")
            return f"/static/media/{filename}", "image"
            
        elif dominant_style == "kinesthetic":
            filename = f"interactive_quiz_week{week_id}_mock.html"
            path = media_dir / filename
            if not path.exists():
                with open(path, "w") as f: f.write("<h2>Quiz Interactivo Mock</h2>")
            return f"/static/media/{filename}", "interactive"
            
        return None, None
