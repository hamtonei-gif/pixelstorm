import cv2
import mediapipe as mp
import math
import random
import time
import os
import sys
import csv
import traceback
from datetime import datetime

# ---------------- SETTINGS ----------------
GRID_SIZE = 3
WIN_DELAY = 5
PINCH_DEBOUNCE_FRAMES = 3
SMOOTHING = 0.5

employee_name = ""
employee_id = ""

# ---------------- PATH HELPER ----------------
def get_base_path():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
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

# ---------------- CAMERA HELPERS ----------------
def score_camera(index):
    for backend in [cv2.CAP_DSHOW, cv2.CAP_MSMF, None]:
        try:
            cap = cv2.VideoCapture(index, backend) if backend else cv2.VideoCapture(index)
            if not cap.isOpened():
                cap.release()
                continue
            ret, frame = cap.read()
            cap.release()
            if not ret or frame is None:
                continue
            h, w = frame.shape[:2]
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            brightness = gray.mean()
            if brightness < 20:
                return -1
            return w * h + int(brightness * 100)
        except Exception:
            pass
    return -1

def get_best_camera():
    scores = {}
    for index in range(7):
        s = score_camera(index)
        if s > 0:
            scores[index] = s
    if not scores:
        return 0
    externals = {i: s for i, s in scores.items() if i > 0}
    if externals:
        return max(externals, key=lambda i: (externals[i], i))
    return 0

def open_camera(index):
    for backend in [cv2.CAP_DSHOW, cv2.CAP_MSMF, None]:
        try:
            cap = cv2.VideoCapture(index, backend) if backend else cv2.VideoCapture(index)
            if cap.isOpened():
                ret, _ = cap.read()
                if ret:
                    return cap
            cap.release()
        except Exception:
            pass
    return None

# ---------------- DRAW TEXT HELPERS ----------------
def draw_centered_text(frame, text, y, scale, color, thickness=2):
    h, w = frame.shape[:2]
    font = cv2.FONT_HERSHEY_SIMPLEX
    size = cv2.getTextSize(text, font, scale, thickness)[0]
    x = (w - size[0]) // 2
    cv2.putText(frame, text, (x, y), font, scale, (0,0,0), thickness+3)
    cv2.putText(frame, text, (x, y), font, scale, color, thickness)

def draw_input_box(frame, label, value, y, active, w):
    font = cv2.FONT_HERSHEY_SIMPLEX
    box_w, box_h = 500, 50
    box_x = (w - box_w) // 2
    # Label
    cv2.putText(frame, label, (box_x, y - 10), font, 0.7, (200, 200, 200), 1)
    # Box background
    box_color = (255, 255, 255) if active else (180, 180, 180)
    cv2.rectangle(frame, (box_x, y), (box_x + box_w, y + box_h), box_color, -1)
    cv2.rectangle(frame, (box_x, y), (box_x + box_w, y + box_h), (0, 200, 150) if active else (100,100,100), 2)
    # Value text
    display = value + ("|" if active and int(time.time() * 2) % 2 == 0 else "")
    cv2.putText(frame, display, (box_x + 10, y + 35), font, 0.8, (0, 0, 0), 2)

def draw_button(frame, text, y, w):
    font = cv2.FONT_HERSHEY_SIMPLEX
    btn_w, btn_h = 300, 60
    btn_x = (w - btn_w) // 2
    cv2.rectangle(frame, (btn_x, y), (btn_x + btn_w, y + btn_h), (0, 170, 120), -1)
    cv2.rectangle(frame, (btn_x, y), (btn_x + btn_w, y + btn_h), (0, 255, 180), 2)
    size = cv2.getTextSize(text, font, 0.9, 2)[0]
    tx = btn_x + (btn_w - size[0]) // 2
    ty = y + (btn_h + size[1]) // 2
    cv2.putText(frame, text, (tx, ty), font, 0.9, (255, 255, 255), 2)
    return (btn_x, y, btn_x + btn_w, y + btn_h)

