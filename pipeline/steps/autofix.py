"""BƯỚC 2/4 — Sửa tự động những lỗi bắt buộc mà máy sửa được AN TOÀN.   ★★

Test:  pytest tests/test_autofix.py -q

`fix(ds, issues, cfg) -> list[dict]`: duyệt `issues` (chỉ lỗi severity ERROR), sửa thẳng vào thư mục `ds`,
và trả về danh sách thay đổi; mỗi phần tử có khoá: image, line, action, before, after
(đây chính là file `03_fixes.csv` — bằng chứng pipeline đã làm gì, người có thể kiểm lại).

| code lỗi                                       | cách sửa                                    | action           |
|------------------------------------------------|---------------------------------------------|------------------|
| BAD_FORMAT, BAD_CLASS_ID, BOX_ZERO, DUP_BOX    | xoá dòng đó khỏi file nhãn                  | "drop_line"      |
| BOX_OUT_OF_IMAGE                               | cắt box về trong [0,1] (giữ nguyên lớp)     | "clip_box"       |
| MISSING_LABEL_FILE                             | KHÔNG sửa file (máy không thể bịa nhãn): ghi 1 dòng fix, before="(không có file)", after="chuyển người gán" | "needs_label" |
| BAD_CLASS_NAME                                 | ghi lại `names` trong data.yaml đúng `cfg["classes"]` | "rename_classes" |
| DUP_IMAGE_*, LEAK_TEST, CORRUPT_IMAGE, BAD_SIZE| xoá ảnh + nhãn khỏi `ds`                    | "remove_image"   |

Bẫy cần nghĩ tới (có test cho từng cái)
- Một file có NHIỀU dòng lỗi: số dòng trong `issues` là số dòng GỐC. Nếu xoá từng dòng một thì số dòng lệch.
  Gom theo file, rồi ghi lại MỘT lần.
- Sau khi cắt, box có thể không còn diện tích (nằm hẳn ngoài ảnh): lúc đó xoá dòng thay vì ghi box rỗng.
- Một dòng có 2 lỗi (vd. BOX_OUT_OF_IMAGE + DUP_BOX): xoá dòng thắng, chỉ ghi 1 fix `drop_line`, không ghi thêm `clip_box`. Dòng trống ở giữa file vẫn đếm vào số dòng gốc.
- Ảnh vừa bị xoá (DUP_IMAGE_*...) mà còn issue dòng của chính nó: bỏ qua êm, không được báo lỗi/chết.
- Không động tới lỗi WARN (cảnh báo là việc của người). Không sửa file ở `data/raw/` — chỉ sửa `ds`.
- Chạy lần 2 trên dữ liệu đã sửa phải không làm gì thêm (idempotent) — NGOẠI LỆ duy nhất: `needs_label` được ghi lại mỗi lần còn lỗi `MISSING_LABEL_FILE` (vì ảnh vẫn chưa có nhãn).

- `needs_label` KHÔNG tạo file nhãn rỗng (rỗng = "ảnh nền", khác với "chưa gán"). `review_queue` sẽ đẩy ảnh này lên đầu hàng đợi cho người.

Gợi ý: `yaml.safe_load / safe_dump`.
"""
"""Step — Tự động sửa lỗi (autofix) dựa trên danh sách các Issue."""

"""Step — Tự động sửa lỗi (autofix) dựa trên danh sách các Issue."""

from pathlib import Path
import yaml


