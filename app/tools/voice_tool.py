import asyncio
import base64
import io
import re
import wave

import httpx

from app.common.custom_exception import CustomException
from app.common.logger import get_logger
from app.config.config import (
    get_sarvam_api_key,
    SARVAM_STT_MODE,
    SARVAM_TTS_LANGUAGE,
    SARVAM_TTS_PACE,
    SARVAM_TTS_SPEAKER,
    SARVAM_TTS_TEMPERATURE,
)

logger = get_logger(__name__)

SARVAM_STT_URL = "https://api.sarvam.ai/speech-to-text"
SARVAM_TTS_URL = "https://api.sarvam.ai/text-to-speech"
SARVAM_STT_MODEL = "saaras:v3"
SARVAM_TTS_MODEL = "bulbul:v3"
STT_CHUNK_SECONDS = 25
TTS_CHUNK_MAX_CHARS = 2400
TTS_STREAM_CHUNK_MAX_CHARS = 180


def prepare_tts_text(text: str) -> str:
    cleaned = re.sub(r"[*#_\[\]{}`]", "", text or "")
    cleaned = cleaned.replace("—", ", ").replace("–", ", ")
    return re.sub(r"\s+", " ", cleaned).strip()


def split_tts_chunks(text: str, max_len: int = TTS_CHUNK_MAX_CHARS) -> list[str]:
    if len(text) <= max_len:
        return [text]
    sentences = re.split(r"(?<=[.!?।॥؟।])\s+", text)
    chunks: list[str] = []
    current = ""
    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
        if len(sentence) > max_len:
            if current:
                chunks.append(current)
                current = ""
            for i in range(0, len(sentence), max_len):
                chunks.append(sentence[i : i + max_len])
            continue
        candidate = f"{current} {sentence}".strip()
        if len(candidate) <= max_len:
            current = candidate
        else:
            if current:
                chunks.append(current)
            current = sentence
    if current:
        chunks.append(current)
    return chunks or [text[:max_len]]


def silence_frames(params: wave._wave_params, ms: int = 35) -> bytes:
    nchannels, sampwidth, framerate, _, _ = params
    nframes = int(framerate * ms / 1000)
    return b"\x00" * (nframes * nchannels * sampwidth)


def concat_wav(wavs: list[bytes]) -> bytes:
    if not wavs:
        return b""
    if len(wavs) == 1:
        return wavs[0]

    out_buf = io.BytesIO()
    params = None
    all_frames: list[bytes] = []
    for i, wav_bytes in enumerate(wavs):
        with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
            chunk_params = wf.getparams()
            if params is None:
                params = chunk_params
            all_frames.append(wf.readframes(wf.getnframes()))
            if i < len(wavs) - 1:
                all_frames.append(silence_frames(chunk_params))

    with wave.open(out_buf, "wb") as out:
        out.setparams(params)
        for frame in all_frames:
            out.writeframes(frame)
    return out_buf.getvalue()


def is_wav(audio_bytes: bytes) -> bool:
    return len(audio_bytes) >= 4 and audio_bytes[:4] == b"RIFF"