# ---------------- EMPLOYEE FORM (inside OpenCV) ----------------
def run_employee_form(cap, w, h):
    """
    Shows name/ID input form inside the OpenCV window.
    Returns (name, employee_id) or (None, None) if user closes.
    """
    name_val = ""
    id_val = ""
    active_field = 0  # 0 = name, 1 = id

    name_y = h // 2 - 120
    id_y = h // 2 + 20
    btn_y = h // 2 + 160

    while True:
        ret, frame = cap.read()
        if not ret:
            frame = None

        # Dark overlay background
        bg = frame.copy() if frame is not None else None
        overlay = bg if bg is not None else (cv2.UMat(h, w, cv2.CV_8UC3) if False else
                  __import__('numpy').zeros((h, w, 3), dtype='uint8'))

        # Semi-transparent dark panel
        panel = overlay.copy()
        cv2.rectangle(panel, (w//2 - 320, h//2 - 200), (w//2 + 320, h//2 + 240), (20, 20, 20), -1)
        cv2.addWeighted(panel, 0.85, overlay, 0.15, 0, overlay)

        draw_centered_text(overlay, "PixelStorm", h // 2 - 200, 1.4, (0, 220, 160), 3)
        draw_centered_text(overlay, "Assemble the Chaos", h // 2 - 160, 0.7, (160, 160, 160), 1)

        draw_input_box(overlay, "Your Name", name_val, name_y, active_field == 0, w)
        draw_input_box(overlay, "Employee ID", id_val, id_y, active_field == 1, w)
        btn_coords = draw_button(overlay, "START PUZZLE", btn_y, w)

        draw_centered_text(overlay, "Click a field then type. Press Tab to switch fields.", h - 30, 0.5, (150, 150, 150), 1)

        cv2.imshow("PixelStorm", overlay)

        key = cv2.waitKey(30) & 0xFF

        if key == 255:
            continue

        # Tab switches field
        if key == 9:
            active_field = 1 - active_field

        # Escape quits
        elif key == 27:
            return None, None

        # Backspace
        elif key == 8:
            if active_field == 0 and name_val:
                name_val = name_val[:-1]
            elif active_field == 1 and id_val:
                id_val = id_val[:-1]

        # Enter = submit if both fields filled
        elif key == 13:
            if name_val.strip() and id_val.strip():
                return name_val.strip(), id_val.strip()

        # Click detection via mouse (handled separately via setMouseCallback)
        # Printable characters
        elif 32 <= key <= 126:
            char = chr(key)
            if active_field == 0:
                name_val += char
            else:
                id_val += char

    return None, None

# Mouse click state for form
_mouse_click = None
def _mouse_callback(event, x, y, flags, param):
    global _mouse_click
    if event == cv2.EVENT_LBUTTONDOWN:
        _mouse_click = (x, y)

# ---------------- FULL FORM WITH MOUSE SUPPORT ----------------
def run_form_with_mouse(cap, w, h):
    global _mouse_click
    _mouse_click = None

    cv2.setMouseCallback("PixelStorm", _mouse_callback)

    name_val = ""
    id_val = ""
    active_field = 0

    name_y = h // 2 - 120
    id_y   = h // 2 + 20
    btn_y  = h // 2 + 160

    name_box  = ((w - 500) // 2, name_y, (w - 500) // 2 + 500, name_y + 50)
    id_box    = ((w - 500) // 2, id_y,   (w - 500) // 2 + 500, id_y + 50)
    btn_box   = ((w - 300) // 2, btn_y,  (w - 300) // 2 + 300, btn_y + 60)

    import numpy as np

    while True:
        ret, frame = cap.read()
        overlay = frame.copy() if ret and frame is not None else np.zeros((h, w, 3), dtype='uint8')

        # Dark panel
        panel = overlay.copy()
        cv2.rectangle(panel, (w//2 - 320, h//2 - 210), (w//2 + 320, h//2 + 250), (15, 15, 15), -1)
        cv2.addWeighted(panel, 0.82, overlay, 0.18, 0, overlay)

        draw_centered_text(overlay, "PixelStorm", h // 2 - 200, 1.4, (0, 220, 160), 3)
        draw_centered_text(overlay, "Assemble the Chaos", h // 2 - 162, 0.7, (160, 160, 160), 1)

        draw_input_box(overlay, "Your Name", name_val, name_y, active_field == 0, w)
        draw_input_box(overlay, "Employee ID", id_val, id_y, active_field == 1, w)
        draw_button(overlay, "START PUZZLE", btn_y, w)

        draw_centered_text(overlay, "Click field + type  |  Tab to switch  |  Enter to start", h - 30, 0.5, (140, 140, 140), 1)

        cv2.imshow("PixelStorm", overlay)

        # Handle mouse clicks
        if _mouse_click:
            mx, my = _mouse_click
            _mouse_click = None
            if name_box[0] < mx < name_box[2] and name_box[1] < my < name_box[3]:
                active_field = 0
            elif id_box[0] < mx < id_box[2] and id_box[1] < my < id_box[3]:
                active_field = 1
            elif btn_box[0] < mx < btn_box[2] and btn_box[1] < my < btn_box[3]:
                if name_val.strip() and id_val.strip():
                    cv2.setMouseCallback("PixelStorm", lambda *a: None)
                    return name_val.strip(), id_val.strip()

        key = cv2.waitKey(30) & 0xFF
        if key == 255:
            continue

        if key == 9:    # Tab
            active_field = 1 - active_field
        elif key == 27: # Esc
            cv2.setMouseCallback("PixelStorm", lambda *a: None)
            return None, None
        elif key == 13: # Enter
            if name_val.strip() and id_val.strip():
                cv2.setMouseCallback("PixelStorm", lambda *a: None)
                return name_val.strip(), id_val.strip()
        elif key == 8:  # Backspace
            if active_field == 0 and name_val:
                name_val = name_val[:-1]
            elif active_field == 1 and id_val:
                id_val = id_val[:-1]
        elif 32 <= key <= 126:
            if active_field == 0:
                name_val += chr(key)
            else:
                id_val += chr(key)

# ---------------- MAIN GAME ----------------
def run_game(cap, w, h, name, emp_id):
    try:
        # Dynamic sizing
        PIECE_SIZE = max(100, min(220, int(h * 0.20)))
        SNAP_DISTANCE = int(PIECE_SIZE * 0.4)
        PINCH_THRESHOLD = max(25, int(h * 0.06))

        max_grid = int(min(w, h) * 0.75)
        if GRID_SIZE * PIECE_SIZE > max_grid:
            PIECE_SIZE = max_grid // GRID_SIZE
            SNAP_DISTANCE = int(PIECE_SIZE * 0.4)

        grid_total = GRID_SIZE * PIECE_SIZE
        grid_start_x = (w - grid_total) // 2
        grid_start_y = (h - grid_total) // 2

        # Load image
        image_path = get_image_path()
        if not os.path.exists(image_path):
            show_error(f"puzzle.jpg not found in:\n{get_base_path()}")
            return

        full_image = cv2.imread(image_path)
        if full_image is None:
            show_error("puzzle.jpg could not be read.")
            return

        full_image = cv2.resize(full_image, (GRID_SIZE * PIECE_SIZE, GRID_SIZE * PIECE_SIZE))
        image_pieces = []
        for row in range(GRID_SIZE):
            for col in range(GRID_SIZE):
                x, y = col * PIECE_SIZE, row * PIECE_SIZE
                image_pieces.append(full_image[y:y+PIECE_SIZE, x:x+PIECE_SIZE])

        # MediaPipe
        from mediapipe.python.solutions import hands as mp_hands_module
        hands = mp_hands_module.Hands(
            static_image_mode=False,
            max_num_hands=1,
            min_detection_confidence=0.6,
            min_tracking_confidence=0.6
        )

        # Pieces
        pieces = []
        placed_count = 0
        game_complete = False
        completion_time = 0
        start_time = time.time()
        win_time_start = None

        dragging_piece = None
        was_pinching = False
        smooth_x = smooth_y = smooth_thumb_x = smooth_thumb_y = 0
        pinch_counter = release_counter = 0
        confirmed_pinching = False

        positions = [(random.randint(20, w-PIECE_SIZE-20), random.randint(20, h-PIECE_SIZE-20))
                     for _ in range(GRID_SIZE * GRID_SIZE)]
        random.shuffle(positions)

        for idx, (row, col) in enumerate([(r, c) for r in range(GRID_SIZE) for c in range(GRID_SIZE)]):
            pieces.append({
                "img": image_pieces[idx],
                "x": positions[idx][0], "y": positions[idx][1],
                "correct_x": grid_start_x + col * PIECE_SIZE,
                "correct_y": grid_start_y + row * PIECE_SIZE,
                "locked": False
            })

        # Detect available cameras — skip current one (already open)
        available_cameras = [current_camera_index]
        for i in range(7):
            if i == current_camera_index:
                continue
            test = open_camera(i)
            if test is not None:
                available_cameras.append(i)
                test.release()
        available_cameras.sort()
        print(f"Available cameras: {available_cameras}")
        hint_start = time.time()
        camera_switch_msg = ""
        camera_switch_time = 0

        while True:
            try:
                ret, frame = cap.read()
                if not ret:
                    break

                frame = cv2.flip(frame, 1)

                try:
                    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    results = hands.process(rgb)
                except Exception:
                    results = None

                cursor_x = cursor_y = None
                raw_pinching = False

                if results and results.multi_hand_landmarks:
                    for lm in results.multi_hand_landmarks:
                        it = lm.landmark[8]
                        tt = lm.landmark[4]
                        rx, ry = int(it.x * w), int(it.y * h)
                        rtx, rty = int(tt.x * w), int(tt.y * h)
                        smooth_x = int(SMOOTHING * smooth_x + (1-SMOOTHING) * rx)
                        smooth_y = int(SMOOTHING * smooth_y + (1-SMOOTHING) * ry)
                        smooth_thumb_x = int(SMOOTHING * smooth_thumb_x + (1-SMOOTHING) * rtx)
                        smooth_thumb_y = int(SMOOTHING * smooth_thumb_y + (1-SMOOTHING) * rty)
                        cursor_x, cursor_y = smooth_x, smooth_y
                        if math.hypot(smooth_thumb_x - cursor_x, smooth_thumb_y - cursor_y) < PINCH_THRESHOLD:
                            raw_pinching = True

                if raw_pinching:
                    pinch_counter += 1; release_counter = 0
                else:
                    release_counter += 1; pinch_counter = 0

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
                        dragging_piece["x"] = max(0, min(w-PIECE_SIZE, cursor_x - PIECE_SIZE//2))
                        dragging_piece["y"] = max(0, min(h-PIECE_SIZE, cursor_y - PIECE_SIZE//2))

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

                # Draw grid
                for i in range(GRID_SIZE + 1):
                    cv2.line(frame, (grid_start_x + i*PIECE_SIZE, grid_start_y),
                             (grid_start_x + i*PIECE_SIZE, grid_start_y + grid_total), (0,0,0), 2)
                    cv2.line(frame, (grid_start_x, grid_start_y + i*PIECE_SIZE),
                             (grid_start_x + grid_total, grid_start_y + i*PIECE_SIZE), (0,0,0), 2)

                # Draw pieces
                for piece in pieces:
                    x = max(0, min(w-PIECE_SIZE, piece["x"]))
                    y = max(0, min(h-PIECE_SIZE, piece["y"]))
                    try:
                        frame[y:y+PIECE_SIZE, x:x+PIECE_SIZE] = piece["img"]
                    except Exception:
                        pass

                # Cursor dot
                if cursor_x and cursor_y:
                    color = (0, 255, 0) if confirmed_pinching else (255, 255, 255)
                    cv2.circle(frame, (cursor_x, cursor_y), 12, color, -1)
                    cv2.circle(frame, (cursor_x, cursor_y), 14, (0,0,0), 2)

                # Timer
                if not game_complete:
                    elapsed = int(time.time() - start_time)
                    cv2.putText(frame, f"Time: {elapsed}s", (40, 60),
                                cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0,0,0), 3)

                # Camera hint
                if time.time() - hint_start < 5:
                    cv2.putText(frame, "Press C to switch camera | ESC to quit",
                                (40, h-30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (200,200,200), 2)

                # Win
                if placed_count == GRID_SIZE * GRID_SIZE and not game_complete:
                    game_complete = True
                    completion_time = time.time() - start_time
                    win_time_start = time.time()
                    save_results(name, emp_id, completion_time)

                if game_complete and win_time_start is not None:
                    font = cv2.FONT_HERSHEY_SIMPLEX
                    win_text = "PUZZLE COMPLETED!"
                    ws = cv2.getTextSize(win_text, font, 2, 5)[0]
                    cv2.putText(frame, win_text, ((w-ws[0])//2, h//2-40), font, 2, (0,255,0), 5)
                    tt = f"Completion Time: {completion_time:.2f} seconds"
                    ts = cv2.getTextSize(tt, font, 1.2, 3)[0]
                    cv2.putText(frame, tt, ((w-ts[0])//2, h//2+30), font, 1.2, (0,0,0), 4)
                    if time.time() - win_time_start > WIN_DELAY:
                        break

                # Show camera switch message for 3 seconds
                if camera_switch_msg and time.time() - camera_switch_time < 3:
                    cv2.putText(frame, camera_switch_msg,
                                (40, h - 70), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 200), 2)

                cv2.imshow("PixelStorm", frame)
                key = cv2.waitKey(16) & 0xFF

                if key == 27:
                    break
                if key in (ord('c'), ord('C')):
                    if len(available_cameras) > 1:
                        idx_in_list = available_cameras.index(current_camera_index) if current_camera_index in available_cameras else 0
                        next_cam = available_cameras[(idx_in_list + 1) % len(available_cameras)]
                        new_cap = open_camera(next_cam)
                        if new_cap:
                            cap.release()
                            cap = new_cap
                            current_camera_index = next_cam
                            camera_switch_msg = f"Switched to camera {next_cam}"
                            camera_switch_time = time.time()
                            print(camera_switch_msg)
                        else:
                            camera_switch_msg = f"Camera {next_cam} failed to open"
                            camera_switch_time = time.time()
                    else:
                        camera_switch_msg = f"Only 1 camera found (index {current_camera_index})"
                        camera_switch_time = time.time()

            except Exception as e:
                print(f"Frame error: {e}")
                continue

    except Exception as e:
        print(f"Game error:\n{traceback.format_exc()}")

    finally:
        try:
            hands.close()
        except:
            pass

def show_error(msg):
    import numpy as np
    frame = np.zeros((400, 700, 3), dtype='uint8')
    y = 80
    for line in msg.split('\n'):
        cv2.putText(frame, line, (40, y), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 100, 255), 2)
        y += 40
    cv2.putText(frame, "Press any key to exit", (40, y+40), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200,200,200), 1)
    cv2.imshow("PixelStorm", frame)
    cv2.waitKey(0)

# ---------------- ENTRY POINT ----------------
def main():
    # Open camera first
    camera_index = get_best_camera()
    cap = open_camera(camera_index)
    if cap is None:
        cap = open_camera(0)
    if cap is None:
        # Show error in a plain window
        import numpy as np
        cv2.namedWindow("PixelStorm", cv2.WINDOW_NORMAL)
        show_error("ERROR: No camera found.\nPlease connect a camera and restart.")
        cv2.destroyAllWindows()
        return

    ret, frame = cap.read()
    if not ret:
        cap.release()
        cv2.namedWindow("PixelStorm", cv2.WINDOW_NORMAL)
        show_error("ERROR: Camera found but cannot read frames.")
        cv2.destroyAllWindows()
        return

    h, w, _ = frame.shape

    # Open fullscreen window
    cv2.namedWindow("PixelStorm", cv2.WINDOW_NORMAL)
    cv2.setWindowProperty("PixelStorm", cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)

    # Show employee form inside OpenCV window
    name, emp_id = run_form_with_mouse(cap, w, h)

    if not name or not emp_id:
        cap.release()
        cv2.destroyAllWindows()
        return

    # Run game
    run_game(cap, w, h, name, emp_id)

    cap.release()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    main()
