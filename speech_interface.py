import azure.cognitiveservices.speech as speechsdk
import os
from dotenv import load_dotenv

load_dotenv()

SPEECH_KEY = os.getenv("AZURE_SPEECH_KEY")
SERVICE_REGION = os.getenv("AZURE_SPEECH_REGION")
speech_config = speechsdk.SpeechConfig(subscription=SPEECH_KEY, region=SERVICE_REGION)


def listen(audio_bytes=None):
   
    if audio_bytes:
        stream = speechsdk.audio.PushAudioInputStream()
        stream.write(audio_bytes)
        stream.close()
        audio_config = speechsdk.audio.AudioConfig(stream=stream)
    else:
        audio_config = speechsdk.audio.AudioConfig(use_default_microphone=True)
    
    recognizer = speechsdk.SpeechRecognizer(speech_config=speech_config, audio_config=audio_config)
    result = recognizer.recognize_once()
    
    if result.reason == speechsdk.ResultReason.RecognizedSpeech:
        return result.text
    return None


def synthesize_text_to_audio(text: str):
 
    if not text:
        return None

    
    synthesizer = speechsdk.SpeechSynthesizer(speech_config=speech_config, audio_config=None)
    result = synthesizer.speak_text_async(text).get()

    if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
        return result.audio_data
    return None


def speak(text: str):
   
    synthesizer = speechsdk.SpeechSynthesizer(speech_config=speech_config)
    synthesizer.speak_text_async(text).get()
