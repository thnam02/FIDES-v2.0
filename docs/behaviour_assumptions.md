# Giả định của reference thao tác tổng hợp

File `engine/artifacts/behaviour_ref/*.json` được `write_synthetic_references` ghi lại với seed 42. Đây là phân phối demo, không phải dữ liệu người dùng thật. Ngưỡng `behaviour_p_rarity_at_most` = 0,05 trong `engine/policy/bank_policy.yaml` đã đánh `demo: true`: đó là giá trị thiết kế trên phân phối này, không phải ước lượng từ phiên thật.

## Tốc độ riêng từng người

`draw_person` lấy một hệ số tốc độ log-chuẩn, độ lệch chuẩn 0,4. Hệ số đó nhân vào khoảng nghỉ nhịp (`median_gap_ms`, `p90_gap_ms`), thời gian xem lại (`review_dwell_ms`), và khoảng nghỉ giữa các cụm gõ số tài khoản. `pause_to_action_ratio` có hệ số log-chuẩn riêng, cùng độ lệch chuẩn 0,4.

## Gõ số tài khoản

Một phiên `new_typed` thường là một cụm khoảng 8–14 chữ số (ba phần tư các phiên). Phần còn lại tách thành hai cụm, khoảng nghỉ khoảng 1,2–2 giây rồi nhân với tốc độ của người đó. Phiên một cụm không có khoảng nghỉ giữa cụm, nên đặc trưng đó không được chấm. QR, dán, và chọn người nhận đã lưu không sinh các số này.

`burst_count` của cả phiên vẫn được lưu (cụm khi khoảng nghỉ dưới 1,5 giây, ít nhất hai bước). Nó không nằm trong sáu nhóm chấm.

## Cuộc gọi và phiên được đọc

Một cuộc gọi nhân khoảng nghỉ nhịp và thời gian xem lại với 1,5. Hình dạng cụm gõ không đổi.

Phiên được đọc số gồm nhiều cụm 2–4 chữ số, nghỉ 2–5 giây, và không rời ứng dụng. Công tắc demo và ca đánh giá dùng đúng hình đó: bốn cụm, trung bình ba chữ số mỗi cụm, nghỉ giữa cụm 3,5 giây, `background_count` và `background_total_ms` bằng 0. Nhịp và thời gian xem lại giữ mức thường.

Điểm phiên là trung bình các nhóm thực sự được chấm. Nhóm đọc số vắng không bị tính là 0.
