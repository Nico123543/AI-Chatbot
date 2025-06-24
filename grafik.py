import tkinter as tk
from tkinter import scrolledtext
import requests
import threading
import json

LMSTUDIO_URL = "http://localhost:1234/v1/chat/completions"  # Standard-Port für LM Studio REST API
LMSTUDIO_MODEL = "bartowski/granite-3.0-1b-a400m-instruct"  # Passe den Modellnamen an (z.B. "llama-2-7b-chat")
LMSTUDIO_MODELS_URL = "http://localhost:1234/v1/models"

class ChatApp:
    def __init__(self, root):
        self.root = root
        self.root.title("LM Studio Chat")
        self.root.geometry("500x500")
        self.messages = []  # Verlauf für den Chat

        self.chat_area = scrolledtext.ScrolledText(root, wrap=tk.WORD, state='disabled')
        self.chat_area.pack(padx=10, pady=10, fill=tk.BOTH, expand=True)

        self.entry = tk.Entry(root)
        self.entry.pack(padx=10, pady=(0,10), fill=tk.X)
        self.entry.bind('<Return>', self.send_message)

        self.send_button = tk.Button(root, text="Senden", command=self.send_message)
        self.send_button.pack(padx=10, pady=(0,10))

        self.check_server_connection()

    def check_server_connection(self):
        try:
            response = requests.get(LMSTUDIO_MODELS_URL, timeout=3)
            response.raise_for_status()
            self.root.title("LM Studio Chat (Server verbunden)")
        except Exception as e:
            self.append_chat("System", f"Server nicht erreichbar: {e}")

    def send_message(self, event=None):
        user_message = self.entry.get().strip()
        if not user_message:
            return
        self.append_chat("Du", user_message)
        self.messages.append({"role": "user", "content": user_message})
        self.entry.delete(0, tk.END)
        threading.Thread(target=self.get_lmstudio_response, daemon=True).start()

    def append_chat(self, sender, message):
        self.chat_area.config(state='normal')
        self.chat_area.insert(tk.END, f"{sender}: {message}\n")
        self.chat_area.config(state='disabled')
        self.chat_area.see(tk.END)

    def get_lmstudio_response(self):
        try:
            payload = {
                "model": LMSTUDIO_MODEL,
                "messages": self.messages,
                "temperature": 0.7,
                "max_tokens": -1,  # Keine Begrenzung, Server entscheidet
                "stream": True  # Streaming wieder aktiviert
            }

            response = requests.post(LMSTUDIO_URL, json=payload, stream=True, timeout=600)
            response.raise_for_status()

            # "LM Studio: " vor der ersten Antwort im UI anzeigen
            self.root.after(0, self.start_assistant_message)
            
            answer = ""
            for line in response.iter_lines():
                if line:
                    decoded_line = line.decode('utf-8')
                    if decoded_line.startswith('data: '):
                        content = decoded_line[6:]
                        if content.strip() == '[DONE]':
                            break
                        try:
                            data = json.loads(content)
                            # Sicherstellen, dass die Datenstruktur vorhanden ist
                            delta = data.get('choices', [{}])[0].get('delta', {}).get('content', '')
                            if delta:
                                answer += delta
                                # Nur das Text-Delta an die UI senden
                                self.root.after(0, lambda d=delta: self.append_chat_delta(d))
                        except json.JSONDecodeError:
                            continue  # Ungültige JSON-Zeilen überspringen

            # Zeilenumbruch am Ende der vollständigen Antwort hinzufügen
            self.root.after(0, lambda: self.append_chat_delta("\\n"))
            self.messages.append({"role": "assistant", "content": answer})

        except Exception as e:
            answer = f"[Fehler beim Streaming: {e}]"
            print(answer)
            self.root.after(0, lambda: self.append_chat("LM Studio", answer))

    def start_assistant_message(self):
        """Fügt den 'Sender'-Teil für die Antwort des Assistenten hinzu."""
        self.chat_area.config(state='normal')
        self.chat_area.insert(tk.END, "LM Studio: ")
        self.chat_area.config(state='disabled')
        self.chat_area.see(tk.END)

    def append_chat_delta(self, delta):
        """Fügt nur den Text (Token) zur Chat-Area hinzu, ohne Sender-Präfix."""
        self.chat_area.config(state='normal')
        self.chat_area.insert(tk.END, delta)
        self.chat_area.config(state='disabled')
        self.chat_area.see(tk.END)

if __name__ == "__main__":
    root = tk.Tk()
    app = ChatApp(root)
    root.mainloop() 