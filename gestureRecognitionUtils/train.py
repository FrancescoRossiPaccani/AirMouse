import glob
import json
import os
import warnings

import matplotlib
matplotlib.use("Agg")           # no window: save to file only
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pywt
from sklearn.base import BaseEstimator, TransformerMixin
from sklearn.ensemble import RandomForestClassifier
from sklearn.feature_selection import mutual_info_classif
from sklearn.metrics import (accuracy_score, confusion_matrix, log_loss, precision_recall_fscore_support)
from sklearn.model_selection import train_test_split

OUT_DIR, IMG_DIR = "trainedTree", "img"

FS = 20.0
DT = 1.0 / FS
USE_MEASURED_DT = False   # True: dt from t_watch (ms); False: fixed dt = 50 ms
W = 32                    # feature window length (samples)
WAVELET, LEVEL = "db2", 3

# AHRS
BETA = 0.1
BETA_INIT, INIT_SAMPLES = 1.0, 40   # fast convergence during the first 2 s

# interval extraction 
PEAK_K = 4                # k of eq. 1-4
INTERVAL = 20             # 1 s around the peak
MARGIN = 20               # 'rest' context around the cue
SLOPE_K = 0.10            # slope threshold (normalized signal)    <- to be tuned
FIT_ERR = 0.05            # fitting error threshold (normalized)   <- to be tuned

# selection + classifier
K_PER_CLASS, MAX_CORR = 10, 0.9
EPOCHS, TREES_PER_EPOCH, PATIENCE = 30, 10, 10
MAX_DEPTH, MIN_LEAF = 10, 2


def madgwick_step(q, g, a, m, beta, dt):
    """One 9-axis Madgwick step. q=(w,x,y,z); g in rad/s."""
    w, x, y, z = q
    gx, gy, gz = g
    qdot = 0.5 * np.array([-x * gx - y * gy - z * gz,
                           w * gx + y * gz - z * gy,
                           w * gy - x * gz + z * gx,
                           w * gz + x * gy - y * gx])

    na, nm = np.linalg.norm(a), np.linalg.norm(m)
    if na > 1e-9:
        a = a / na
        # gravity
        fg = np.array([2 * (x * z - w * y) - a[0],
                       2 * (w * x + y * z) - a[1],
                       2 * (0.5 - x * x - y * y) - a[2]])
        Jg = np.array([[-2 * y, 2 * z, -2 * w, 2 * x],
                       [2 * x, 2 * w, 2 * z, 2 * y],
                       [0.0, -4 * x, -4 * y, 0.0]])
        grad = Jg.T @ fg
        # magnetic field 
        if nm > 1e-9:
            m = m / nm
            hx = (1 - 2 * (y * y + z * z)) * m[0] + 2 * (x * y - w * z) * m[1] + 2 * (x * z + w * y) * m[2]
            hy = 2 * (x * y + w * z) * m[0] + (1 - 2 * (x * x + z * z)) * m[1] + 2 * (y * z - w * x) * m[2]
            hz = 2 * (x * z - w * y) * m[0] + 2 * (y * z + w * x) * m[1] + (1 - 2 * (x * x + y * y)) * m[2]
            bx, bz = np.hypot(hx, hy), hz
            fm = np.array([2 * bx * (0.5 - y * y - z * z) + 2 * bz * (x * z - w * y) - m[0],
                           2 * bx * (x * y - w * z) + 2 * bz * (w * x + y * z) - m[1],
                           2 * bx * (w * y + x * z) + 2 * bz * (0.5 - x * x - y * y) - m[2]])
            Jm = np.array([[-2 * bz * y, 2 * bz * z, -4 * bx * y - 2 * bz * w, -4 * bx * z + 2 * bz * x],
                           [-2 * bx * z + 2 * bz * x, 2 * bx * y + 2 * bz * w, 2 * bx * x + 2 * bz * z, -2 * bx * w + 2 * bz * y],
                           [2 * bx * y, 2 * bx * z - 4 * bz * x, 2 * bx * w - 4 * bz * y, 2 * bx * x]])
            grad = grad + Jm.T @ fm
        ng = np.linalg.norm(grad)
        if ng > 1e-12:
            qdot = qdot - beta * grad / ng

    q = q + qdot * dt
    return q / np.linalg.norm(q)


