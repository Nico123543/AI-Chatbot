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

        # --- TTS Engine (pyttsx3) initialisieren ---
        self.tts_engine = pyttsx3.init()
        voices = self.tts_engine.getProperty('voices')
        for voice in voices:
            if 'german' in voice.name.lower():
                self.tts_engine.setProperty('voice', voice.id)
                break
        self.is_speaking = False

        # --- Standbild und Video-Infos ---
        self.video_path = "Avatar IV Video.mp4"
        orig_w, orig_h = self.get_video_size(self.video_path)
        self.video_width = max(1, orig_w // 2)
        self.video_height = max(1, orig_h // 2)
        self.standbild = self.get_first_frame_image(self.video_path)
        self.image_label = tk.Label(root)
        self.image_label.pack(padx=10, pady=10)
        if self.standbild:
            self.image_label.config(image=self.standbild, width=self.video_width, height=self.video_height)
            self.image_label.image = self.standbild
        else:
            self.image_label.config(text="[Kein Standbild verfügbar]", width=self.video_width, height=self.video_height)

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

        # --- Video nach Start einmalig abspielen ---
        self.root.after(1000, lambda: self.play_video_once())

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

    def play_video_once(self):
        """Spielt das Video einmalig ab."""
        cap = cv2.VideoCapture(self.video_path)
        if not cap.isOpened():
            print("Konnte das Video nicht öffnen.")
            return
        frame_delay = int(1000 / max(1, cap.get(cv2.CAP_PROP_FPS)))
        def show_frame():
            ret, frame = cap.read()
            if ret:
                frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                img = Image.fromarray(frame).resize((self.video_width, self.video_height))
                imgtk = ImageTk.PhotoImage(img)
                self.image_label.config(image=imgtk, width=self.video_width, height=self.video_height)
                self.image_label.image = imgtk
                self.root.after(frame_delay, show_frame)
            else:
                cap.release()
                if self.standbild:
                    self.image_label.config(image=self.standbild)
                    self.image_label.image = self.standbild
        show_frame()

    def play_video_loop(self):
        """Spielt das Video in einer Schleife ab, solange self.is_speaking True ist."""
        if not self.is_speaking:
            cap.release()
            if self.standbild:
                self.image_label.config(image=self.standbild, width=self.video_width, height=self.video_height)
                self.image_label.image = self.standbild
            return

        cap = cv2.VideoCapture(self.video_path)
        if not cap.isOpened():
            print("Konnte das Video nicht öffnen.")
            self.is_speaking = False
            return
        frame_delay = int(1000 / max(1, cap.get(cv2.CAP_PROP_FPS)))
        def show_frame():
            if not self.is_speaking:
                cap.release()
                if self.standbild:
                    self.image_label.config(image=self.standbild, width=self.video_width, height=self.video_height)
                    self.image_label.image = self.standbild
                return
            ret, frame = cap.read()
            if not ret:
                cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                ret, frame = cap.read()
            if ret:
                frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                img = Image.fromarray(frame).resize((self.video_width, self.video_height))
                imgtk = ImageTk.PhotoImage(img)
                self.image_label.config(image=imgtk, width=self.video_width, height=self.video_height)
                self.image_label.image = imgtk
                self.root.after(frame_delay, show_frame)
        show_frame()

    def speak_and_animate_worker(self, text_queue):
        """Processes a queue of text chunks and speaks them out loud."""
        while True:
            try:
                chunk = text_queue.get()
                if chunk is None:
                    break
                self.tts_engine.say(chunk)
                self.tts_engine.runAndWait()
                text_queue.task_done()
            except queue.Empty:
                continue
        self.is_speaking = False

    def speak_with_video(self, text):
        cleaned_text = clean_text_for_tts(text)
        if not cleaned_text.strip():
            return
        def speak_and_animate():
            self.root.after(0, self.play_video_loop)
            self.tts_engine.say(cleaned_text)
            self.tts_engine.runAndWait()
            self.is_speaking = False
        threading.Thread(target=speak_and_animate, daemon=True).start()

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
                "model": selected, "messages": self.messages, "temperature": 0.7,
                "max_tokens": -1, "stream": True
            }
            response = requests.post(LMSTUDIO_URL, json=payload, timeout=600, stream=True)
            response.raise_for_status()
            
            self.root.after(0, self.start_assistant_message)

            # --- Streaming TTS Setup ---
            text_queue = queue.Queue()
            self.is_speaking = True
            threading.Thread(target=self.speak_and_animate_worker, args=(text_queue,), daemon=True).start()
            self.root.after(0, self.play_video_loop)

            full_response_for_history = ""
            word_buffer = ""
            is_inside_think_tag = False
            
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
                                full_response_for_history += delta
                                
                                temp_chunk = delta
                                while temp_chunk:
                                    visible_part = ""
                                    if not is_inside_think_tag:
                                        think_start_pos = temp_chunk.find("<think>")
                                        if think_start_pos != -1:
                                            visible_part = temp_chunk[:think_start_pos]
                                            is_inside_think_tag = True
                                            temp_chunk = temp_chunk[think_start_pos + len("<think>"):]
                                        else:
                                            visible_part = temp_chunk
                                            temp_chunk = ""
                                    else:
                                        think_end_pos = temp_chunk.find("</think>")
                                        if think_end_pos != -1:
                                            is_inside_think_tag = False
                                            temp_chunk = temp_chunk[think_end_pos + len("</think>"):]
                                        else:
                                            temp_chunk = ""
                                    
                                    if visible_part:
                                        self.root.after(0, lambda d=visible_part: self.append_chat_delta(d))
                                        word_buffer += visible_part
                                        # Split by space to get words
                                        words = word_buffer.split(' ')
                                        if len(words) > 1:
                                            for word in words[:-1]:
                                                if word:
                                                    text_queue.put(clean_text_for_tts(word))
                                            word_buffer = words[-1]

                        except json.JSONDecodeError:
                            continue
            
            if word_buffer:
                text_queue.put(clean_text_for_tts(word_buffer))

            text_queue.put(None) # End signal for the speaker thread

            self.root.after(0, lambda: self.append_chat_delta("\n"))
            self.messages.append({"role": "assistant", "content": full_response_for_history})

        except Exception as e:
            self.is_speaking = False # Stop video on error
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
                    self._send_user_message(recognized_text)
                else:
                    messagebox.showinfo("Info", "Keine Sprache erkannt.")
            self.root.after(0, handle_ui_updates)
        threading.Thread(target=recognize_and_send, daemon=True).start()

if __name__ == "__main__":
    root = tk.Tk()
    app = ChatBotApp(root)
    root.mainloop()