def fix(ds, issues, cfg):
    """Thực hiện sửa lỗi tự động trên dataset dựa theo danh sách issues.
    
    Trả về danh sách dict chứa các log hành động autofix với cấu trúc:
    {"image": ..., "line": ..., "action": ..., "before": ..., "after": ...}
    """
    fixes = []
    classes_target = cfg.get("classes", [])
    class_aliases = cfg.get("class_aliases", {})

    # 1. Xử lý đồng bộ tên lớp trong data.yaml (BAD_CLASS_NAME)
    yaml_rename_issues = [i for i in issues if i.code == "BAD_CLASS_NAME" and getattr(i, "image", None) == "data.yaml"]
    if yaml_rename_issues:
        try:
            names = ds.yaml_names()
            if names is not None:
                # Cập nhật lại names theo đúng classes_target hoặc dựa trên class_aliases
                for idx in list(names.keys()):
                    current_name = names[idx]
                    if current_name in class_aliases:
                        names[idx] = class_aliases[current_name]
                    elif idx < len(classes_target):
                        names[idx] = classes_target[idx]
                
                if hasattr(ds, "save_yaml_names"):
                    ds.save_yaml_names(names)
                elif hasattr(ds, "yaml_path") and ds.yaml_path.exists():
                    data = yaml.safe_load(ds.yaml_path.read_text(encoding="utf-8")) or {}
                    data["names"] = names
                    ds.yaml_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

                fixes.append({
                    "image": "data.yaml",
                    "line": None,
                    "action": "rename_classes",
                    "before": str(names),
                    "after": str(classes_target)
                })
        except Exception:
            pass

    # 2. Xử lý xóa ảnh lỗi (DUP_IMAGE_*, LEAK_TEST, CORRUPT_IMAGE, BAD_SIZE)
    remove_codes = ("DUP_IMAGE_EXACT", "DUP_IMAGE_NEAR", "LEAK_TEST", "CORRUPT_IMAGE", "BAD_SIZE")
    remove_img_issues = [i for i in issues if i.code in remove_codes and getattr(i, "image", None) and i.image not in ("<dataset>", "data.yaml")]
    removed_images = set()
    for i in remove_img_issues:
        stem = i.image
        if stem not in removed_images:
            try:
                img_path = ds.image_path(stem) if hasattr(ds, "image_path") else None
                if img_path and Path(img_path).exists():
                    Path(img_path).unlink()
                
                label_path = ds.label_path(stem) if hasattr(ds, "label_path") else None
                if label_path and Path(label_path).exists():
                    Path(label_path).unlink()
                
                removed_images.add(stem)
                fixes.append({
                    "image": stem,
                    "line": None,
                    "action": "remove_image",
                    "before": "exists",
                    "after": "removed"
                })
            except Exception:
                pass

    # 3. Xử lý thiếu file nhãn (MISSING_LABEL_FILE) -> needs_label
    missing_label_issues = [i for i in issues if i.code == "MISSING_LABEL_FILE" and getattr(i, "image", None)]
    for i in missing_label_issues:
        stem = i.image
        if stem not in removed_images:
            fixes.append({
                "image": stem,
                "line": None,
                "action": "needs_label",
                "before": "(không có file)",
                "after": "chuyển người gán"
            })

    # 4. Gom nhóm các issue liên quan đến dòng nhãn theo từng ảnh
    image_issues_map = {}
    for i in issues:
        # Chỉ xử lý các lỗi severity == "error"
        if getattr(i, "severity", "error") != "error":
            continue
        stem = getattr(i, "image", None)
        if not stem or stem in removed_images or stem in ("<dataset>", "data.yaml"):
            continue
        line = getattr(i, "line", None)
        if line is not None:
            image_issues_map.setdefault(stem, []).append(i)

    # Duyệt qua từng ảnh để sửa nội dung file nhãn (.txt)
    for stem, img_iss in image_issues_map.items():
        try:
            if hasattr(ds, "read_label_lines"):
                lines_data = ds.read_label_lines(stem)
            else:
                continue
            if not lines_data:
                continue
        except Exception:
            continue

        lines_to_drop = set()
        clips_to_apply = {}

        for iss in img_iss:
            ln = iss.line
            code = iss.code
            if code in ("BAD_FORMAT", "BAD_CLASS_ID", "BOX_ZERO", "DUP_BOX"):
                lines_to_drop.add(ln)
            elif code == "BOX_OUT_OF_IMAGE":
                target_line_str = next((l_str for l_num, l_str in lines_data if l_num == ln), None)
                if target_line_str and ln not in lines_to_drop:
                    parts = target_line_str.strip().split()
                    if len(parts) == 5:
                        try:
                            c_id = parts[0]
                            cx, cy, w, h = map(float, parts[1:])
                            
                            xmin = cx - w / 2
                            xmax = cx + w / 2
                            ymin = cy - h / 2
                            ymax = cy + h / 2

                            if xmax <= 0 or xmin >= 1.0 or ymax <= 0 or ymin >= 1.0 or w <= 0 or h <= 0:
                                lines_to_drop.add(ln)
                            else:
                                new_xmin = max(0.0, xmin)
                                new_xmax = min(1.0, xmax)
                                new_ymin = max(0.0, ymin)
                                new_ymax = min(1.0, ymax)

                                new_w = new_xmax - new_xmin
                                new_h = new_ymax - new_ymin
                                new_cx = new_xmin + new_w / 2
                                new_cy = new_ymin + new_h / 2

                                if new_w <= 0 or new_h <= 0:
                                    lines_to_drop.add(ln)
                                else:
                                    new_line_str = f"{c_id} {new_cx} {new_cy} {new_w} {new_h}"
                                    clips_to_apply[ln] = (target_line_str.strip(), new_line_str)
                        except Exception:
                            lines_to_drop.add(ln)

        new_lines_output = []
        for l_num, l_str in lines_data:
            stripped = l_str.strip()
            if not stripped:
                new_lines_output.append(l_str)
                continue

            if l_num in lines_to_drop:
                fixes.append({
                    "image": stem,
                    "line": l_num,
                    "action": "drop_line",
                    "before": stripped,
                    "after": ""
                })
                continue

            if l_num in clips_to_apply:
                before_str, after_str = clips_to_apply[l_num]
                new_lines_output.append(after_str)
                fixes.append({
                    "image": stem,
                    "line": l_num,
                    "action": "clip_box",
                    "before": before_str,
                    "after": after_str
                })
                continue

            new_lines_output.append(l_str)

        try:
            label_path = ds.label_path(stem) if hasattr(ds, "label_path") else None
            if label_path:
                label_path.parent.mkdir(parents=True, exist_ok=True)
                label_path.write_text("\n".join(new_lines_output) + ("\n" if new_lines_output else ""), encoding="utf-8")
        except Exception:
            pass

    return fixes