def compute_angles(df):
    acc = df[["c_ax", "c_ay", "c_az"]].to_numpy(dtype=float)
    gyr = df[["c_gx", "c_gy", "c_gz"]].to_numpy(dtype=float)
    mag = df[["c_mx", "c_my", "c_mz"]].to_numpy(dtype=float)
    
    if USE_MEASURED_DT:
        dts = np.diff(df["t_watch"].to_numpy(dtype=float) / 1000.0, prepend=np.nan)
        dts = np.where(np.isfinite(dts) & (dts > 0) & (dts < 0.5), dts, DT)
    else:
        dts = np.full(len(df), DT)

    q = np.array([1.0, 0.0, 0.0, 0.0])
    out = np.zeros((len(df), 3))
    for i in range(len(df)):
        beta = BETA_INIT if i < INIT_SAMPLES else BETA
        q = madgwick_step(q, gyr[i], acc[i], mag[i], beta, dts[i])
        w, x, y, z = q
        out[i, 0] = np.arctan2(2 * (w * x + y * z), 1 - 2 * (x * x + y * y))   # roll
        out[i, 1] = np.arcsin(np.clip(2 * (w * y - z * x), -1.0, 1.0))         # pitch
        out[i, 2] = np.arctan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z))   # yaw
    return np.unwrap(out, axis=0)


# Gesture ectraction
def peak_valley_weights(x, k):
    n = len(x)
    wp, wv = np.zeros(n), np.zeros(n)
    for i in range(k, n - k):
        left, right = x[i - k:i], x[i + 1:i + 1 + k]
        wp[i] = 0.5 * ((x[i] - left).max() + (x[i] - right).max())
        wv[i] = 0.5 * ((x[i] - left).min() + (x[i] - right).min())
    return wp, wv


def piecewise_segments(y, thr): # linear fit (sez 5.1 paper)
    n = len(y)
    segs, start, end = [], 0, 1
    while end + 1 < n:
        nxt = end + 1
        t = np.arange(start, nxt + 1)
        p = np.polyfit(t, y[start:nxt + 1], 1)
        if np.abs(np.polyval(p, t) - y[start:nxt + 1]).max() <= thr:
            end = nxt
        else:
            segs.append((start, end))
            start, end = nxt, min(nxt + 1, n - 1)
    segs.append((start, end))
    return segs


def refine_interval(y, slope_k, thr):
    y = y - y.mean()
    y = y / (np.abs(y).max() + 1e-12)
    steep = [(a, b) for a, b in piecewise_segments(y, thr)
             if b > a and abs(np.polyfit(np.arange(a, b + 1), y[a:b + 1], 1)[0]) > slope_k]
    
    return (steep[0][0], steep[-1][1]) if steep else None


def extract_window(g, angles, lo, hi):
    N = len(g)
    a0, a1 = max(0, lo - MARGIN), min(N, hi + 1 + MARGIN)
    c0, c1 = lo - a0, hi - a0
    ang = angles[a0:a1]
    base = ang[:c0].mean(axis=0) if c0 >= 3 else np.median(ang, axis=0)
    ang = ang - base

    best = None
    for ax in range(3):
        wp, wv = peak_valley_weights(ang[:, ax], PEAK_K)
        score = np.maximum(wp, -wv)
        score[:max(c0, PEAK_K)] = 0
        score[c1 + 1:] = 0
        i = int(score.argmax())
        if best is None or score[i] > best[0]:
            best = (score[i], ax, i)
    _, ax, p = best

    h = INTERVAL // 2
    s, e = max(0, p - h), min(len(ang), p + h)
    r = refine_interval(ang[s:e, ax], SLOPE_K, FIT_ERR)
    center = p if r is None else s + (r[0] + r[1]) // 2

    start = a0 + center - W // 2
    if start < 0 or start + W > N:
        return None
    dbg = dict(ang=ang.copy(), c0=c0, c1=c1, peak=p, axis=ax, win0=start - a0,
               interval=None if r is None else (s + r[0], s + r[1]))
    return start, r is not None, dbg


