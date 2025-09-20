import requests
import os
from dotenv import load_dotenv
import logging
import json

load_dotenv()

SPEECH_KEY = os.getenv("AZURE_SPEECH_KEY")
SERVICE_REGION = os.getenv("AZURE_SPEECH_REGION")

def listen(audio_bytes=None):
    """
    Speech-to-text using Azure Speech REST API (no file system operations)
    """
    if not audio_bytes:
        return "No audio data provided"
    
    try:
        # API endpoint
        url = f"https://{SERVICE_REGION}.stt.speech.microsoft.com/speech/recognition/conversation/cognitiveservices/v1"
        
        # Headers
        headers = {
            "Ocp-Apim-Subscription-Key": SPEECH_KEY,
            "Content-Type": "audio/wav; codecs=audio/pcm; samplerate=16000",
            "Accept": "application/json"
        }
        
        # Parameters
        params = {
            "language": "en-US",
            "format": "detailed"
        }
        
        # Send request
        response = requests.post(url, headers=headers, params=params, data=audio_bytes)
        
        if response.status_code == 200:
            result = response.json()
            if result["RecognitionStatus"] == "Success":
                return result["DisplayText"]
            else:
                return f"Recognition failed: {result['RecognitionStatus']}"
        else:
            return f"API error: {response.status_code} - {response.text}"
            
    except Exception as e:
        logging.error(f"REST API speech recognition error: {e}")
        return f"Error: {str(e)}"

def synthesize_text_to_audio(text: str):
    """
    Text-to-speech using Azure Speech REST API
    """
    if not text:
        return None
        
    try:
        # API endpoint
        url = f"https://{SERVICE_REGION}.tts.speech.microsoft.com/cognitiveservices/v1"
        
        # Headers
        headers = {
            "Ocp-Apim-Subscription-Key": SPEECH_KEY,
            "Content-Type": "application/ssml+xml",
            "X-Microsoft-OutputFormat": "riff-16khz-16bit-mono-pcm"
        }
        
        # SSML payload
        ssml = f"""
        <speak version='1.0' xml:lang='en-US'>
            <voice name='en-US-JennyNeural'>
                {text}
            </voice>
        </speak>
        """
        
        # Send request
        response = requests.post(url, headers=headers, data=ssml.encode('utf-8'))
        
        if response.status_code == 200:
            return response.content
        else:
            logging.error(f"TTS API error: {response.status_code} - {response.text}")
            return None
            
    except Exception as e:
        logging.error(f"REST API speech synthesis error: {e}")
        return None