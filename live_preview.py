import time
import cv2
import mss
import numpy as np
import onnxruntime as ort

MODEL_PATH = r"C:\Users\mbari\Videos\Captures\runs\player_v3\weights\best.onnx"
IMG_SIZE = 960
CONF_THRESH = 0.35
IOU_THRESH = 0.45
PREVIEW_SCALE = 0.65  # Scale preview window so it fits nicely on screen


def letterbox(img, new_shape=960):
    h, w = img.shape[:2]
    scale = min(new_shape / h, new_shape / w)
    nh, nw = int(round(h * scale)), int(round(w * scale))
    resized = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_LINEAR)
    pad_w = (new_shape - nw) // 2
    pad_h = (new_shape - nh) // 2
    canvas = np.full((new_shape, new_shape, 3), 114, dtype=np.uint8)
    canvas[pad_h:pad_h + nh, pad_w:pad_w + nw] = resized
    return canvas, scale, pad_w, pad_h


def detect(session, input_name, frame_bgr):
    inp, scale, pad_w, pad_h = letterbox(frame_bgr, IMG_SIZE)
    blob = inp[:, :, ::-1].transpose(2, 0, 1).astype(np.float32) / 255.0
    blob = np.expand_dims(blob, axis=0)

    out = session.run(None, {input_name: blob})[0]  # (1, 5, 18900)
    preds = out[0].T  # (18900, 5): cx, cy, w, h, conf

    scores = preds[:, 4]
    mask = scores >= CONF_THRESH
    preds = preds[mask]
    scores = scores[mask]

    if len(preds) == 0:
        return []

    boxes_xywh = []
    for cx, cy, bw, bh, _ in preds:
        x1 = int(((cx - bw / 2) - pad_w) / scale)
        y1 = int(((cy - bh / 2) - pad_h) / scale)
        w = int(bw / scale)
        h = int(bh / scale)
        boxes_xywh.append([x1, y1, w, h])

    indices = cv2.dnn.NMSBoxes(boxes_xywh, scores.tolist(), CONF_THRESH, IOU_THRESH)
    results = []
    if len(indices) > 0:
        for idx in indices.flatten():
            x, y, w, h = boxes_xywh[idx]
            results.append((x, y, x + w, y + h, float(scores[idx])))
    return results


def main():
    opts = ort.SessionOptions()
    opts.enable_mem_pattern = False
    session = ort.InferenceSession(
        MODEL_PATH,
        sess_options=opts,
        providers=[("DmlExecutionProvider", {"device_id": 0}), "CPUExecutionProvider"],
    )
    input_name = session.get_inputs()[0].name
    print("Active provider:", session.get_providers()[0])
    print("Pokrecem live preview... Stisni 'Q' u preview prozoru za izlaz.")

    with mss.mss() as sct:
        monitor = sct.monitors[1]
        while True:
            t0 = time.perf_counter()
            raw = np.array(sct.grab(monitor))
            frame = cv2.cvtColor(raw, cv2.COLOR_BGRA2BGR)

            dets = detect(session, input_name, frame)
            for x1, y1, x2, y2, conf in dets:
                cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
                cv2.putText(
                    frame,
                    f"player {conf:.2f}",
                    (x1, max(20, y1 - 8)),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.7,
                    (0, 255, 0),
                    2,
                )

            dt = time.perf_counter() - t0
            fps = 1.0 / dt if dt > 0 else 0.0
            cv2.putText(
                frame,
                f"FPS: {fps:.1f} | Detections: {len(dets)}",
                (20, 40),
                cv2.FONT_HERSHEY_SIMPLEX,
                1.0,
                (0, 255, 255),
                2,
            )

            disp = cv2.resize(
                frame,
                (int(frame.shape[1] * PREVIEW_SCALE), int(frame.shape[0] * PREVIEW_SCALE)),
            )
            cv2.imshow("Player v3 Live Preview (Q za izlaz)", disp)
            if cv2.waitKey(1) & 0xFF in (ord("q"), ord("Q"), 27):
                break

    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