# Feature extraction

TIME_N = ["mean", "var", "std", "max", "min", "range", "skew", "kurt", "rms",
          "energy", "mad", "median", "zcr", "npeaks", "nvalleys", "peak_order",
          "argmax", "argmin", "ar1", "ar2"]

FREQ_N = [f"fft{k}" for k in range(10)] + ["energy", "median", "var", "dom_bin"]

TF_N = [f"{b}_{s}" for b in ("cA3", "cD3", "cD2", "cD1")
        for s in ("rms", "var", "max", "min", "mean")]

NAMES = [f"{ax}_{dom}_{n}" for ax in ("gx", "gy", "gz")
         for dom, lst in (("time", TIME_N), ("freq", FREQ_N), ("tf", TF_N)) for n in lst]

NAMES += ["time_corr_xy", "time_corr_xz", "time_corr_yz"]

def axis_feats(x):
    # it work only to one gyroscope axi 
    n = len(x)
    mean = x.mean()
    d = x - mean
    var = (d ** 2).mean()
    std = np.sqrt(var)
    if std < 1e-9:
        skew = kurt = 0.0
    else:
        z = d / std
        skew, kurt = (z ** 3).mean(), (z ** 4).mean()
    energy = (x ** 2).sum()
    zcr = int(((d >= 0)[1:] != (d >= 0)[:-1]).sum())

    hi, lo = mean + 0.5 * std, mean - 0.5 * std
    peaks = [i for i in range(1, n - 1) if x[i] > x[i - 1] and x[i] > x[i + 1] and x[i] > hi]
    valleys = [i for i in range(1, n - 1) if x[i] < x[i - 1] and x[i] < x[i + 1] and x[i] < lo]
    order = 0.0
    if peaks and valleys:
        order = 1.0 if peaks[0] < valleys[0] else -1.0

    den = (d * d).sum()
    ar1 = (d[:-1] * d[1:]).sum() / den if den > 1e-18 else 0.0
    ar2 = (d[:-2] * d[2:]).sum() / den if den > 1e-18 else 0.0

    time_f = [mean, var, std, x.max(), x.min(), np.ptp(x), skew, kurt,
              np.sqrt(energy / n), energy, np.abs(d).mean(), np.median(x),
              zcr, len(peaks), len(valleys), order,
              x.argmax() / (n - 1), x.argmin() / (n - 1), ar1, ar2]

    mag = np.abs(np.fft.rfft(x))
    sp = mag[1:]
    freq_f = list(mag[:10]) + [(sp ** 2).sum(), np.median(sp), sp.var(), float(sp.argmax() + 1)]

    tf_f = []
    for c in pywt.wavedec(x, WAVELET, level=LEVEL, mode="symmetric"):
        tf_f += [np.sqrt((c ** 2).mean()), c.var(), c.max(), c.min(), c.mean()]

    return time_f + freq_f + tf_f


def feats(w):
    w = np.asarray(w, dtype=np.float64)
    f = []
    for a in range(3):
        f += axis_feats(w[:, a])
    for a, b in ((0, 1), (0, 2), (1, 2)):
        sa, sb = w[:, a].std(), w[:, b].std()
        f.append(0.0 if sa < 1e-9 or sb < 1e-9 else
                 ((w[:, a] - w[:, a].mean()) * (w[:, b] - w[:, b].mean())).mean() / (sa * sb))
    assert len(f) == len(NAMES)
    return np.array(f)



