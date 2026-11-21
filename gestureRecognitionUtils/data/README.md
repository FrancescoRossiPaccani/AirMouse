# Gesture Recognition Dataset

This folder contains the raw sensor recordings used to train and validate the Random Forest gesture classifier.

## Participants
Data was recorded across 10 participants (`P0` through `P9`), as mapped in `gestureRecognitionUtils/persons.txt`.

## CSV File Format
Each file `P<ID>_static_<TIMESTAMP>.csv` contains time-series data sampled at 20 Hz with the following columns:

- `pc_time`: Unix epoch timestamp on the receiving PC (seconds).
- `seq`: Monotonically increasing packet sequence counter.
- `t_watch`: Watch hardware timestamp (`SystemClock.elapsedRealtime()` in milliseconds).
- `c_ax, c_ay, c_az`: 3-axis accelerometer readings ($m/s^2$).
- `c_gx, c_gy, c_gz`: 3-axis gyroscope readings ($rad/s$).
- `c_mx, c_my, c_mz`: 3-axis magnetometer readings ($\mu T$).
- `trial`: Repetition index of the gesture trial (0 to 4).
- `label`: Gesture ground truth label:
  - `rest`: Resting position (no gesture).
  - `RLB`: Roll Left Back (left click).
  - `RRB`: Roll Right Back (right click).
  - `UDB`: Up Down Back (double click).
  - `MLB`: Move Left Back (drag & drop toggle).
  - `MRB`: Move Right Back (right lock toggle).
