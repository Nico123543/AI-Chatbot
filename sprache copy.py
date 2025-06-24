from TTS.api import TTS
import torchaudio
import torch
import sounddevice as sd

# Lade ein deutsches TTS-Modell (z.B. von Coqui)
tts = TTS(model_name="tts_models/de/thorsten/tacotron2-DDC", progress_bar=False, gpu=False)

def speak(text):
    # Text zu Audio (als NumPy-Array)
    wav = tts.tts(text)
    # In Torch-Tensor umwandeln
    audio_tensor = torch.tensor(wav).unsqueeze(0)
    # Mit torchaudio abspielen (oder sounddevice)
    sd.play(wav, samplerate=tts.synthesizer.output_sample_rate)
    sd.wait()

# Beispiel
speak("Israel hat das iranische Regime im Rekordtempo geschwaecht. Nun sind selbst die Atomanlagen des Landes schwer getroffen, trotzdem geht der Krieg weiter. Was macht Premier Netanyahu als nächstes?")