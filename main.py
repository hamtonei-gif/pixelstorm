import tkinter as tk
from tkinter import messagebox
import cv2
import mediapipe as mp
import math
import random
import time
import os
import sys
import csv
import threading
import traceback
from datetime import datetime

# ---------------- SETTINGS ----------------
GRID_SIZE = 3
PIECE_SIZE = 150
SNAP_DISTANCE = 60
PINCH_THRESHOLD = 45
SMOOTHING = 0.5
WIN_DELAY = 5
PINCH_DEBOUNCE_FRAMES = 3

employee_name = ""
employee_id = ""

# ---------------- IMAGE PATH (EXE SAFE) ----------------
def get_base_path():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    else:
        return os.path.dirname(os.path.abspath(__file__))

def get_image_path():
    return os.path.join(get_base_path(), "puzzle.jpg")

# ---------------- SAVE RESULTS ----------------
def save_results(name, emp_id, completion_time):
    try:
        file_path = os.path.join(get_base_path(), "results.csv")
        file_exists = os.path.isfile(file_path)
        with open(file_path, mode='a', newline='') as file:
            writer = csv.writer(file)
            if not file_exists:
                writer.writerow(["Name", "Employee ID", "Completion Time", "Date"])
            today = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            writer.writerow([name, emp_id, round(completion_time, 2), today])
    except Exception as e:
        print(f"Could not save results: {e}")

# ---------------- AUTO CAMERA DETECTION ----------------
def get_best_camera():
    available = []
    for index in range(5):
        try:
            cap = cv2.VideoCapture(index, cv2.CAP_DSHOW)
            if cap.isOpened():
                ret, _ = cap.read()
                if ret:
                    available.append(index)
            cap.release()
        except Exception:
            pass
    if not available:
        return 0
    if len(available) > 1:
        return available[-1]
    return available[0]

