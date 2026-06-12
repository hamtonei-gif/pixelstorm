import tkinter as tk
import os
import sys
import subprocess
import tempfile

employee_name = ""
employee_id = ""

# ---------------- IMAGE PATH (EXE SAFE) ----------------
def get_base_path():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    else:
        return os.path.dirname(os.path.abspath(__file__))

# ---------------- EMPLOYEE FORM ----------------
def open_employee_form():
    form = tk.Toplevel(root)
    form.title("Enter Details")
    form.geometry("400x250")
    form.configure(bg="#111111")

    tk.Label(form, text="Enter Your Name",
             font=("Helvetica", 14),
             fg="white",
             bg="#111111").pack(pady=10)

    name_entry = tk.Entry(form, font=("Helvetica", 12))
    name_entry.pack(pady=5)

    tk.Label(form, text="Enter Employee ID",
             font=("Helvetica", 14),
             fg="white",
             bg="#111111").pack(pady=10)

    id_entry = tk.Entry(form, font=("Helvetica", 12))
    id_entry.pack(pady=5)

    def submit():
        name = name_entry.get().strip()
        emp_id = id_entry.get().strip()

        if name and emp_id:
            form.destroy()
            root.withdraw()

            # Write name and ID to a temp file so the game process can read them
            info_path = os.path.join(get_base_path(), "_player_info.txt")
            with open(info_path, 'w') as f:
                f.write(f"{name}\n{emp_id}\n")

            # Launch the game as a completely separate process
            game_script = os.path.join(get_base_path(), "_game.exe" if getattr(sys, 'frozen', False) else "_game.py")
            if getattr(sys, 'frozen', False):
                proc = subprocess.Popen([game_script])
            else:
                proc = subprocess.Popen([sys.executable, game_script])

            # Wait for game to finish, then show landing page again
            root.after(500, lambda: wait_for_game(proc))

    tk.Button(form,
              text="Start Puzzle",
              font=("Helvetica", 12),
              bg="#00aa88",
              fg="white",
              command=submit).pack(pady=20)

def wait_for_game(proc):
    if proc.poll() is None:
        # Game still running, check again in 500ms
        root.after(500, lambda: wait_for_game(proc))
    else:
        # Game finished, show landing page
        root.deiconify()

# ---------------- LANDING SCREEN ----------------
root = tk.Tk()
root.title("PixelStorm: Assemble the Chaos")
root.geometry("600x400")
root.configure(bg="#111111")

title = tk.Label(root,
                 text="PixelStorm: Assemble the Chaos",
                 font=("Helvetica", 22, "bold"),
                 fg="white",
                 bg="#111111")
title.pack(pady=80)

start_button = tk.Button(root,
                         text="Start Game",
                         font=("Helvetica", 16),
                         bg="#00aa88",
                         fg="white",
                         width=15,
                         height=2,
                         command=open_employee_form)
start_button.pack()

root.mainloop()
