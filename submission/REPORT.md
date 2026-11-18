# Báo cáo Day 09 — Nguyễn Phương Nga, 2A202603335

## 1. Kết luận trước
Pipeline kết luận **Hold**. Hệ thống nhận **203 / 224 ảnh** qua cổng intake (loại 21 ảnh do hỏng, kích thước quá nhỏ, trùng lặp hoặc rò rỉ tập test) và xuất **203 / 203 ảnh** ra bản nháp dataset (`clean_v1`, chưa phát hành chính thức). Lý do chính: tỷ lệ ảnh cảnh báo sau khi duyệt hết ngân sách 80 ảnh vẫn ở mức **38 / 203 ảnh (18.7%)**, vượt ngưỡng cho phép tối đa 10%.

## 2. Lỗi và phân việc
| Mã lỗi | Số ảnh/dòng | Ai sửa (máy/người) | Vì sao |
|---|---:|---|---|
| `BAD_SIZE` | 3 / 224 ảnh | Máy (Intake) | Cạnh ngắn nhỏ hơn 250px, không đạt chuẩn đầu vào nên loại trực tiếp. |
| `CORRUPT_IMAGE` | 2 / 224 ảnh | Máy (Intake) | File ảnh hỏng cấu trúc byte (`UnidentifiedImageError`, `OSError`), không thể đọc dữ liệu. |
| `DUP_IMAGE_EXACT` | 8 / 224 ảnh | Máy (Intake) | Trùng lặp từng byte tuyệt đối với ảnh đã có trong tập dữ liệu. |
| `DUP_IMAGE_NEAR` | 3 / 224 ảnh | Máy (Intake) | Trùng gần đúng (khoảng cách pHash $\le 8$), loại bớt bản sao để tránh lệch phân phối. |
| `LEAK_TEST` | 5 / 224 ảnh | Máy (Intake) | Trùng với ảnh trong kho `test/val`, bắt buộc loại để tránh rò rỉ dữ liệu đánh giá. |
| `BAD_FORMAT` / `BOX_ZERO` / `BOX_OUT_OF_IMAGE` / `DUP_BOX` / `BAD_CLASS_ID` / `BAD_CLASS_NAME` | 35 thay đổi (`03_fixes.csv`) | Máy (Autofix) | Các lỗi cú pháp, trùng box hoặc tọa độ tràn biên có quy tắc hình học/cấu hình rõ ràng để tự động chuẩn hóa an toàn. |
| `MISSING_LABEL_FILE` | Vào hàng đợi | Người (Hàng đợi) | Ảnh chưa có file nhãn; máy không tự bịa nhãn mà chuyển cho người gán thủ công. |
| `POSSIBLE_MISSING` / `POSSIBLE_WRONG_CLASS` / `POSSIBLE_LOOSE_BOX` | 125 ảnh vào hàng đợi | Người (Hàng đợi) | Các cảnh báo ngữ nghĩa từ model lớn (`yolo26l`), cần mắt người xác nhận độ chính xác của box và lớp. |

`05_review_queue.csv` xếp các ảnh lỗi bắt buộc chưa sửa (`MISSING_LABEL_FILE`) lên đầu hàng, tiếp theo là các ảnh có nhiều cảnh báo ngữ nghĩa nhất từ `second_opinion` để tối đa hóa hiệu quả trên mỗi lượt duyệt. Với ngân sách 80 ảnh, người duyệt xử lý trọn vẹn **80 / 125 ảnh** ưu tiên cao nhất trong hàng đợi (bao gồm toàn bộ ảnh thiếu file nhãn và nhóm ảnh có mật độ lỗi ngữ nghĩa dày đặc nhất); **45 / 125 ảnh** còn lại chưa được duyệt vẫn giữ nguyên trạng thái cảnh báo và tính vào tỷ lệ 18.7% của cổng Gate.

## 3. Calibration (2 ngưỡng)
| Tham số | Khởi đầu | Đã chọn | Precision / Recall (trước → sau) | Lý do (đánh đổi) |
|---|---|---|---|---|
| `duplicates.phash_dist` | 2 | 8 | **DUP_IMAGE_NEAR:**<br>P: 1.00 → 1.00<br>R: 0.50 → 0.67 | - **Khởi đầu (2):** Bỏ sót nhiều ảnh gần trùng (recall thấp 0.50).<br>- **Đã chọn (8):** Nằm an toàn ở giữa vùng ổn định (4–14), giữ vững precision tuyệt đối (1.00) và nâng recall lên 0.67. Đồng thời tránh được bẫy gộp nhầm cụm (chaining) như khi đẩy lên ngưỡng cao (16–20). |
| `second_opinion.conf` | 0.25 | 0.6 | **POSSIBLE_MISSING:**<br>P: 0.50 → 0.57<br>R: 1.00 → 1.00<br><br>**POSSIBLE_WRONG_CLASS:**<br>P: 0.56 → 0.62<br>R: 0.83 → 0.83 | - **Khởi đầu (0.25):** Sinh ra quá nhiều báo động giả (precision thấp, đặc biệt là LOOSE_BOX chỉ 0.29), gây quá tải cho ngân sách kiểm duyệt.<br>- **Đã chọn (0.6):** Lọc bớt nhiễu hiệu quả, nâng precision của MISSING lên 0.57 và WRONG_CLASS lên 0.62 mà vẫn bảo toàn trọn vẹn recall (1.00 cho missing và 0.83 cho wrong class). |

## 4. Cửa chặn và những điểm mù pipeline KHÔNG bắt được

