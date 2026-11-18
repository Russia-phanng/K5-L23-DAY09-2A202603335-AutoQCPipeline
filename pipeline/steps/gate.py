"""Step — Quyết định Release / Hold / Rework dựa trên danh sách các Issue."""

def decide(issues, stems, cfg=None, reviewed=None):
    """Quyết định trạng thái Release / Hold / Rework cho lô dữ liệu."""
    if cfg is None:
        cfg = {}
    if reviewed is None:
        reviewed = set()
    else:
        reviewed = set(reviewed)

    stems_set = set(stems)
    total_stems = len(stems_set)

    # 1. Đếm và thu thập lỗi ERROR (Lỗi error KHÔNG THỂ bị che khuất bởi reviewed)
    errors = []
    for i in issues:
        severity = getattr(i, "severity", "error")
        if severity == "error":
            errors.append(i)

    n_errors = len(errors)
    reasons = [str(e) for e in errors]

    if n_errors > 0:
        return {
            "decision": "Rework",
            "reason": "Phát hiện lỗi nghiêm trọng (ERROR)",
            "reasons": reasons,
            "n_errors": n_errors,
            "n_warn_images": 0,
            "warn_ratio": 0.0,
            "n_images": total_stems
        }

    # 2. Xử lý cảnh báo WARNING (Warning có thể được miễn giảm nếu ảnh thuộc reviewed)
    warn_images = set()
    for i in issues:
        severity = getattr(i, "severity", "warn")
        if severity == "warn":
            img = getattr(i, "image", None)
            if img == "<dataset>" or img == "data.yaml" or (img in stems_set and img not in reviewed):
                if img in stems_set:
                    warn_images.add(img)

    n_warn_images = len(warn_images)
    warn_ratio = (n_warn_images / total_stems) if total_stems > 0 else 0.0
    
    warn_ratio_threshold = cfg.get("gate", {}).get("warn_ratio", 0.1)

    if warn_ratio >= warn_ratio_threshold:
        decision = "Hold"
        reason = f"Tỷ lệ ảnh cảnh báo ({n_warn_images}/{total_stems} = {warn_ratio:.1%}) vượt ngưỡng cho phép"
    else:
        decision = "Release"
        reason = "Dữ liệu đạt chuẩn"

    return {
        "decision": decision,
        "reason": reason,
        "reasons": [],
        "n_errors": 0,
        "n_warn_images": n_warn_images,
        "warn_ratio": warn_ratio,
        "n_images": total_stems
    }