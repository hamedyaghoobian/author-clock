import tkinter as tk
from tkinter import font as tkFont
from datetime import datetime
from zoneinfo import ZoneInfo
import inflect
from langchain_community.llms import Ollama

# Initialize Ollama connection
ollama = Ollama(base_url='http://localhost:11434', model="phi3:medium", temperature=0.1, num_predict=64)

def time_in_words(hour, minute):
    p = inflect.engine()
    if minute == 0:
        words = f"{p.number_to_words(hour)} o'clock"
    elif minute <= 30:
        words = f"{p.number_to_words(minute)} past {p.number_to_words(hour)}"
    else:
        words = f"{p.number_to_words(60 - minute)} to {p.number_to_words((hour + 1) % 24)}"
    return words.capitalize()

def witty_time_sentence(time_words):
    prompt = f"Write simple yet meaningful sentence when it's {time_words} in less than 50 words."
    response = ollama.invoke(input=prompt)
    return f"{response}"

def update_time():
    now = datetime.now(ZoneInfo("America/New_York"))
    current_time_words = time_in_words(now.hour, now.minute)
    witty_sentence = witty_time_sentence(current_time_words)
    time_text.config(state=tk.NORMAL)
    time_text.delete('1.0', tk.END)
    time_text.insert(tk.END, witty_sentence)
    time_text.tag_add("time", '1.0', f"1.{len(current_time_words)}")
    time_text.tag_config("time", foreground="black")
    time_text.config(state=tk.DISABLED)
    root.after(60000 - (now.second * 1000 + now.microsecond // 1000), update_time)

def resize_text(event=None):
    new_size = max(12, min(root.winfo_width() // 15, root.winfo_height() // 15))
    text_font.configure(size=new_size)
    time_text.configure(wrap='word')  # Adjust wrap to word

root = tk.Tk()
root.title("Author Clock")

text_font = tkFont.Font(family='Input Serif', size=40, weight='bold')

time_text = tk.Text(root, font=text_font, height=10, width=50, state=tk.DISABLED, wrap='word', fg='blue')
time_text.pack(expand=True, padx=10, pady=10)

update_time()

root.bind('<Configure>', resize_text)

root.mainloop()
