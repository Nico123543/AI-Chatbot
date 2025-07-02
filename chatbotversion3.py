import tkinter as tk
from tkinter import scrolledtext, messagebox
import requests
import threading
import re
import pyttsx3
import vosk
import pyaudio
import json
import cv2
from PIL import Image, ImageTk
import queue
import time


# --- LLM Studio Einstellungen ---
LMSTUDIO_URL = "http://localhost:1234/v1/chat/completions"
LMSTUDIO_MODELS_URL = "http://localhost:1234/v1/models"


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
    return text

def recognize_speech():
    try:
        print("DEBUG: recognize_speech started")
        model = vosk.Model(lang="de")
        print("DEBUG: Vosk model loaded")
        rec = vosk.KaldiRecognizer(model, 16000)
        print("DEBUG: KaldiRecognizer created")
        p = pyaudio.PyAudio()
        print("DEBUG: PyAudio object created")
        stream = p.open(format=pyaudio.paInt16,
                        channels=1,
                        rate=16000,
                        input=True,
                        frames_per_buffer=8192)
        print("DEBUG: PyAudio stream opened. Sprich jetzt...")
        result_text = ""
        while True:
            data = stream.read(4096)
            if rec.AcceptWaveform(data):
                result = json.loads(rec.Result())
                recognized_text = result['text']
                print(f"DEBUG: Recognized chunk: '{recognized_text}'")
                if recognized_text:
                    result_text += recognized_text + " "
                    break  # Nur eine Äußerung aufnehmen
        print(f"DEBUG: Final recognized text: '{result_text.strip()}'")
        stream.stop_stream()
        stream.close()
        p.terminate()
        print("DEBUG: Stream closed and PyAudio terminated")
        return result_text.strip()
    except Exception as e:
        print(f"!!! FEHLER bei Speech-to-Text: {e}")
        import traceback
        traceback.print_exc()
        return ""

