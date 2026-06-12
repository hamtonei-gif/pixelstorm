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

# ---------------- PATH HELPER ----------------
def get_base_path():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

def get_image_path():
    return os.path.join(get_base_path(), "puzzle.jpg")

# ---------------- READ PLAYER INFO ----------------
def get_player_info():
    info_path = os.path.join(get_base_path(), "_player_info.txt")
    try:
        with open(info_path, 'r') as f:
            lines = f.read().splitlines()
            return lines[0], lines[1]
    except Exception:
        return "Player", "000"

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

def get_best_camera():
    """
    Scans indices 0-6.
    Scores by resolution + brightness to avoid bad lenses.
    Prefers external (higher index) over built-in.
    """
    scores = {}
    for index in range(7):
        try:
            cap = open_camera(index)
            if cap is None:
                continue
            ret, frame = cap.read()
            cap.release()
            if not ret or frame is None:
                continue
            h, w = frame.shape[:2]
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            brightness = gray.mean()
            if brightness < 20:
                continue
            scores[index] = w * h + int(brightness * 100)
        except Exception:
            pass

    if not scores:
        return 0

    externals = {i: s for i, s in scores.items() if i > 0}
    if externals:
        return max(externals, key=lambda i: (externals[i], i))
    return 0

# ---------------- MAIN GAME ----------------
def run():
    employee_name, employee_id = get_player_info()

    # Open best camera
    camera_index = get_best_camera()
    cap = open_camera(camera_index)
    if cap is None:
        cap = open_camera(0)
    if cap is None:
        print("ERROR: No camera found.")
        return

    ret, frame = cap.read()
    if not ret:
        cap.release()
        print("ERROR: Cannot read from camera.")
        return

    h, w, _ = frame.shape

    # Dynamic sizing — scales to any resolution
    PIECE_SIZE = max(100, min(220, int(h * 0.20)))
    SNAP_DISTANCE = int(PIECE_SIZE * 0.4)
    PINCH_THRESHOLD = max(25, int(h * 0.06))

    # Shrink if grid overflows frame
    max_grid = int(min(w, h) * 0.75)
    if GRID_SIZE * PIECE_SIZE > max_grid:
        PIECE_SIZE = max_grid // GRID_SIZE
        SNAP_DISTANCE = int(PIECE_SIZE * 0.4)

    grid_total = GRID_SIZE * PIECE_SIZE
    grid_start_x = (w - grid_total) // 2
    grid_start_y = (h - grid_total) // 2

    # Load puzzle image
    image_path = get_image_path()
    if not os.path.exists(image_path):
        print(f"ERROR: puzzle.jpg not found in {get_base_path()}")
        cap.release()
        return

    full_image = cv2.imread(image_path)
    if full_image is None:
        print("ERROR: Could not read puzzle.jpg")
        cap.release()
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

    # Setup pieces
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

    # Available cameras for switching
    available_cameras = [camera_index]
    for i in range(7):
        if i == camera_index:
            continue
        test = open_camera(i)
        if test is not None:
            available_cameras.append(i)
            test.release()
    available_cameras.sort()
    current_camera_index = camera_index

    cv2.namedWindow("PixelStorm", cv2.WINDOW_NORMAL)
    cv2.setWindowProperty("PixelStorm", cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)

    hint_start = time.time()
    camera_msg = f"Camera {current_camera_index} active | Press C to switch"
    camera_msg_time = time.time()

    # Game loop
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

            # Camera message (first 5 seconds + after switching)
            if time.time() - camera_msg_time < 5:
                cv2.putText(frame, camera_msg,
                            (40, h-30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0,220,160), 2)

            # Win condition
            if placed_count == GRID_SIZE * GRID_SIZE and not game_complete:
                game_complete = True
                completion_time = time.time() - start_time
                win_time_start = time.time()
                save_results(employee_name, employee_id, completion_time)

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
                        camera_msg = f"Switched to camera {next_cam} | Press C to switch"
                        camera_msg_time = time.time()
                    else:
                        camera_msg = f"Camera {next_cam} failed to open"
                        camera_msg_time = time.time()
                else:
                    camera_msg = f"Only 1 camera detected (index {current_camera_index})"
                    camera_msg_time = time.time()

        except Exception as e:
            print(f"Frame error: {e}")
            continue

    try:
        hands.close()
    except:
        pass
    cap.release()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    run()
