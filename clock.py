import tkinter as tk
from datetime import datetime
import inflect 

def time_in_words(hour, minute):
    p = inflect.engine()
    words = ""
    if minute == 0:
        words = f"{p.number_to_words(hour)} o'clock"
    elif minute <= 30:
        words = f"{p.number_to_words(minute)} past {p.number_to_words(hour)}"
    else:
        words = f"{p.number_to_words(60 - minute)} to {p.number_to_words((hour + 1) % 24)}"
    return words.capitalize()

def update_time():
    now = datetime.now()
    current_time = time_in_words(now.hour, now.minute)
    time_text.set(current_time)
    root.after(60000 - (now.second * 1000 + now.microsecond // 1000), update_time)

root = tk.Tk()
root.title("Time in Words")

time_text = tk.StringVar()
label = tk.Label(root, textvariable=time_text, font=('Helvetica', 72, 'bold'), fg='blue')
label.pack(pady=100, padx=100) 

update_time()

root.mainloop()
