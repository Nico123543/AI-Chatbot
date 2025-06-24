import tkinter as tk
from tkinter import scrolledtext, messagebox
import requests
import threading
import re
import sounddevice as sd
from TTS.api import TTS
import vosk
import pyaudio
import json

# --- LLM Studio Einstellungen ---
LMSTUDIO_URL = "http://localhost:1234/v1/chat/completions"
LMSTUDIO_MODELS_URL = "http://localhost:1234/v1/models"

# --- TTS initialisieren ---
print("Lade TTS-Modell, bitte warten ...")
tts = TTS(model_name="tts_models/de/thorsten/tacotron2-DDC", progress_bar=False, gpu=False)
print("TTS-Modell geladen!")

def clean_text_for_tts(text):
    # 1. Markdown entfernen (Sterne, Rauten, Backticks etc.)
    text = re.sub(r'[\*#`]', '', text)
    # Nummerierte Listen am Zeilenanfang entfernen (z.B. "1. ")
    text = re.sub(r'^\s*\d+\.\s*', '', text, flags=re.MULTILINE)

    # 2. Emojis und andere nicht-sprachliche Symbole entfernen
    emoji_pattern = re.compile(
        "["
        u"\\U0001F600-\\U0001F64F"  # emoticons
        u"\\U0001F300-\\U0001F5FF"  # symbols & pictographs
        u"\\U0001F680-\\U0001F6FF"  # transport & map symbols
        u"\\U0001F1E0-\\U0001F1FF"  # flags (iOS)
        u"\\U00002700-\\U000027BF"  # Dingbats
        u"\\U0001f900-\\U0001f9ff"  # Supplemental Symbols and Pictographs
        "]+",
        flags=re.UNICODE,
    )
    text = emoji_pattern.sub(r'', text)

    # 3. Umlaute ersetzen für bessere Kompatibilität
    text = re.sub(r'ä', 'ae', text)
    text = re.sub(r'ö', 'oe', text)
    text = re.sub(r'ü', 'ue', text)
    text = re.sub(r'Ä', 'Ae', text)
    text = re.sub(r'Ö', 'Oe', text)
    text = re.sub(r'Ü', 'Ue', text)
    text = re.sub(r'ß', 'ss', text)
    return text

def speak(text):
    text = clean_text_for_tts(text)
    if not text.strip():
        return
    wav = tts.tts(text)
    sd.play(wav, samplerate=tts.synthesizer.output_sample_rate)
    sd.wait()

# --- Speech-to-Text (Vosk) ---
def recognize_speech():
    try:
        model = vosk.Model(lang="de")
        rec = vosk.KaldiRecognizer(model, 16000)
        p = pyaudio.PyAudio()
        stream = p.open(format=pyaudio.paInt16,
                        channels=1,
                        rate=16000,
                        input=True,
                        frames_per_buffer=8192)
        print("Sprich jetzt...")
        result_text = ""
        while True:
            data = stream.read(4096)
            if rec.AcceptWaveform(data):
                result = json.loads(rec.Result())
                recognized_text = result['text']
                if recognized_text:
                    result_text += recognized_text + " "
                    break  # Nur eine Äußerung aufnehmen
        stream.stop_stream()
        stream.close()
        p.terminate()
        return result_text.strip()
    except Exception as e:
        print(f"Fehler bei Speech-to-Text: {e}")
        return ""

