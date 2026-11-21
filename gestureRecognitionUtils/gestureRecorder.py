# This code is used to obtain the data used in the training phase of the gesture classification model.
#
# Overview:
#   The smartwatch streams its denoised sensor data (accelerometer, gyroscope, magnetometer at 20 Hz) over UDP to this script. 
#   N.B. Only the denoised signal ("c_*" columns) is recorded.
#
#   The script guides the user through a recording protocol: for each of the five gestures the user repeats the gesture N times after a "GO" cue, in batches of --block repetitions, with a rest after each batch to avoid arm fatigue.
#
#   At the end of every batch the user decides whether to SAVE it (and continue) or DISCARD it
#   (and redo only that batch). Data of the current batch is kept in memory and is written to the
#   CSV only when the batch is saved, so a mistake never forces a full restart.
#
#   Every saved sample is written to a CSV file together with:
#     - the PC arrival time, the packet sequence number and the watch timestamp;
#     - the trial number (consecutive, discarded batches do not leave gaps);
#     - a label: the gesture name during the cue window, "rest" otherwise.
#
#   The exact peak/valley of each gesture is located offline, so the labels only need to be accurate to within the cue window.
#
# Usage:
#   python3 gestureRecorder.py --subject P1                        # static gestures
#   python3 gestureRecorder.py --subject P1 --moving               # gestures while slowly moving the hand
#   python3 gestureRecorder.py --subject P1 --reps 10 --block 5    # 10 reps per gesture, batches of 5
#
# Output: data/<subject>_<mode>_<timestamp>.csv

import argparse
import csv
import json
import os
import random
import socket
import threading
import time

GESTURES = {
    "MLB": "MOVE-LEFT-BACK    (move left and return)",
    "MRB": "MOVE-RIGHT-BACK   (move right and return)",
    "RLB": "ROTATE-LEFT-BACK  (rotate left and return)",
    "RRB": "ROTATE-RIGHT-BACK (rotate right and return)",
    "UDB": "UP-DOWN-BACK      (move up and return)",
}

ap = argparse.ArgumentParser()
ap.add_argument("--subject", required=True, help="e.g. P1")
ap.add_argument("--reps", type=int, default=10, help="repetitions per gesture")
ap.add_argument("--block", type=int, default=10,
                help="batch size: after every N repetitions you choose to save or discard")
ap.add_argument("--moving", action="store_true",
                help="user slowly moves the hand while performing the gesture")
ap.add_argument("--port", type=int, default=5005)
ap.add_argument("--window", type=float, default=2.0, help="gesture window length (s)")
args = ap.parse_args()

os.makedirs("data", exist_ok=True)
mode = "moving" if args.moving else "static"
fname = f"data/{args.subject}_{mode}_{time.strftime('%Y%m%d_%H%M%S')}.csv"

CH = ["ax", "ay", "az", "gx", "gy", "gz", "mx", "my", "mz"]
header = (["pc_time", "seq", "t_watch"]
          + [f"c_{n}" for n in CH]
          + ["trial", "label"])

state = {"label": "rest", "trial": 0}
pending = []          # rows of the current, not yet confirmed, batch
lock = threading.Lock()
stop = threading.Event()
got_packet = threading.Event()
f = open(fname, "w", newline="")
writer = csv.writer(f)
writer.writerow(header)
f.flush()


def receiver():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", args.port))
    sock.settimeout(0.5)
    while not stop.is_set():
        try:
            data, _ = sock.recvfrom(2048)
        except socket.timeout:
            continue
        try:
            p = json.loads(data.decode())
        except json.JSONDecodeError:
            continue
        clean = p["acc"] + p["gyro"] + p["mag"]  # denoised signal only
        with lock:
            lab, tr = state["label"], state["trial"]
            pending.append([f"{time.time():.4f}", p["seq"], p["t"]]
                           + clean + [tr, lab])
        got_packet.set()


def save_pending():
    """Write the current batch to the CSV."""
    with lock:
        n = len(pending)
        writer.writerows(pending)
        f.flush()
        pending.clear()
    return n


def discard_pending(trial_at_start):
    """Drop the current batch and restore the trial counter."""
    with lock:
        n = len(pending)
        pending.clear()
        state["trial"] = trial_at_start
        state["label"] = "rest"
    return n


def ask_decision():
    """Ask whether to keep the batch. Returns True = save, False = discard."""
    while True:
        ans = input("\nBatch finished. [S]ave and continue / [D]iscard and redo this batch? ").strip().lower()
        if ans in ("s", "save", ""):
            return True
        if ans in ("d", "discard"):
            return False
        print("Please type 's' to save or 'd' to discard.")


def beep():
    print("\a", end="", flush=True)


def run():
    threading.Thread(target=receiver, daemon=True).start()
    print(f"Saving to {fname}")
    print("Waiting for watch data (the first ~3 s fill the filter window)...")
    got_packet.wait()
    print("Stream OK.\n")

    # Warm-up: ~5 s per gesture, data is recorded but labeled 'rest'
    input("WARM-UP: you will try each gesture for a few seconds. Press Enter...")
    for g, desc in GESTURES.items():
        print(f"  Try: {desc}")
        time.sleep(5)
    print()
    save_pending()   # keep warm-up data, as in the original behaviour

    for g, desc in GESTURES.items():
        print("=" * 60)
        print(f"GESTURE: {desc}")
        if args.moving:
            print("Slowly move your hand (as if driving the cursor) "
                  "and perform the gesture after GO.")
        input("Press Enter to start the block...")

        reps_done = 0
        while reps_done < args.reps:
            n = min(args.block, args.reps - reps_done)
            with lock:
                trial_at_start = state["trial"]

            for i in range(1, n + 1):
                rep = reps_done + i
                with lock:
                    state["trial"] += 1
                    state["label"] = "rest"
                print(f"\n[{g}] {rep}/{args.reps}  get ready...")
                time.sleep(1.2 + random.uniform(0.0, 0.5))

                beep()
                print("   >>> GO! <<<")
                with lock:
                    state["label"] = g
                time.sleep(args.window)
                with lock:
                    state["label"] = "rest"

                if i < n:
                    time.sleep(random.uniform(0.3, 0.7))

            if ask_decision():
                saved = save_pending()
                reps_done += n
                print(f"Saved {n} repetitions ({saved} samples) "
                      f"[{reps_done}/{args.reps} of {g}].")
                if reps_done < args.reps:
                    input("Relax your arm. Press Enter to start the next batch...")
            else:
                dropped = discard_pending(trial_at_start)
                print(f"Discarded {n} repetitions ({dropped} samples).")
                input("Press Enter to redo this batch...")

    print("\nSession complete.")


try:
    run()
except KeyboardInterrupt:
    with lock:
        lost = len(pending)
    print(f"\nInterrupted. The unsaved batch ({lost} samples) was not written.")
finally:
    stop.set()
    time.sleep(0.6)
    f.close()
    print(f"File saved: {fname}")