class CorrRelevanceSelector(BaseEstimator, TransformerMixin):
    # For every gesture (one-vs-rest): most informative, weakly correlated features 
    # Union of the subsets (eq. 5). Remember fit() must be called ONLY on the training set

    def __init__(self, k_per_class=10, max_corr=0.9):
        self.k_per_class = k_per_class
        self.max_corr = max_corr

    def fit(self, X, y):
        with np.errstate(all="ignore"), warnings.catch_warnings():
            warnings.simplefilter("ignore")
            corr = np.abs(np.nan_to_num(np.corrcoef(X, rowvar=False)))
        keep = set()
        for c in np.unique(y):
            rel = mutual_info_classif(X, (y == c).astype(int), random_state=0)
            chosen = []
            for j in np.argsort(-rel):
                if rel[j] <= 0:
                    break
                if all(corr[j, i] < self.max_corr for i in chosen):
                    chosen.append(int(j))
                if len(chosen) == self.k_per_class:
                    break
            keep |= set(chosen)
        self.support_ = np.array(sorted(keep or {0}))
        return self

    def transform(self, X):
        return np.asarray(X)[:, self.support_]


# Train classifier
def fit_rf_early_stopping(Xtr, ytr, Xva, yva, seed):
    rf = RandomForestClassifier(n_estimators=TREES_PER_EPOCH, warm_start=True,
                                max_depth=MAX_DEPTH, min_samples_leaf=MIN_LEAF,
                                random_state=seed)

    best_loss, best_ep, bad, ran = np.inf, 1, 0, 0

    for ep in range(1, EPOCHS + 1):
        rf.set_params(n_estimators=ep * TREES_PER_EPOCH)
        rf.fit(Xtr, ytr)
        ran = ep
        loss = log_loss(yva, rf.predict_proba(Xva), labels=rf.classes_)

        if loss < best_loss - 1e-4:
            best_loss, best_ep, bad = loss, ep, 0
        else:
            bad += 1
            if bad >= PATIENCE:
                break

    n_best = best_ep * TREES_PER_EPOCH
    rf.estimators_ = rf.estimators_[:n_best]
    rf.n_estimators = n_best
    return rf, best_ep, ran


def train_model(X, y, subj, idx, seed):
    subs = sorted(set(subj[idx]))

    #hp: at least 3 subject in the dataset, otherwise it doesnt work
    vs = subs[np.random.RandomState(seed).randint(len(subs))]
    va, fi = idx[subj[idx] == vs], idx[subj[idx] != vs]


    sel = CorrRelevanceSelector(K_PER_CLASS, MAX_CORR).fit(X[fi], y[fi])
    rf, best_ep, ran = fit_rf_early_stopping(
        sel.transform(X[fi]), y[fi], sel.transform(X[va]), y[va], seed)

    return sel, rf, dict(best_epoch=best_ep, epochs_run=ran)


# Utils
def load_dataset():
    X, y, subj, examples = [], [], [], {}       
    skipped = fallback = 0
    for path in sorted(glob.glob("data/*.csv")):
        s = os.path.basename(path).split("_")[0]
        df = pd.read_csv(path)
        g = df[["c_gx", "c_gy", "c_gz"]].to_numpy()
        angles = compute_angles(df)              # AHRS over the whole file
        for _, d in df[df.label != "rest"].groupby("trial"):
            r = extract_window(g, angles, d.index.min(), d.index.max())
            if r is None:
                skipped += 1
                continue
            start, refined, dbg = r
            fallback += (not refined)
            label = d.label.iloc[0]
            X.append(feats(g[start:start + W]))
            y.append(label)
            subj.append(s)
            examples.setdefault(label, dbg)
    print(f"Windows: {len(y)} (discarded {skipped}, not refined {fallback})")
    return (np.array(X), np.array(y), np.array(subj), examples,
            dict(skipped=skipped, not_refined=fallback))


