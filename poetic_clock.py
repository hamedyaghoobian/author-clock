import tkinter as tk
from tkinter import font as tkFont
from datetime import datetime
from zoneinfo import ZoneInfo
import inflect
from langchain_ollama import OllamaLLM

# Initialize Ollama connection
ollama = OllamaLLM(base_url='http://localhost:11434', model="gemma3:4b", temperature=0.1, num_predict=64)

def time_in_words(hour, minute):
    p = inflect.engine()
    if minute == 0:
        words = f"{p.number_to_words(hour)} o'clock"
    elif minute <= 30:
        words = f"{p.number_to_words(minute)} past {p.number_to_words(hour)}"
    else:
        words = f"{p.number_to_words(60 - minute)} to {p.number_to_words((hour + 1) % 24)}"
    return words.capitalize()

def witty_time_sentence(time_words, am_pm):
    prompt = f"Write a simple, direct sentence about what people typically do when it's {time_words} {am_pm}. Keep it under 30 words and start with 'At {time_words} {am_pm},'."
    response = ollama.invoke(input=prompt)
    return f"{response}"

def update_time():
    now = datetime.now(ZoneInfo("America/New_York"))
    current_time_words = time_in_words(now.hour, now.minute)
    am_pm = "AM" if now.hour < 12 else "PM"
    witty_sentence = witty_time_sentence(current_time_words, am_pm)
    
    time_text.config(state=tk.NORMAL)
    time_text.delete('1.0', tk.END)
    time_text.insert(tk.END, witty_sentence)
    
    # Find and highlight the time portion
    time_phrase = f"{current_time_words} {am_pm}"
    content = time_text.get('1.0', tk.END)
    start_idx = content.lower().find(time_phrase.lower())
    if start_idx != -1:
        start_pos = f"1.{start_idx}"
        end_pos = f"1.{start_idx + len(time_phrase)}"
        time_text.tag_add("time", start_pos, end_pos)
        update_time_tag_format()
    
    time_text.config(state=tk.DISABLED)
    root.after(60000 - (now.second * 1000 + now.microsecond // 1000), update_time)

def update_time_tag_format():
    time_text.tag_config("time", foreground="white", font=(text_font.cget("family"), text_font.cget("size"), "bold"))

def resize_text(event=None):
    new_size = max(12, min(root.winfo_width() // 15, root.winfo_height() // 15))
    text_font.configure(size=new_size)
    time_text.configure(wrap='word')  # Adjust wrap to word
    update_time_tag_format()  # Update time tag font size to match

root = tk.Tk()
root.title("Author Clock")

text_font = tkFont.Font(family='Input Serif', size=40, weight='bold')

time_text = tk.Text(root, font=text_font, height=10, width=50, state=tk.DISABLED, wrap='word', fg='blue')
time_text.pack(expand=True, padx=10, pady=10)

update_time()

root.bind('<Configure>', resize_text)

root.mainloop()
