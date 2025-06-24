import tkinter as tk
from tkinter import messagebox
from TTS.api import TTS
import sounddevice as sd
import re

# Lade das TTS-Modell beim Start
print("Lade TTS-Modell, bitte warten ...")
tts = TTS(model_name="tts_models/de/thorsten/tacotron2-DDC", progress_bar=False, gpu=False)
print("Modell geladen!")

def replace_umlaute(text):
    # Ersetze Umlaute durch ae, oe, ue usw.
    text = re.sub(r'ä', 'ae', text)
    text = re.sub(r'ö', 'oe', text)
    text = re.sub(r'ü', 'ue', text)
    text = re.sub(r'Ä', 'Ae', text)
    text = re.sub(r'Ö', 'Oe', text)
    text = re.sub(r'Ü', 'Ue', text)
    text = re.sub(r'ß', 'ss', text)
    return text

def speak(text):
    text = replace_umlaute(text)
    if not text.strip():
        messagebox.showwarning("Warnung", "Bitte gib einen Text ein!")
        return
    wav = tts.tts(text)
    sd.play(wav, samplerate=tts.synthesizer.output_sample_rate)
    sd.wait()

# GUI mit tkinter
root = tk.Tk()
root.title("Einfache TTS Demo")

label = tk.Label(root, text="Text eingeben:")
label.pack(padx=10, pady=5)

text_entry = tk.Entry(root, width=60)
text_entry.pack(padx=10, pady=5)


def on_speak():
    text = text_entry.get()
    speak(text)

speak_button = tk.Button(root, text="Vorlesen", command=on_speak)
speak_button.pack(padx=10, pady=10)

root.mainloop()
