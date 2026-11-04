# Tiền tránh được: ba giả định

Đây là giả định, không phải số đo từ khách thật. Mẫu số là tổng số tiền của mọi phiên lừa đảo trong tập test. Tử số chỉ tính phiên lừa đảo.

Mỗi phiên lấy một `p_stop`. Thứ tự:

1. Mức 2 tăng cường dùng đúng `p_stop` của tăng cường, kể cả khi khách có người giám hộ.
2. Mức 2 còn lại, khách cao tuổi và có giám hộ, dùng `p_stop` của giám hộ.
3. Mức 2 còn lại dùng `p_stop` mức 2.
4. Mức 1 dùng `p_stop` mức 1.
5. Mức 0 không tính.
6. Mức 3, nếu có, tính `p_stop` = 1 vì lệnh bị giữ.

| Giả định | Mức 1 | Mức 2 | Tăng cường | Giám hộ |
|---|---:|---:|---:|---:|
| conservative | 0.08 | 0.12 | 0.12 | 0.18 |
| mid | 0.15 | 0.40 | 0.60 | 0.60 |
| trial-based | 0.15 | 0.80 | 0.85 | 0.85 |

`conservative` lấy các tỷ lệ của `response_model` hiện tại (mức 1 0.08, mức 2 0.12, giám hộ 0.18) và tính cả mức 1. Mô hình phản hồi không có hàng cho mức 2 tăng cường, nên giả định này gán cho tăng cường cùng 0.12, nhưng vẫn là một đầu vào riêng.

`mid` nâng mức dừng ở mức 2 và coi tăng cường hoặc giám hộ là 0.60.

`trial-based` lấy 0.80 cho mức 2 từ kết quả CTA có mục tiêu rủi ro ở Anh, và 0.85 cho tăng cường và giám hộ.