# --- GUI ---
class ChatBotApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Chatbot mit Spracheingabe & Sprachausgabe")
        self.root.geometry("600x650")  # Höhe angepasst für das Menü
        self.messages = [
            {"role": "system", "content": "Du bist ein KI-Assistent. Antworte immer auf Deutsch, egal in welcher Sprache die Frage gestellt wird."}
        ]
        self.model_names = ["Kein Modell geladen"]
        self.selected_model = tk.StringVar(value=self.model_names[0])

        # --- Modellauswahl ---
        model_frame = tk.Frame(root)
        model_frame.pack(padx=10, pady=5, fill=tk.X)
        model_label = tk.Label(model_frame, text="Modell:")
        model_label.pack(side=tk.LEFT, padx=(0, 5))
        self.model_menu = tk.OptionMenu(model_frame, self.selected_model, *self.model_names)
        self.model_menu.pack(expand=True, fill=tk.X)

        self.chat_area = scrolledtext.ScrolledText(root, wrap=tk.WORD, state='disabled')
        self.chat_area.pack(padx=10, pady=10, fill=tk.BOTH, expand=True)

        self.entry = tk.Entry(root)
        self.entry.pack(padx=10, pady=(0,10), fill=tk.X)
        self.entry.bind('<Return>', self.send_message)

        frame = tk.Frame(root)
        frame.pack(padx=10, pady=(0,10))

        self.send_button = tk.Button(frame, text="Senden", command=self.send_message)
        self.send_button.pack(side=tk.LEFT, padx=5)

        self.speech_button = tk.Button(frame, text="🎤 Spracheingabe", command=self.speech_to_text)
        self.speech_button.pack(side=tk.LEFT, padx=5)

        self.check_server_connection()
        threading.Thread(target=self.load_models, daemon=True).start()

    def load_models(self):
        """Lädt verfügbare Modelle vom Server und aktualisiert das Dropdown-Menü."""
        try:
            response = requests.get(LMSTUDIO_MODELS_URL, timeout=5)
            response.raise_for_status()
            models_data = response.json().get("data", [])
            self.model_names = [model.get("id") for model in models_data if model.get("id")]

            def update_ui():
                menu = self.model_menu["menu"]
                menu.delete(0, "end")
                if self.model_names:
                    for model_name in self.model_names:
                        menu.add_command(label=model_name, command=tk._setit(self.selected_model, model_name))
                    self.selected_model.set(self.model_names[0])
                else:
                    self.selected_model.set("Keine Modelle gefunden")
            self.root.after(0, update_ui)
        except Exception as e:
            print(f"Fehler beim Laden der Modelle: {e}")
            self.root.after(0, lambda: self.selected_model.set("Server nicht erreichbar"))

    def check_server_connection(self):
        try:
            response = requests.get(LMSTUDIO_MODELS_URL, timeout=3)
            response.raise_for_status()
            self.root.title("Chatbot (Server verbunden)")
        except Exception as e:
            self.append_chat("System", f"Server nicht erreichbar: {e}")

    def send_message(self, event=None):
        user_message = self.entry.get().strip()
        if user_message:
            self.entry.delete(0, tk.END)
            self._send_user_message(user_message)

    def _send_user_message(self, user_message):
        """Verarbeitet und sendet eine Nachricht des Benutzers an die LLM."""
        if not user_message:
            return
        self.append_chat("Du", user_message)
        self.messages.append({"role": "user", "content": user_message})
        threading.Thread(target=self.get_lmstudio_response, daemon=True).start()

    def append_chat(self, sender, message):
        self.chat_area.config(state='normal')
        self.chat_area.insert(tk.END, f"{sender}: {message}\n")
        self.chat_area.config(state='disabled')
        self.chat_area.see(tk.END)

    def get_lmstudio_response(self):
        selected = self.selected_model.get()
        if not selected or "Kein" in selected or "Fehler" in selected:
            self.root.after(0, lambda: self.append_chat("System", "Bitte zuerst ein gültiges Modell auswählen."))
            return
            
        try:
            payload = {
                "model": selected,
                "messages": self.messages,
                "temperature": 0.7,
                "max_tokens": -1,
                "stream": True
            }
            response = requests.post(LMSTUDIO_URL, json=payload, timeout=600, stream=True)
            response.raise_for_status()
            
            self.root.after(0, self.start_assistant_message)
            
            full_response_for_history = ""
            visible_response_for_ui_and_tts = ""
            is_inside_think_tag = False

            for line in response.iter_lines():
                if line:
                    decoded_line = line.decode('utf-8')
                    if decoded_line.startswith('data: '):
                        content = decoded_line[6:]
                        if content.strip() == '[DONE]':
                            break
                        try:
                            data = json.loads(content)
                            delta = data.get('choices', [{}])[0].get('delta', {}).get('content', '')
                            if delta:
                                full_response_for_history += delta
                                
                                temp_chunk = delta
                                while temp_chunk:
                                    if not is_inside_think_tag:
                                        think_start_pos = temp_chunk.find("<think>")
                                        if think_start_pos != -1:
                                            part_to_display = temp_chunk[:think_start_pos]
                                            if part_to_display:
                                                visible_response_for_ui_and_tts += part_to_display
                                                self.root.after(0, lambda d=part_to_display: self.append_chat_delta(d))
                                            is_inside_think_tag = True
                                            temp_chunk = temp_chunk[think_start_pos + len("<think>"):]
                                        else:
                                            visible_response_for_ui_and_tts += temp_chunk
                                            self.root.after(0, lambda d=temp_chunk: self.append_chat_delta(d))
                                            temp_chunk = ""
                                    else: # Inside a think tag
                                        think_end_pos = temp_chunk.find("</think>")
                                        if think_end_pos != -1:
                                            is_inside_think_tag = False
                                            temp_chunk = temp_chunk[think_end_pos + len("</think>"):]
                                        else:
                                            temp_chunk = "" # Discard chunk
                        except json.JSONDecodeError:
                            continue
            
            self.root.after(0, lambda: self.append_chat_delta("\\n"))
            self.messages.append({"role": "assistant", "content": full_response_for_history})
            # Sprachausgabe der gefilterten Bot-Antwort
            threading.Thread(target=speak, args=(visible_response_for_ui_and_tts,), daemon=True).start()
        except Exception as e:
            answer = f"[Fehler: {e}]"
            self.root.after(0, lambda: self.append_chat("Bot", answer))

    def start_assistant_message(self):
        self.chat_area.config(state='normal')
        self.chat_area.insert(tk.END, "Bot: ")
        self.chat_area.config(state='disabled')
        self.chat_area.see(tk.END)

    def append_chat_delta(self, delta):
        self.chat_area.config(state='normal')
        self.chat_area.insert(tk.END, delta)
        self.chat_area.config(state='disabled')
        self.chat_area.see(tk.END)

    def speech_to_text(self):
        self.speech_button.config(state='disabled', text="🎤 Höre zu...")

        def recognize_and_send():
            recognized_text = recognize_speech()

            def handle_ui_updates():
                self.speech_button.config(state='normal', text="🎤 Spracheingabe")
                if recognized_text:
                    # Direkte Übergabe an die LLM ohne Prüfung
                    self._send_user_message(recognized_text)
                else:
                    messagebox.showinfo("Info", "Keine Sprache erkannt.")
            
            self.root.after(0, handle_ui_updates)

        threading.Thread(target=recognize_and_send, daemon=True).start()

if __name__ == "__main__":
    root = tk.Tk()
    app = ChatBotApp(root)
    root.mainloop()