def export(rf, sel, path):
    trees = []
    for e in rf.estimators_:
        t = e.tree_
        v = t.value[:, 0, :]
        v = v / v.sum(axis=1, keepdims=True)
        trees.append({"left": t.children_left.tolist(), "right": t.children_right.tolist(),
                      "feat": t.feature.tolist(), "thr": t.threshold.tolist(),
                      "proba": v.round(6).tolist()})
    json.dump({"classes": [str(c) for c in rf.classes_], "n_candidates": len(NAMES),
               "window": W, "wavelet": WAVELET, "level": LEVEL,
               "selected": sel.support_.tolist(),
               "selected_names": [NAMES[i] for i in sel.support_],
               "trees": trees}, open(path, "w"))


# PLOTS
METRIC_COLORS = {"precision": "#4C72B0", "recall": "#DD8452",
                 "f1": "#55A868", "accuracy": "#C44E52"}
DOMAIN_COLORS = {"time": "#4C72B0", "freq": "#DD8452", "tf": "#55A868", "corr": "#8172B3"}


def save_fig(fig, name):
    fig.tight_layout()
    fig.savefig(os.path.join(IMG_DIR, name), dpi=150)
    plt.close(fig)


def plot_metrics_per_subject(res):
    """Per-subject histograms (like Fig. 8a of the paper), plus the mean."""
    metrics = ["precision", "recall", "f1", "accuracy"]
    labels = list(res["test_subject"]) + ["mean"]
    x = np.arange(len(labels))
    bw = 0.2
    fig, ax = plt.subplots(figsize=(max(7, 0.9 * len(labels) + 3), 4.5))
    for k, m in enumerate(metrics):
        vals = list(res[m] * 100) + [res[m].mean() * 100]
        err = [0] * len(res) + [res[m].std(ddof=0) * 100]
        ax.bar(x + (k - 1.5) * bw, vals, bw, yerr=err, capsize=2,
               label="F1-score" if m == "f1" else m.capitalize(), color=METRIC_COLORS[m])
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.set_xlabel("Test subject (leave-one-subject-out)")
    ax.set_ylabel("Score (%)")
    ax.set_ylim(max(0, min(res[metrics].min().min() * 100 - 10, 70)), 102)
    ax.legend(ncol=4, loc="upper center", bbox_to_anchor=(0.5, 1.12), frameon=False)
    ax.grid(axis="y", alpha=0.3)
    save_fig(fig, "01_metrics_per_subject.png")


def plot_confusion(cm, classes):
    """Aggregated confusion matrix: row-wise %, counts in brackets."""
    norm = cm / np.clip(cm.sum(axis=1, keepdims=True), 1, None) * 100
    fig, ax = plt.subplots(figsize=(6, 5.2))
    ax.imshow(norm, vmin=0, vmax=100, cmap="Blues")
    for i in range(len(classes)):
        for j in range(len(classes)):
            ax.text(j, i, f"{norm[i, j]:.1f}\n({cm[i, j]})", ha="center", va="center",
                    fontsize=9, color="white" if norm[i, j] > 55 else "black")
    ax.set_xticks(range(len(classes)))
    ax.set_yticks(range(len(classes)))
    ax.set_xticklabels(classes)
    ax.set_yticklabels(classes)
    ax.set_xlabel("Predicted label")
    ax.set_ylabel("True label")
    ax.set_title("Aggregated confusion matrix")
    save_fig(fig, "02_confusion_aggregated.png")