### (a) Chứng minh cửa chặn hoạt động đúng (Budget = 0)
Khi chạy thực nghiệm kiểm chứng với ngân sách người duyệt bằng 0 (`python -m pipeline.run --budget 0 --reports work/rep_nb --export-dir work/exp_nb`), do không có nhân sự can thiệp xử lý các ảnh thiếu file nhãn (`MISSING_LABEL_FILE`) và các cảnh báo tồn đọng:
- **Kết luận của Gate:** Chuyển từ `Hold` thành **`Rework`**.
- **Mã thoát (Exit Code):** Trả về mã **20** (chuẩn quy định: 0 cho Release, 10 cho Hold, 20 cho Rework).
- **Hành vi xuất dữ liệu:** Pipeline từ chối xuất bản dataset (`submission/export/clean_v1` không được tạo ra bản chính thức), đảm bảo dữ liệu chưa đạt chuẩn không bị rò rỉ ra môi trường downstream.

### (b) Các điểm mù (Blind Spots) mà Pipeline tự động không thể bắt được
Dù hệ thống QC kết hợp rule-based và second opinion (`yolo26l`) đạt hiệu quả cao, vẫn tồn tại các điểm mù thực tế đòi hỏi sự can thiệp thủ công:
1. **Box lỏng nhẹ (Loose Box tinh vi):** Các trường hợp bounding box ôm sát đối tượng ở mức ranh giới (IoU nằm lửng lơ quanh ngưỡng biên `iou_loose`), khiến model lớn hoặc quy tắc hình học không đủ cơ sở phân định rõ ràng đây là lỗi gán nhãn hay do đặc thù hình dạng vật thể.
2. **Nhầm lẫn lớp phức tạp (Semantic Confusion):** Khi các đối tượng có hình thái học tương tự nhau (ví dụ: phân biệt xe tải nhỏ `truck` với ô tô con dạng lớn `car`, hoặc các biến thể phân khúc xe), model kiểm định `yolo26l` đôi khi cũng mắc sai lầm tương tự model gán nhãn gốc, dẫn đến việc bỏ sót lỗi `POSSIBLE_WRONG_CLASS`.
3. **Ảnh trùng lặp biến đổi mạnh (Complex Image Transformations):** Các cặp ảnh chụp cùng một khu vực nhưng bị thay đổi góc nhìn lớn, chênh lệch điều kiện ánh sáng mạnh (ngày/đêm), hoặc bị che khuất một phần. Thuật toán perceptual hash (`phash_dist`) ở ngưỡng an toàn có thể không nhận diện được đây là bản sao gần đúng (`DUP_IMAGE_NEAR`), dẫn đến lọt lưới trùng lặp dữ liệu.

## 5. Train: raw vs clean (tùy chọn, chấm riêng)
Chưa chạy. Lý do: tập trung hoàn thiện và kiểm thử toàn bộ lõi AutoQC pipeline (intake, rule-based gate, autofix, second opinion, calibration) trước khi triển khai huấn luyện trên Colab.

## 6. Quyết định và ghi chú AI

### (a) Quyết định cuối cùng và hướng xử lý
- **Quyết định hiện tại:** **HOLD** (với tỷ lệ ảnh cảnh báo đạt 18.72%, vượt ngưỡng an toàn 10%).
- **Cần làm gì để chuyển thành Release?** 
  1. Tổ chức phân công nhân sự kiểm duyệt qua hàng đợi (Review Queue - tối đa 80 ảnh) để xử lý dứt điểm các trường hợp `POSSIBLE_MISSING`, `POSSIBLE_LOOSE_BOX` và `MISSING_LABEL_FILE`.
  2. Sau khi con người xác nhận và cập nhật lại nhãn chuẩn cho các ảnh trong hàng đợi, chạy lại pipeline. Nếu tỷ lệ ảnh cảnh báo sau duyệt giảm xuống dưới ngưỡng 10% và không còn lỗi bắt buộc tồn đọng, hệ thống sẽ tự động chuyển sang trạng thái **Release** và xuất bản chính thức dataset (`submission/export/clean_v1`).

### (b) Ghi chú sử dụng AI (AI Collaboration Notes)
1. **Prompt chính:** *"Viết hàm kiểm tra `second_opinion.py` theo kiến trúc config-driven, xử lý logic đối chiếu IoU giữa dự đoán model lớn `yolo26l` và nhãn gốc, đồng thời đảm bảo không sinh ngoại lệ khi dữ liệu thiếu hoặc rỗng."*
2. **Cách kiểm code AI:** Đọc kỹ từng khối lệnh, kiểm tra điều kiện biên (edge cases như file nhãn trống, tọa độ tràn biên, danh sách dự đoán `None`), sau đó viết và chạy các bộ test case khắt khe qua `pytest` để đối chiếu từng mã lỗi (`POSSIBLE_MISSING`, `POSSIBLE_FALSE_POS`,...).
3. **1 lần AI sai:** AI từng sinh nhầm logic tính chỉ số IoU kết hợp trực tiếp diện tích pixel vào vòng lặp kiểm tra `FALSE_POS` (áp dụng nhầm bộ lọc `min_area_px` vào chiều nhãn gốc → dự đoán, dẫn đến việc bỏ sót các box nhãn hợp lệ bị nhỏ). Đã phát hiện khi chạy unit test và yêu cầu AI tách biệt hoàn toàn logic lọc diện tích (chỉ áp dụng cho model prediction) với logic duyệt nhãn gốc.

*(Thưởng +2, tùy chọn)* CVAT: lọc `width < 20`, ảnh/số box khớp, đối chiếu `BOX_TINY` (xem docs/CVAT_FILTER.md), 1 câu về `can_review`.