def split_wav_chunks(audio_bytes: bytes, chunk_seconds: int = STT_CHUNK_SECONDS) -> list[bytes]:
    """Split WAV into chunks for STT when answer exceeds API duration limit."""
    if not is_wav(audio_bytes):
        return [audio_bytes]

    with wave.open(io.BytesIO(audio_bytes), "rb") as wf:
        channels = wf.getnchannels()
        sample_width = wf.getsampwidth()
        rate = wf.getframerate()
        frames = wf.readframes(wf.getnframes())

    if not frames:
        return [audio_bytes]

    frames_per_chunk = int(rate * chunk_seconds)
    bytes_per_frame = channels * sample_width
    chunks: list[bytes] = []

    for start in range(0, len(frames) // bytes_per_frame, frames_per_chunk):
        chunk_frames = frames[start * bytes_per_frame : (start + frames_per_chunk) * bytes_per_frame]
        if not chunk_frames:
            continue
        buf = io.BytesIO()
        with wave.open(buf, "wb") as out:
            out.setnchannels(channels)
            out.setsampwidth(sample_width)
            out.setframerate(rate)
            out.writeframes(chunk_frames)
        chunks.append(buf.getvalue())

    return chunks or [audio_bytes]


class SttTool:
    @staticmethod
    def guess_filename(content_type: str) -> tuple[str, str]:
        ct = (content_type or "audio/wav").lower()
        if "webm" in ct:
            return "audio.webm", "audio/webm"
        if "ogg" in ct:
            return "audio.ogg", "audio/ogg"
        if "mp4" in ct or "m4a" in ct:
            return "audio.m4a", "audio/mp4"
        return "audio.wav", "audio/wav"

    async def transcribe_chunk(
        self, client: httpx.AsyncClient, audio_bytes: bytes, content_type: str = "audio/wav"
    ) -> str:
        headers = {"api-subscription-key": get_sarvam_api_key()}
        filename, mime = self.guess_filename(content_type)
        files = {"file": (filename, audio_bytes, mime)}
        data = {"model": SARVAM_STT_MODEL, "mode": SARVAM_STT_MODE}
        resp = await client.post(SARVAM_STT_URL, headers=headers, files=files, data=data)
        resp.raise_for_status()
        payload = resp.json()
        return (payload.get("transcript") or payload.get("text") or "").strip()

    async def transcribe(self, audio_bytes, content_type="audio/wav"):
        try:
            logger.info("SttTool started")
            if not get_sarvam_api_key():
                return "[mock transcript — set SARVAM_API_KEY for real STT]"

            chunks = split_wav_chunks(audio_bytes)
            parts: list[str] = []
            async with httpx.AsyncClient(timeout=120.0) as client:
                for i, chunk in enumerate(chunks):
                    text = await self.transcribe_chunk(client, chunk, content_type)
                    if text:
                        parts.append(text)
                    logger.info(f"SttTool chunk {i + 1}/{len(chunks)}: {len(text)} chars")

            transcript = " ".join(parts).strip()
            logger.info("SttTool completed")
            return transcript
        except Exception as e:
            logger.error(f"Error in SttTool: {str(e)}")
            raise CustomException("SttTool Failed", e)


class TtsTool:
    async def synthesize_one(
        self, text: str, client: httpx.AsyncClient, language_code: str
    ) -> bytes:
        headers = {"api-subscription-key": get_sarvam_api_key(), "Content-Type": "application/json"}
        payload = {
            "text": text,
            "language_code": language_code,
            "speaker": SARVAM_TTS_SPEAKER,
            "model": SARVAM_TTS_MODEL,
            "pace": SARVAM_TTS_PACE,
            "temperature": SARVAM_TTS_TEMPERATURE,
            "output_audio_codec": "wav",
        }
        resp = await client.post(SARVAM_TTS_URL, headers=headers, json=payload)
        resp.raise_for_status()
        data = resp.json()
        audios = data.get("audios") or []
        if not audios:
            raise ValueError("Sarvam TTS returned no audio")
        wavs = [base64.b64decode(a) for a in audios]
        return concat_wav(wavs)

    async def synthesize(self, text, language_code: str | None = None):
        try:
            tts_lang = language_code or SARVAM_TTS_LANGUAGE
            logger.info(f"TtsTool started ({tts_lang})")
            if not get_sarvam_api_key():
                return b""

            clean = prepare_tts_text(text)
            if not clean:
                return b""

            chunks = split_tts_chunks(clean)
            async with httpx.AsyncClient(timeout=120.0) as client:
                wavs: list[bytes] = []
                for i, chunk in enumerate(chunks):
                    wavs.append(await self.synthesize_one(chunk, client, tts_lang))
                    if i < len(chunks) - 1:
                        await asyncio.sleep(0.25)

            result = concat_wav(wavs)
            logger.info(
                f"TtsTool completed ({len(chunks)} chunk(s), {len(result)} bytes, "
                f"lang={tts_lang}, speaker={SARVAM_TTS_SPEAKER})"
            )
            return result
        except Exception as e:
            logger.error(f"Error in TtsTool: {str(e)}")
            raise CustomException("TtsTool Failed", e)

    async def synthesize_stream(self, text: str, language_code: str | None = None):
        """Async generator yielding base64 encoded wav audio chunks sentence by sentence for low-latency streaming."""
        try:
            tts_lang = language_code or SARVAM_TTS_LANGUAGE
            if not get_sarvam_api_key():
                return

            clean = prepare_tts_text(text)
            if not clean:
                return

            chunks = split_tts_chunks(clean, max_len=TTS_STREAM_CHUNK_MAX_CHARS)
            async with httpx.AsyncClient(timeout=120.0) as client:
                for i, chunk in enumerate(chunks):
                    wav_bytes = await self.synthesize_one(chunk, client, tts_lang)
                    if wav_bytes:
                        yield {
                            "index": i,
                            "total": len(chunks),
                            "text": chunk,
                            "audio_base64": base64.b64encode(wav_bytes).decode(),
                        }
                    if i < len(chunks) - 1:
                        await asyncio.sleep(0.05)
        except Exception as e:
            logger.error(f"Error in TtsTool synthesize_stream: {str(e)}")