def plot_confusion_per_subject(cms, subjects, classes):
    """One confusion matrix (row-wise %) for every test subject."""
    n = len(subjects)
    cols = min(3, n)
    rows = int(np.ceil(n / cols))
    fig, axes = plt.subplots(rows, cols, figsize=(3.8 * cols, 3.6 * rows), squeeze=False)
    for ax in axes.ravel():
        ax.axis("off")
    for ax, cm, s in zip(axes.ravel(), cms, subjects):
        ax.axis("on")
        norm = cm / np.clip(cm.sum(axis=1, keepdims=True), 1, None) * 100
        ax.imshow(norm, vmin=0, vmax=100, cmap="Blues")
        for i in range(len(classes)):
            for j in range(len(classes)):
                ax.text(j, i, f"{norm[i, j]:.0f}\n({cm[i, j]})", ha="center", va="center",
                        fontsize=7, color="white" if norm[i, j] > 55 else "black")
        ax.set_xticks(range(len(classes)))
        ax.set_yticks(range(len(classes)))
        ax.set_xticklabels(classes, fontsize=7)
        ax.set_yticklabels(classes, fontsize=7)
        ax.set_title(f"Test = {s}", fontsize=9)
        ax.set_xlabel("Predicted", fontsize=7)
        ax.set_ylabel("True", fontsize=7)
    save_fig(fig, "05_confusion_per_subject.png")


def plot_interval_examples(examples, classes):
    """One example per gesture: used to tune PEAK_K, SLOPE_K and FIT_ERR."""
    classes = [c for c in classes if c in examples]
    fig, axes = plt.subplots(len(classes), 1, figsize=(9, 2.6 * len(classes)), squeeze=False)
    for ax, c in zip(axes[:, 0], classes):
        d = examples[c]
        ang = np.degrees(d["ang"])
        for k, name in enumerate(("roll", "pitch", "yaw")):
            ax.plot(ang[:, k], label=name, lw=2 if k == d["axis"] else 1)
        ax.axvspan(d["c0"], d["c1"], color="gray", alpha=0.15, label="cue window")
        ax.axvspan(d["win0"], d["win0"] + W, color="green", alpha=0.18, label=f"{W}-sample window")
        ax.axvline(d["peak"], color="red", ls="--", lw=1, label="peak/valley")
        if d["interval"] is not None:
            ax.axvspan(*d["interval"], color="orange", alpha=0.25, label="refined interval")
        ax.set_ylabel("deg")
        ax.set_title(f"{c}: AHRS angles (baseline removed)", fontsize=10)
    axes[0, 0].legend(ncol=4, fontsize=7, frameon=False, loc="upper right")
    axes[-1, 0].set_xlabel("Sample")
    save_fig(fig, "03_interval_extraction.png")


def plot_importance(rf, sel, top=20):
    imp = rf.feature_importances_
    order = np.argsort(imp)[::-1][:top][::-1]
    names = [NAMES[sel.support_[i]] for i in order]
    domain = lambda n: n.split("_")[1] if n.count("_") >= 2 else n.split("_")[0]
    fig, ax = plt.subplots(figsize=(8, 0.28 * len(names) + 1.5))
    ax.barh(names, imp[order], color=[DOMAIN_COLORS.get(domain(n), "gray") for n in names])
    ax.set_xlabel("Random Forest importance")
    ax.set_title("Final model: feature importance")
    handles = [plt.Rectangle((0, 0), 1, 1, color=c) for c in DOMAIN_COLORS.values()]
    ax.legend(handles, ["time", "frequency", "time-frequency", "correlation"],
              loc="lower right", frameon=False)
    save_fig(fig, "04_feature_importance.png")





