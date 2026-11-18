"""CHECK 2 — Dòng nhãn YOLO: sai định dạng, ID lớp lạ, box tràn ảnh, box rỗng, box lặp.   (Script 2 trong slide)   ★★

Test:  pytest tests/test_label_format.py -q

Mỗi dòng nhãn: `id cx cy w h` (5 số, toạ độ 0–1). Trả về list[Issue]; `Issue.line` = số dòng (đếm từ 1).

| code             | severity | khi nào                                                                  |
|------------------|----------|--------------------------------------------------------------------------|
| BAD_FORMAT       | ERROR    | không đúng 5 cột số (dùng `parse_yolo_line`, bắt `ValueError`)           |
| BAD_CLASS_ID     | ERROR    | id lớp ngoài 0..len(ds.classes)-1                                        |
| BOX_ZERO         | ERROR    | w <= 0 hoặc h <= 0                                                       |
| BOX_OUT_OF_IMAGE | ERROR    | mép box vượt [0,1] quá `cfg["label_format"]["overflow_tol"]`; extra={"overflow": mức tràn} |
| DUP_BOX          | ERROR    | cùng lớp với một dòng TRƯỚC ĐÓ và IoU > `dup_box_iou`; báo ở dòng SAU    |
| BOX_TINY         | WARN     | cạnh ngắn của box (px) < `min_box_px`  (cần `ds.image_size(stem)`)       |
| BOX_HUGE         | WARN     | w*h > `max_box_frac`                                                     |

Gợi ý
- Mép trái = x - w/2, mép phải = x + w/2 (xem câu hỏi "dòng YOLO nào lỗi?" trong slide).
- Một dòng hỏng (BAD_FORMAT, BAD_CLASS_ID, BOX_ZERO) thì `continue`, đừng kiểm tiếp hình học của dòng đó.
- Dòng thiếu cột làm script của slide dừng giữa chừng: đây là lý do phải `try/except`.
- `iou_xywh(a, b)` có sẵn trong common.py.
- Ngưỡng nằm trong `cfg["label_format"]` — đừng viết cứng số vào code.
"""
from ..common import ERROR, WARN, Issue, iou_xywh, parse_yolo_line  # noqa: F401


def run(ds, cfg):
    issues = []
    fmt_cfg = cfg.get("label_format", {})
    overflow_tol = fmt_cfg.get("overflow_tol", 0.001)
    dup_iou_thresh = fmt_cfg.get("dup_box_iou", 0.8)
    min_box_px = fmt_cfg.get("min_box_px", 12)
    max_box_frac = fmt_cfg.get("max_box_frac", 0.95)
    
    num_classes = len(ds.classes) if hasattr(ds, "classes") else 4

    for stem in ds.image_files():
        lines = ds.read_label_lines(stem)
        valid_boxes = []  # Lưu list các tuple (class_id, [cx, cy, w, h], line_num) để check DUP_BOX

        for line_num, line_str in lines:
            stripped = line_str.strip()
            if not stripped:
                continue

            # 1. Parse dòng nhãn YOLO
            try:
                class_id, cx, cy, w, h = parse_yolo_line(stripped)
            except (ValueError, TypeError):
                issues.append(Issue("label_format", ERROR, "BAD_FORMAT", stem, f"Dòng {line_num} sai định dạng hoặc thiếu cột", line=line_num))
                continue

            # 2. Kiểm tra ID lớp (BAD_CLASS_ID)
            if not isinstance(class_id, int) or not (0 <= class_id < num_classes):
                issues.append(Issue("label_format", ERROR, "BAD_CLASS_ID", stem, f"ID lớp không hợp lệ: {class_id}", line=line_num))
                continue

            # 3. Kiểm tra box rỗng / âm (BOX_ZERO)
            if w <= 0 or h <= 0:
                issues.append(Issue("label_format", ERROR, "BOX_ZERO", stem, f"Kích thước box không hợp lệ (w={w}, h={h})", line=line_num))
                continue

            # Tính toán các mép box (hệ toạ độ 0-1)
            xmin = cx - w / 2
            xmax = cx + w / 2
            ymin = cy - h / 2
            ymax = cy + h / 2

            # 4. Kiểm tra tràn biên ảnh (BOX_OUT_OF_IMAGE)
            left_ov = max(0.0, 0.0 - xmin)
            right_ov = max(0.0, xmax - 1.0)
            top_ov = max(0.0, 0.0 - ymin)
            bottom_ov = max(0.0, ymax - 1.0)
            max_overflow = max(left_ov, right_ov, top_ov, bottom_ov)

            if max_overflow > overflow_tol:
                issues.append(Issue("label_format", ERROR, "BOX_OUT_OF_IMAGE", stem, f"Box vượt ngoài biên ảnh (mức tràn: {max_overflow:.4f})", line=line_num, extra={"overflow": max_overflow}))

            # 5. Kiểm tra kích thước quá nhỏ (BOX_TINY) hoặc quá lớn (BOX_HUGE)
            try:
                img_w, img_h = ds.image_size(stem)
                box_w_px = w * img_w
                box_h_px = h * img_h
                if min(box_w_px, box_h_px) < min_box_px:
                    issues.append(Issue("label_format", WARN, "BOX_TINY", stem, f"Cạnh ngắn của box quá nhỏ ({min(box_w_px, box_h_px):.1f}px < {min_box_px}px)", line=line_num))
            except Exception:
                pass

            if w * h > max_box_frac:
                issues.append(Issue("label_format", WARN, "BOX_HUGE", stem, f"Diện tích box chiếm quá lớn ({w*h:.2f} > {max_box_frac})", line=line_num))

            # 6. Kiểm tra box trùng lặp (DUP_BOX) với các dòng trước đó cùng lớp
            current_box = [cx, cy, w, h]
            is_duplicate = False
            for prev_class, prev_box, prev_line in valid_boxes:
                if prev_class == class_id:
                    iou_val = iou_xywh(current_box, prev_box)
                    if iou_val > dup_iou_thresh:
                        issues.append(Issue("label_format", ERROR, "DUP_BOX", stem, f"Trùng lặp với dòng {prev_line} (IoU={iou_val:.2f})", line=line_num))
                        is_duplicate = True
                        break

            if not is_duplicate:
                valid_boxes.append((class_id, current_box, line_num))

    return issues