# --- GUI ---
class ChatBotApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Chatbot mit Spracheingabe & Sprachausgabe")
        self.root.geometry("600x650")
        self.messages = [
            {"role": "system", "content": "Du bist ein KI-Assistent. Antworte immer auf Deutsch, egal in welcher Sprache die Frage gestellt wird."}
        ]
        self.model_names = ["Kein Modell geladen"]
        self.selected_model = tk.StringVar(value=self.model_names[0])
        self.deepseek_label = "DeepSeek (API)"

        # --- TTS Engine (pyttsx3) initialisieren ---
        self.tts_engine = pyttsx3.init()
        voices = self.tts_engine.getProperty('voices')
        for voice in voices:
            if 'german' in voice.name.lower() or 'hedda' in voice.name.lower():
                self.tts_engine.setProperty('voice', voice.id)
                break
        self.is_speaking = False
        self.tts_queue = queue.Queue()
        # pyttsx3 Callback-Events verbinden
        self.tts_engine.connect('started-utterance', self._on_tts_start)
        self.tts_engine.connect('finished-utterance', self._on_tts_end)

        # --- Video-Thread & Frame-Queue ---
        self.video_path = "Avatar IV Video.mp4"
        orig_w, orig_h = self.get_video_size(self.video_path)
        self.video_width = max(1, orig_w // 3)
        self.video_height = max(1, orig_h // 3)
        self.standbild = self.get_first_frame_image(self.video_path)
        self.image_label = tk.Label(root)
        self.image_label.pack(padx=10, pady=10)
        if self.standbild:
            self.image_label.config(image=self.standbild, width=self.video_width, height=self.video_height)
            self.image_label.image = self.standbild
        else:
            self.image_label.config(text="[Kein Standbild verfügbar]", width=self.video_width, height=self.video_height)

        # VideoCapture und Frame-Queue initialisieren
        self.cap = cv2.VideoCapture(self.video_path)
        self.frame_queue = queue.Queue(maxsize=10)
        self.playing = False
        self.target_fps = int(self.cap.get(cv2.CAP_PROP_FPS)) or 25
        threading.Thread(target=self._decode_frames, daemon=True).start()

        # --- Modellauswahl ---
        model_frame = tk.Frame(root)
        model_frame.pack(padx=10, pady=5, fill=tk.X)
        model_label = tk.Label(model_frame, text="Modell:")
        model_label.pack(side=tk.LEFT, padx=(0, 5))
        self.model_menu = tk.OptionMenu(model_frame, self.selected_model, *self.model_names, self.deepseek_label)
        self.model_menu.pack(expand=True, fill=tk.X)

        self.chat_area = scrolledtext.ScrolledText(root, wrap=tk.WORD, state='disabled')
        self.chat_area.pack(padx=10, pady=10, fill=tk.BOTH, expand=True)

        self.entry = tk.Entry(root)
        self.entry.pack(padx=10, pady=(0, 10), fill=tk.X)
        self.entry.bind('<Return>', self.send_message)

        frame = tk.Frame(root)
        frame.pack(padx=10, pady=(0, 10))

        self.send_button = tk.Button(frame, text="Senden", command=self.send_message)
        self.send_button.pack(side=tk.LEFT, padx=5)

        self.speech_button = tk.Button(frame, text="🎤 Spracheingabe", command=self.speech_to_text)
        self.speech_button.pack(side=tk.LEFT, padx=5)

        self.check_server_connection()
        threading.Thread(target=self.load_models, daemon=True).start()

    def get_video_size(self, video_path):
        try:
            cap = cv2.VideoCapture(video_path)
            if not cap.isOpened(): return 400, 225
            width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            cap.release()
            return width, height
        except Exception:
            return 400, 225

    def get_first_frame_image(self, video_path):
        try:
            cap = cv2.VideoCapture(video_path)
            ret, frame = cap.read()
            cap.release()
            if ret:
                frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                img = Image.fromarray(frame)
                img = img.resize((self.video_width, self.video_height))
                return ImageTk.PhotoImage(img)
            else: return None
        except Exception as e:
            print(f"Fehler beim Laden des Standbilds: {e}")
            return None

    def _decode_frames(self):
        while True:
            if not self.playing:
                time.sleep(0.1)
                continue
            ret, frame = self.cap.read()
            if not ret:
                self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                continue
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            img = Image.fromarray(frame).resize((self.video_width, self.video_height))
            imgtk = ImageTk.PhotoImage(img)
            if self.frame_queue.full():
                try:
                    self.frame_queue.get_nowait()
                except queue.Empty:
                    pass
            self.frame_queue.put(imgtk)

    def play_video_loop(self):
        if not self.playing:
            # Video anhalten und Standbild zeigen
            if self.standbild:
                self.image_label.config(image=self.standbild, width=self.video_width, height=self.video_height)
                self.image_label.image = self.standbild
            return
        try:
            imgtk = self.frame_queue.get_nowait()
            self.image_label.config(image=imgtk, width=self.video_width, height=self.video_height)
            self.image_label.image = imgtk
        except queue.Empty:
            pass
        self.root.after(int(1000/self.target_fps), self.play_video_loop)

    def _on_tts_start(self, name):
        self.is_speaking = True
        self.playing = True
        self.root.after(0, self.play_video_loop)

    def _on_tts_end(self, name, completed=True):
        self.is_speaking = False
        self.playing = False
        # Nach dem Sprechen Standbild anzeigen
        if self.standbild:
            self.image_label.config(image=self.standbild, width=self.video_width, height=self.video_height)
            self.image_label.image = self.standbild

    def tts_consumer_loop(self):
        """Verarbeitet die TTS-Warteschlange und steuert die Animation."""
        # Wir sammeln größere Chunks (z.B. 2 Sätze oder 200 Wörter)
        batch = ""
        max_words = 200
        sentence_endings = re.compile(r'[.!?]\s+')
        tts_start_time = None
        tts_end_time = None
        word_count = 0
        first_chunk = True
        while True:
            try:
                chunk = self.tts_queue.get()
                if chunk is None:
                    # Restlichen Batch sprechen
                    if batch.strip():
                        self._speak_batch(batch)
                        batch = ""
                    break
                cleaned_chunk = clean_text_for_tts(chunk)
                if cleaned_chunk.strip():
                    batch += cleaned_chunk + " "
                    # Prüfen, ob Batch-Kriterien erfüllt sind
                    sentences = sentence_endings.split(batch)
                    words = batch.split()
                    if len(sentences) > 2 or len(words) > max_words:
                        self._speak_batch(batch)
                        word_count += len(words)
                        batch = ""
            finally:
                self.tts_queue.task_done()
        # Statistik
        tts_end_time = time.time()
        if tts_start_time and tts_end_time and word_count > 0:
            duration_min = (tts_end_time - tts_start_time) / 60.0
            wpm = word_count / duration_min if duration_min > 0 else 0
            print(f"[Sprechgeschwindigkeit: {wpm:.1f} Wörter/Minute]")
        self.is_speaking = False
        self.playing = False

    def _speak_batch(self, text):
        # pyttsx3 übernimmt das Event-Handling für Animation
        self.tts_engine.say(text)
        self.tts_engine.runAndWait()

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
                # DeepSeek immer als Option hinzufügen
                menu.add_command(label=self.deepseek_label, command=tk._setit(self.selected_model, self.deepseek_label))
                if self.model_names:
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
            if selected == self.deepseek_label:
                # Anfrage an DeepSeek API
                api_url = "https://api.deepseek.com/v1/chat/completions"
                api_key = "sk-28a5945c8c8d42feada2aac62622f2b4"
                payload = {
                    "model": "deepseek-reasoner",
                    "messages": self.messages,
                    "temperature": 1.5,
                    "max_tokens": 8192,
                    "stream": True
                }
                headers = {
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json"
                }
                response = requests.post(api_url, json=payload, headers=headers, timeout=600, stream=True, verify=False)
            else:
                payload = {
                    "model": selected, "messages": self.messages, "temperature": 0.7,
                    "max_tokens": -1, "stream": True
                }
                response = requests.post(LMSTUDIO_URL, json=payload, timeout=600, stream=True)
            response.raise_for_status()
            
            # Zeitstempel für Latenz-Messung
            self.first_token_time = None
            self.tts_start_time = None
            self.tts_word_count = 0
            self.tts_total_text = ""

            # Token- und Buchstaben-Counter
            token_count = 0
            char_count = 0

            # Starte den TTS-Consumer-Thread für diese Antwort
            threading.Thread(target=self.tts_consumer_loop, daemon=True).start()

            self.root.after(0, self.start_assistant_message)
            full_response_for_history = ""
            tts_buffer = ""

            for line in response.iter_lines():
                if line:
                    decoded_line = line.decode('utf-8')
                    if decoded_line.startswith('data: '):
                        content = decoded_line[6:]
                        if content.strip() == '[DONE]': break
                        try:
                            data = json.loads(content)
                            delta = data.get('choices', [{}])[0].get('delta', {}).get('content', '')
                            if delta:
                                if self.first_token_time is None:
                                    self.first_token_time = time.time()
                                full_response_for_history += delta
                                # UI sofort aktualisieren
                                self.root.after(0, lambda d=delta: self.append_chat_delta(d))

                                tts_buffer += delta
                                # Token- und Buchstaben zählen
                                token_count += len(delta.split())
                                char_count += len(delta)

                                # Prüfen, ob ein Satzende vorhanden ist
                                last_terminator = -1
                                for term in ['.', '!', '?', '\n', ':']:
                                    last_terminator = max(last_terminator, tts_buffer.rfind(term))

                                if last_terminator != -1:
                                    chunk_to_speak = tts_buffer[:last_terminator + 1]
                                    tts_buffer = tts_buffer[last_terminator + 1:]
                                    self.tts_total_text += chunk_to_speak
                                    self.tts_queue.put(chunk_to_speak)

                        except json.JSONDecodeError:
                            continue
            # Restlichen Pufferinhalt zur Warteschlange hinzufügen
            if tts_buffer.strip():
                self.tts_total_text += tts_buffer
                self.tts_queue.put(tts_buffer)

            # Sentinel hinzufügen, um dem Consumer-Thread das Ende zu signalisieren
            self.tts_queue.put(None)

            # Token- und Buchstaben-Statistik ausgeben
            print(f"[Antwort-Statistik] Tokens (geschätzt): {token_count}, Buchstaben: {char_count}")

            self.root.after(0, lambda: self.append_chat_delta("\n"))
            self.messages.append({"role": "assistant", "content": full_response_for_history})

        except Exception as e:
            answer = f"[Fehler: {e}]"
            self.root.after(0, lambda: self.append_chat("Bot", answer))
            # Sicherstellen, dass der TTS-Thread beendet wird, auch bei Fehlern
            self.tts_queue.put(None)

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
                    self._send_user_message(recognized_text)
                else:
                    messagebox.showinfo("Info", "Keine Sprache erkannt.")
            self.root.after(0, handle_ui_updates)
        threading.Thread(target=recognize_and_send, daemon=True).start()

if __name__ == "__main__":
    root = tk.Tk()
    app = ChatBotApp(root)
    root.mainloop()