# ---------------- GAME FUNCTION ----------------
def run_game():
    try:
        # --- Camera ---
        camera_index = get_best_camera()
        cap = None
        for idx in [camera_index, 0]:
            for backend in [cv2.CAP_DSHOW, cv2.CAP_MSMF, None]:
                try:
                    if backend is None:
                        cap = cv2.VideoCapture(idx)
                    else:
                        cap = cv2.VideoCapture(idx, backend)
                    if cap.isOpened():
                        ret, _ = cap.read()
                        if ret:
                            break
                    cap.release()
                    cap = None
                except:
                    cap = None
            if cap is not None:
                break

        if cap is None or not cap.isOpened():
            root.after(0, lambda: messagebox.showerror("Camera Error", "Could not open any camera.\nPlease check your camera is connected and not in use by another app."))
            root.after(0, root.deiconify)
            return

        ret, frame = cap.read()
        if not ret:
            cap.release()
            root.after(0, lambda: messagebox.showerror("Camera Error", "Camera opened but could not read a frame."))
            root.after(0, root.deiconify)
            return

        h, w, _ = frame.shape

        # --- Puzzle image ---
        image_path = get_image_path()
        if not os.path.exists(image_path):
            cap.release()
            root.after(0, lambda: messagebox.showerror("File Error", f"puzzle.jpg not found!\nLooking in: {get_base_path()}\n\nMake sure puzzle.jpg is in the same folder as the .exe"))
            root.after(0, root.deiconify)
            return

        full_image = cv2.imread(image_path)
        if full_image is None:
            cap.release()
            root.after(0, lambda: messagebox.showerror("File Error", "puzzle.jpg found but could not be read.\nMake sure it is a valid JPG image."))
            root.after(0, root.deiconify)
            return

        # --- MediaPipe ---
        mp_hands = mp.solutions.hands
        hands = mp_hands.Hands(
            static_image_mode=False,
            max_num_hands=1,
            min_detection_confidence=0.7,
            min_tracking_confidence=0.7
        )

        # --- Setup pieces ---
        grid_start_x = (w - GRID_SIZE * PIECE_SIZE) // 2
        grid_start_y = (h - GRID_SIZE * PIECE_SIZE) // 2

        full_image = cv2.resize(full_image, (GRID_SIZE * PIECE_SIZE, GRID_SIZE * PIECE_SIZE))
        image_pieces = []
        for row in range(GRID_SIZE):
            for col in range(GRID_SIZE):
                x = col * PIECE_SIZE
                y = row * PIECE_SIZE
                image_pieces.append(full_image[y:y+PIECE_SIZE, x:x+PIECE_SIZE])

        pieces = []
        placed_count = 0
        game_complete = False
        completion_time = 0
        start_time = time.time()
        win_time_start = None

        dragging_piece = None
        was_pinching = False
        smooth_x, smooth_y = 0, 0
        smooth_thumb_x, smooth_thumb_y = 0, 0
        pinch_counter = 0
        release_counter = 0
        confirmed_pinching = False

        random_positions = []
        for _ in range(GRID_SIZE * GRID_SIZE):
            rx = random.randint(20, w - PIECE_SIZE - 20)
            ry = random.randint(20, h - PIECE_SIZE - 20)
            random_positions.append((rx, ry))
        random.shuffle(random_positions)

        index = 0
        for row in range(GRID_SIZE):
            for col in range(GRID_SIZE):
                correct_x = grid_start_x + col * PIECE_SIZE
                correct_y = grid_start_y + row * PIECE_SIZE
                start_x, start_y = random_positions[index]
                pieces.append({
                    "img": image_pieces[index],
                    "x": start_x, "y": start_y,
                    "correct_x": correct_x, "correct_y": correct_y,
                    "locked": False
                })
                index += 1

        cv2.namedWindow("PixelStorm", cv2.WINDOW_NORMAL)
        cv2.setWindowProperty("PixelStorm", cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)

        # --- Game loop ---
        while True:
            try:
                ret, frame = cap.read()
                if not ret:
                    break

                frame = cv2.flip(frame, 1)

                try:
                    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    results = hands.process(rgb)
                except Exception as e:
                    results = None

                cursor_x, cursor_y = None, None
                raw_pinching = False

                if results and results.multi_hand_landmarks:
                    for hand_landmarks in results.multi_hand_landmarks:
                        index_tip = hand_landmarks.landmark[8]
                        thumb_tip = hand_landmarks.landmark[4]

                        raw_x = int(index_tip.x * w)
                        raw_y = int(index_tip.y * h)
                        raw_thumb_x = int(thumb_tip.x * w)
                        raw_thumb_y = int(thumb_tip.y * h)

                        smooth_x = int(SMOOTHING * smooth_x + (1 - SMOOTHING) * raw_x)
                        smooth_y = int(SMOOTHING * smooth_y + (1 - SMOOTHING) * raw_y)
                        smooth_thumb_x = int(SMOOTHING * smooth_thumb_x + (1 - SMOOTHING) * raw_thumb_x)
                        smooth_thumb_y = int(SMOOTHING * smooth_thumb_y + (1 - SMOOTHING) * raw_thumb_y)

                        cursor_x, cursor_y = smooth_x, smooth_y

                        if math.hypot(smooth_thumb_x - cursor_x, smooth_thumb_y - cursor_y) < PINCH_THRESHOLD:
                            raw_pinching = True

                if raw_pinching:
                    pinch_counter += 1
                    release_counter = 0
                else:
                    release_counter += 1
                    pinch_counter = 0

                if pinch_counter >= PINCH_DEBOUNCE_FRAMES:
                    confirmed_pinching = True
                elif release_counter >= PINCH_DEBOUNCE_FRAMES:
                    confirmed_pinching = False

                if not game_complete and cursor_x and cursor_y:
                    if confirmed_pinching and not was_pinching:
                        for piece in reversed(pieces):
                            if not piece["locked"]:
                                if (piece["x"] < cursor_x < piece["x"] + PIECE_SIZE and
                                        piece["y"] < cursor_y < piece["y"] + PIECE_SIZE):
                                    dragging_piece = piece
                                    break

                    if dragging_piece and confirmed_pinching:
                        new_x = max(0, min(w - PIECE_SIZE, cursor_x - PIECE_SIZE // 2))
                        new_y = max(0, min(h - PIECE_SIZE, cursor_y - PIECE_SIZE // 2))
                        dragging_piece["x"] = new_x
                        dragging_piece["y"] = new_y

                    if dragging_piece and not confirmed_pinching and was_pinching:
                        dx = dragging_piece["x"] - dragging_piece["correct_x"]
                        dy = dragging_piece["y"] - dragging_piece["correct_y"]
                        if math.hypot(dx, dy) < SNAP_DISTANCE:
                            dragging_piece["x"] = dragging_piece["correct_x"]
                            dragging_piece["y"] = dragging_piece["correct_y"]
                            dragging_piece["locked"] = True
                            placed_count += 1
                        dragging_piece = None

                was_pinching = confirmed_pinching

                for i in range(GRID_SIZE + 1):
                    cv2.line(frame,
                             (grid_start_x + i * PIECE_SIZE, grid_start_y),
                             (grid_start_x + i * PIECE_SIZE, grid_start_y + GRID_SIZE * PIECE_SIZE),
                             (0, 0, 0), 2)
                    cv2.line(frame,
                             (grid_start_x, grid_start_y + i * PIECE_SIZE),
                             (grid_start_x + GRID_SIZE * PIECE_SIZE, grid_start_y + i * PIECE_SIZE),
                             (0, 0, 0), 2)

                for piece in pieces:
                    x = max(0, min(w - PIECE_SIZE, piece["x"]))
                    y = max(0, min(h - PIECE_SIZE, piece["y"]))
                    try:
                        frame[y:y+PIECE_SIZE, x:x+PIECE_SIZE] = piece["img"]
                    except Exception:
                        pass

                if not game_complete:
                    elapsed = int(time.time() - start_time)
                    cv2.putText(frame, f"Time: {elapsed}s", (40, 60),
                                cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 0, 0), 3)

                if placed_count == GRID_SIZE * GRID_SIZE and not game_complete:
                    game_complete = True
                    completion_time = time.time() - start_time
                    win_time_start = time.time()
                    save_results(employee_name, employee_id, completion_time)

                if game_complete and win_time_start is not None:
                    font = cv2.FONT_HERSHEY_SIMPLEX
                    win_text = "PUZZLE COMPLETED!"
                    win_size = cv2.getTextSize(win_text, font, 2, 5)[0]
                    win_x = (w - win_size[0]) // 2
                    win_y = h // 2 - 40
                    cv2.putText(frame, win_text, (win_x, win_y), font, 2, (0, 255, 0), 5)
                    time_text = f"Completion Time: {completion_time:.2f} seconds"
                    time_size = cv2.getTextSize(time_text, font, 1.2, 3)[0]
                    time_x = (w - time_size[0]) // 2
                    cv2.putText(frame, time_text, (time_x, win_y + 70), font, 1.2, (0, 0, 0), 4)
                    if time.time() - win_time_start > WIN_DELAY:
                        break

                cv2.imshow("PixelStorm", frame)
                if cv2.waitKey(1) & 0xFF == 27:
                    break

            except Exception as e:
                print(f"Frame error: {e}")
                continue

    except Exception as e:
        error_msg = traceback.format_exc()
        print(f"GAME ERROR:\n{error_msg}")
        root.after(0, lambda msg=error_msg: messagebox.showerror(
            "Game Error",
            f"Something went wrong:\n\n{msg[:800]}"
        ))

    finally:
        try:
            cap.release()
        except:
            pass
        try:
            cv2.destroyAllWindows()
        except:
            pass
        root.after(0, root.deiconify)


def start_game():
    root.after(0, root.withdraw)
    t = threading.Thread(target=run_game, daemon=True)
    t.start()


# ---------------- EMPLOYEE FORM ----------------
def open_employee_form():
    form = tk.Toplevel(root)
    form.title("Enter Details")
    form.geometry("400x250")
    form.configure(bg="#111111")

    tk.Label(form, text="Enter Your Name",
             font=("Helvetica", 14), fg="white", bg="#111111").pack(pady=10)
    name_entry = tk.Entry(form, font=("Helvetica", 12))
    name_entry.pack(pady=5)

    tk.Label(form, text="Enter Employee ID",
             font=("Helvetica", 14), fg="white", bg="#111111").pack(pady=10)
    id_entry = tk.Entry(form, font=("Helvetica", 12))
    id_entry.pack(pady=5)

    def submit():
        global employee_name, employee_id
        employee_name = name_entry.get().strip()
        employee_id = id_entry.get().strip()
        if employee_name and employee_id:
            form.destroy()
            start_game()

    tk.Button(form, text="Start Puzzle", font=("Helvetica", 12),
              bg="#00aa88", fg="white", command=submit).pack(pady=20)


# ---------------- LANDING SCREEN ----------------
root = tk.Tk()
root.title("PixelStorm: Assemble the Chaos")
root.geometry("600x400")
root.configure(bg="#111111")

tk.Label(root, text="PixelStorm: Assemble the Chaos",
         font=("Helvetica", 22, "bold"), fg="white", bg="#111111").pack(pady=80)

tk.Button(root, text="Start Game", font=("Helvetica", 16),
          bg="#00aa88", fg="white", width=15, height=2,
          command=open_employee_form).pack()

root.mainloop()