if __name__ == "__main__":
    os.makedirs(OUT_DIR, exist_ok=True)
    os.makedirs(IMG_DIR, exist_ok=True)

    X, y, subj, examples, qc = load_dataset()
    subjects, classes = sorted(set(subj)), sorted(set(y))
    print(f"{len(subjects)} subjects {subjects}, {X.shape[1]} candidate features, classes {classes}")
    if len(subjects) < 3:
        raise SystemExit("At least 3 subjects are required for leave-one-subject-out validation.")

    # leave-one-subject-out
    rows = []
    fold_cms = []
    cm_tot = np.zeros((len(classes), len(classes)), dtype=int)
    all_true, all_pred = [], []

    for fold, s in enumerate(subjects):
        te, tr = np.where(subj == s)[0], np.where(subj != s)[0]
        sel, rf, info = train_model(X, y, subj, tr, seed=fold)
        pred = rf.predict(sel.transform(X[te]))     # test set reduced with features chosen on train

        p, r, f1, _ = precision_recall_fscore_support(y[te], pred, labels=classes, average="macro", zero_division=0)

        rows.append(dict(fold=fold + 1, test_subject=s, n_test=len(te),
                         accuracy=accuracy_score(y[te], pred),
                         precision=p, recall=r, f1=f1,
                         n_features=len(sel.support_), n_trees=rf.n_estimators,
                         best_epoch=info["best_epoch"], epochs_run=info["epochs_run"]))
                         
        cm = confusion_matrix(y[te], pred, labels=classes)
        cm_tot += cm
        fold_cms.append(cm)
        all_true += list(y[te])
        all_pred += list(pred)

        print(f"fold {fold + 1}/{len(subjects)}  test={s}  acc={rows[-1]['accuracy']:.3f}  "
              f"features={len(sel.support_)}  trees={rf.n_estimators}")

    res = pd.DataFrame(rows)
    pd.set_option("display.width", 200)
    print("\n", res.round(3).to_string(index=False))

    summary = {m: dict(mean=float(res[m].mean()), std=float(res[m].std(ddof=0)))
               for m in ("accuracy", "precision", "recall", "f1")}

    summary["pooled_accuracy"] = float(accuracy_score(all_true, all_pred))

    summary["qc"] = qc

    print("\nMean ± std over folds:")
    for m in ("accuracy", "precision", "recall", "f1"):
        print(f"  {m:9s} {summary[m]['mean']:.3f} ± {summary[m]['std']:.3f}")

    print(f"  pooled accuracy: {summary['pooled_accuracy']:.3f}")
    cm_df = pd.DataFrame(cm_tot, index=classes, columns=classes)

    print("\nConfusion matrix (sum over folds, rows = true):\n", cm_df)

    # output files
    res.to_csv(os.path.join(OUT_DIR, "results_folds.csv"), index=False)
    cm_df.to_csv(os.path.join(OUT_DIR, "confusion_matrix.csv"))
    json.dump(summary, open(os.path.join(OUT_DIR, "results_summary.json"), "w"), indent=2)
    json.dump(dict(W=W, WAVELET=WAVELET, LEVEL=LEVEL, USE_MEASURED_DT=USE_MEASURED_DT,
                   BETA=BETA, BETA_INIT=BETA_INIT, INIT_SAMPLES=INIT_SAMPLES,
                   PEAK_K=PEAK_K, INTERVAL=INTERVAL, MARGIN=MARGIN,
                   SLOPE_K=SLOPE_K, FIT_ERR=FIT_ERR,
                   K_PER_CLASS=K_PER_CLASS, MAX_CORR=MAX_CORR,
                   EPOCHS=EPOCHS, TREES_PER_EPOCH=TREES_PER_EPOCH, PATIENCE=PATIENCE,
                   MAX_DEPTH=MAX_DEPTH, MIN_LEAF=MIN_LEAF,
                   subjects=subjects, classes=classes),
              open(os.path.join(OUT_DIR, "config.json"), "w"), indent=2)


    # final model on all subjects (selection on its own training part only)
    sel, rf, _ = train_model(X, y, subj, np.arange(len(y)), seed=123)
    export(rf, sel, os.path.join(OUT_DIR, "rf.json"))
    print(f"\nFinal model: {len(sel.support_)} features, {rf.n_estimators} trees "
          f"-> {OUT_DIR}/rf.json")
    print("Selected features:", ", ".join(NAMES[i] for i in sel.support_))

    # plots
    plot_metrics_per_subject(res)
    plot_confusion(cm_tot, classes)
    plot_confusion_per_subject(fold_cms, subjects, classes)
    plot_interval_examples(examples, classes)
    plot_importance(rf, sel)
    print(f"Plots saved in {IMG_DIR}/")