import requests
import os
from dotenv import load_dotenv
import logging
import json
from azure.identity import DefaultAzureCredential
from azure.keyvault.secrets import SecretClient

load_dotenv()

SERVICE_REGION = os.getenv("AZURE_SPEECH_REGION")
KEYVAULT_NAME = os.getenv("KEYVAULT_NAME")

# Cache for speech key
_speech_key = None

def get_speech_key():
    """Lazy load speech key from environment first, then Key Vault"""
    global _speech_key
    if _speech_key is None:
        # Try environment variable first
        _speech_key = os.getenv("AZURE_SPEECH_KEY")
        if _speech_key:
            print("Using Speech key from environment variable")
            return _speech_key
            
        print("Speech key not found in environment, trying Key Vault...")
        
        # Fall back to Key Vault
        if not KEYVAULT_NAME:
            raise ValueError("KEYVAULT_NAME is not set in environment variables")
        
        try:
            keyvault_url = f"https://{KEYVAULT_NAME}.vault.azure.net/"
            credential = DefaultAzureCredential()
            secret_client = SecretClient(vault_url=keyvault_url, credential=credential)
            _speech_key = secret_client.get_secret("AZURE-SPEECH-KEY").value
            print(" Successfully fetched Speech key from Key Vault")
        except Exception as e:
            print(f" Error fetching Speech key from Key Vault: {e}")
            print(" Make sure AZURE_SPEECH_KEY is set in local.settings.json")
            raise ValueError("Could not get Speech key from environment or Key Vault")
    return _speech_key

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
            "Ocp-Apim-Subscription-Key": get_speech_key(),  # Use getter function
            "Content-Type": "audio/wav; codecs=audio/pcm; samplerate=16000",
            "Accept": "application/json"
        }
        
        params = {"language": "en-US", "format": "detailed"}
        
        response = requests.post(url, headers=headers, params=params, data=audio_bytes)
        
        if response.status_code == 200:
            result = response.json()
            if result.get("RecognitionStatus") == "Success":
                return result.get("DisplayText", "")
            else:
                return f"Recognition failed: {result.get('RecognitionStatus')}"
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
        url = f"https://{SERVICE_REGION}.tts.speech.microsoft.com/cognitiveservices/v1"
        
        headers = {
            "Ocp-Apim-Subscription-Key": get_speech_key(),  # Use getter function
            "Content-Type": "application/ssml+xml",
            "X-Microsoft-OutputFormat": "riff-16khz-16bit-mono-pcm"
        }
        
        ssml = f"""
        <speak version='1.0' xml:lang='en-US'>
            <voice name='en-US-JennyNeural'>
                {text}
            </voice>
        </speak>
        """
        
        response = requests.post(url, headers=headers, data=ssml.encode('utf-8'))
        
        if response.status_code == 200:
            return response.content
        else:
            logging.error(f"TTS API error: {response.status_code} - {response.text}")
            return None
            
    except Exception as e:
        logging.error(f"REST API speech synthesis error: {e}")
        return None