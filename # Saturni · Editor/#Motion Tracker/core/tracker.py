"""Point tracker backend for the PointTracker Premiere panel.

Runs as a long-lived process: reads one JSON request per line on stdin,
writes JSON lines to stdout. Every response carries the request "id".

Commands:
  open   {path}                       -> decode once, cache previews, return info
  frame  {index}                      -> preview JPEG (base64) of a frame
  track  {ref, x, y, w, h, margins:[l,t,r,b], adapt, minConf}
                                      -> track feature box (full-res pixels)
                                         forward and backward from frame `ref`;
                                         points are [x, y, confidence, scale, angleDeg]
                                         with scale/angle relative to frame `ref`
"""
import base64
import json
import math
import sys

import cv2
import numpy as np

PREVIEW_MAX_SIDE = 1920  # previews are zoomable in the panel, keep them sharp

state = {"path": None, "info": None, "previews": []}


def send(obj):
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def cmd_open(req):
    path = req["path"]
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        raise RuntimeError("Cannot open video: " + path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 0.0
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    approx = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    scale = min(1.0, PREVIEW_MAX_SIDE / float(max(w, h)))
    pw, ph = int(round(w * scale)), int(round(h * scale))
    previews = []
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        small = cv2.resize(frame, (pw, ph), interpolation=cv2.INTER_AREA) if scale < 1 else frame
        previews.append(cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, 85])[1].tobytes())
        if len(previews) % 10 == 0:
            send({"id": req["id"], "progress": len(previews), "total": max(approx, len(previews))})
    cap.release()
    if not previews:
        raise RuntimeError("The video has no frames")
    state["path"] = path
    state["previews"] = previews
    state["info"] = {"fps": fps, "width": w, "height": h, "frames": len(previews),
                     "previewWidth": pw, "previewHeight": ph}
    return state["info"]


def cmd_frame(req):
    i = max(0, min(int(req["index"]), len(state["previews"]) - 1))
    return {"index": i, "jpeg": base64.b64encode(state["previews"][i]).decode("ascii")}


def gray8(frame_bgr):
    return cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)


def smooth_f32(g8):
    return cv2.GaussianBlur(g8.astype(np.float32), (3, 3), 0)


def subpixel_peak(res, loc):
    """Parabolic refinement of the correlation maximum."""
    x, y = loc
    dx = dy = 0.0
    if 0 < x < res.shape[1] - 1:
        l, c, r = res[y, x - 1], res[y, x], res[y, x + 1]
        d = l - 2 * c + r
        if d != 0:
            dx = 0.5 * (l - r) / d
    if 0 < y < res.shape[0] - 1:
        t, c, b = res[y - 1, x], res[y, x], res[y + 1, x]
        d = t - 2 * c + b
        if d != 0:
            dy = 0.5 * (t - b) / d
    return x + max(-0.5, min(0.5, dx)), y + max(-0.5, min(0.5, dy))


IDENTITY = np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]])
LK = dict(winSize=(21, 21), maxLevel=2, criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 30, 0.01))


def compose(a, b):
    """2x3 affine a after b."""
    return np.hstack([a[:, :2] @ b[:, :2], a[:, :2] @ b[:, 2:] + a[:, 2:]])


class Tracker:
    """Template-matching tracker in the spirit of the After Effects tracker:
    a feature box is searched inside a larger search box around the
    predicted position; the template adapts when confidence drops.
    Scale and rotation come from corners around the feature, matched directly
    against an anchor frame (not chained frame to frame, so errors do not
    accumulate) and fitted with a similarity transform. The anchor moves on
    only when too few corners survive."""

    def __init__(self, g8, cx, cy, fw, fh, margins, adapt, min_conf):
        self.fw = max(8, int(round(fw)))
        self.fh = max(8, int(round(fh)))
        # search margins around the feature box: left, top, right, bottom
        self.ml, self.mt, self.mr, self.mb = [max(1, int(round(m))) for m in margins]
        self.adapt = adapt  # "low" | "always" | "never"
        self.min_conf = min_conf
        self.c = np.array([cx, cy], dtype=np.float64)
        self.v = np.zeros(2)
        self.tpl = self.patch(smooth_f32(g8), self.c)
        self.scale, self.angle = 1.0, 0.0
        self.base = IDENTITY.copy()  # reference frame -> anchor frame
        self.sim = IDENTITY.copy()   # anchor frame -> current frame
        self.set_anchor(g8)

    def patch(self, gray, c):
        return cv2.getRectSubPix(gray, (self.fw, self.fh), (float(c[0]), float(c[1])))

    def set_anchor(self, g8):
        """Start matching corners against the current frame."""
        self.base = compose(self.sim, self.base)
        self.sim = IDENTITY.copy()
        self.anchor, self.anchor_c = g8, self.c.copy()
        H, W = g8.shape
        # Corners come from the whole search area: a wider baseline gives steadier scale/rotation.
        k = self.scale
        x0, y0 = max(0, int(self.c[0] - (self.fw / 2 + self.ml) * k)), max(0, int(self.c[1] - (self.fh / 2 + self.mt) * k))
        x1, y1 = min(W, int(self.c[0] + (self.fw / 2 + self.mr) * k) + 1), min(H, int(self.c[1] + (self.fh / 2 + self.mb) * k) + 1)
        self.anchor_pts = None
        if x1 - x0 >= 4 and y1 - y0 >= 4:
            mask = np.zeros_like(g8)
            mask[y0:y1, x0:x1] = 255
            self.anchor_pts = cv2.goodFeaturesToTrack(g8, 100, 0.01, 3, mask=mask, blockSize=5)

    def update_similarity(self, g8):
        pts = self.anchor_pts
        if pts is None or len(pts) < 6:
            self.set_anchor(g8)
            return
        # Guess: last similarity, re-centred on the template-matched position.
        pred = self.sim.copy()
        pred[:, 2] += self.c - (pred[:, :2] @ self.anchor_c + pred[:, 2])
        guess = cv2.transform(pts, pred)
        nxt, st, _ = cv2.calcOpticalFlowPyrLK(self.anchor, g8, pts, guess.copy(), flags=cv2.OPTFLOW_USE_INITIAL_FLOW, **LK)
        back, st2, _ = cv2.calcOpticalFlowPyrLK(g8, self.anchor, nxt, pts.copy(), flags=cv2.OPTFLOW_USE_INITIAL_FLOW, **LK)
        fb = np.linalg.norm((pts - back).reshape(-1, 2), axis=1)
        good = (st.ravel() == 1) & (st2.ravel() == 1) & (fb < 1.0)
        inliers = 0
        if good.sum() >= 6:
            m, inl = cv2.estimateAffinePartial2D(pts[good], nxt[good], method=cv2.RANSAC, ransacReprojThreshold=1.0)
            if m is not None:
                inliers = int(inl.sum())
                if inliers >= 6:
                    self.sim = m
                    # The corner fit follows scale and rotation, the fixed template does not:
                    # take the position from it.
                    c = m[:, :2] @ self.anchor_c + m[:, 2]
                    self.v += c - self.c
                    self.c = c
        total = compose(self.sim, self.base)
        self.scale = math.hypot(total[0, 0], total[1, 0])
        self.angle = math.atan2(total[1, 0], total[0, 0])
        if inliers < max(6, 0.5 * len(pts)):  # the detail changed too much: re-anchor here
            self.set_anchor(g8)

    def step(self, g8):
        gray = smooth_f32(g8)
        H, W = gray.shape
        pred = self.c + self.v
        x0 = int(np.floor(pred[0] - self.fw / 2.0 - self.ml))
        y0 = int(np.floor(pred[1] - self.fh / 2.0 - self.mt))
        x1 = x0 + self.fw + self.ml + self.mr
        y1 = y0 + self.fh + self.mt + self.mb
        x0c, y0c, x1c, y1c = max(0, x0), max(0, y0), min(W, x1), min(H, y1)
        if x1c - x0c < self.fw or y1c - y0c < self.fh:
            return 0.0  # feature left the frame
        region = gray[y0c:y1c, x0c:x1c]
        res = cv2.matchTemplate(region, self.tpl, cv2.TM_CCOEFF_NORMED)
        _, conf, _, loc = cv2.minMaxLoc(res)
        px, py = subpixel_peak(res, loc)
        new_c = np.array([x0c + px + (self.fw - 1) / 2.0, y0c + py + (self.fh - 1) / 2.0])
        self.v = new_c - self.c
        self.c = new_c
        if self.adapt == "always" or (self.adapt == "low" and conf < self.min_conf):
            self.tpl = self.patch(gray, self.c)
        self.update_similarity(g8)
        return float(conf)

    def point(self, conf):
        return [float(self.c[0]), float(self.c[1]), conf, self.scale, math.degrees(self.angle)]


def cmd_track(req):
    info = state["info"]
    if not info:
        raise RuntimeError("No video is open")
    n = info["frames"]
    ref = max(0, min(int(req["ref"]), n - 1))
    fw, fh = float(req["w"]), float(req["h"])
    cx, cy = float(req["x"]) + fw / 2.0, float(req["y"]) + fh / 2.0
    margins = req.get("margins") or [fw * 1.5, fh * 1.5, fw * 1.5, fh * 1.5]
    args = (fw, fh, [float(m) for m in margins], req.get("adapt", "low"), float(req.get("minConf", 0.8)))

    points = [None] * n
    points[ref] = [cx, cy, 1.0, 1.0, 0.0]
    done = [1]

    def report():
        done[0] += 1
        if done[0] % 5 == 0 or done[0] == n:
            send({"id": req["id"], "progress": done[0], "total": n})

    cap = cv2.VideoCapture(state["path"])
    before = []  # 8-bit grayscale frames preceding ref, for the backward pass
    i = 0
    while i < ref:
        ok, f = cap.read()
        if not ok:
            break
        before.append(gray8(f))
        i += 1
    ok, f = cap.read()
    if not ok:
        raise RuntimeError("Cannot read the reference frame")
    ref_g = gray8(f)

    # Backward from ref
    tr = Tracker(ref_g, cx, cy, *args)
    for j in range(len(before) - 1, -1, -1):
        points[j] = tr.point(tr.step(before[j]))
        report()
    before = None

    # Forward from ref
    tr = Tracker(ref_g, cx, cy, *args)
    j = ref + 1
    while j < n:
        ok, f = cap.read()
        if not ok:
            break
        points[j] = tr.point(tr.step(gray8(f)))
        report()
        j += 1
    cap.release()

    # Frames the decoder could not deliver: hold the last known values
    last = points[ref]
    for k in range(ref, n):
        if points[k] is None:
            points[k] = last[:2] + [0.0] + last[3:]
        last = points[k]
    return {"ref": ref, "points": [[round(p[0], 3), round(p[1], 3), round(p[2], 3), round(p[3], 5), round(p[4], 4)]
                                   for p in points]}


COMMANDS = {"open": cmd_open, "frame": cmd_frame, "track": cmd_track}


def main():
    send({"ready": True, "opencv": cv2.__version__})
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        rid = None
        try:
            req = json.loads(line)
            rid = req.get("id")
            result = COMMANDS[req["cmd"]](req)
            send({"id": rid, "ok": True, "result": result})
        except Exception as e:  # report every failure back to the panel
            send({"id": rid, "ok": False, "error": str(e)})


if __name__ == "__main__":
    main()
