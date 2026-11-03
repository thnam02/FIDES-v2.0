# Tiền vào bất thường, luật đi qua, và mục đích đầu tư

Ngưỡng nằm trong `engine/policy/bank_policy.yaml`, mục `inflow_*` và `recurring_*`. Mỗi ngưỡng ghi nguồn `v2.5 funds inflows`.

Sổ 72 giờ của chính khách được so với mức thường. Mức thường là trung vị các khoảng 72 giờ trong `inflow_history_days` ngày ngay trước cửa sổ hiện tại. Khoảng không có tiền vào tính là 0. Không có lịch sử thì mức thường là 0, và sàn `inflow_min_vnd` (10 triệu) là điều kiện tiền.

- `p2p_inflow`: chuyển đến từ ít nhất hai người, hoặc từ một người chưa từng chuyển tới, tổng 72 giờ ≥ 5 lần mức thường và ≥ 10 triệu.
- `lender_inflow`: giải ngân từ bên cho vay hoặc công ty tài chính, không phải sản phẩm của chính ngân hàng này. Tên người gửi khớp `lender_markers`.
- `cash_deposit`: một lần nộp tiền mặt ≥ 5 lần mức nộp thường và ≥ 10 triệu.
- `own_transfer_in`: tiền từ tài khoản của chính khách ở ngân hàng khác. Chuyển giữa các tài khoản cùng khách tại BVC không tính.

Lương và lương hưu không tính là tiền vào bất thường: cùng người gửi, cách nhau khoảng một tháng (sai số `recurring_gap_slack_days`), số tiền trong khoảng `recurring_amount_within`. `salary_in` luôn bị loại.

`funds_mobilised` gồm sự kiện sản phẩm cũ và bốn loại trên. Thẻ bằng chứng ghi `kind`, `amount`, `channel`, `at` cho từng khoản.

`R_FUNDS_PASSTHROUGH` (mức 2, nhóm A, không cần cuộc gọi) khớp khi có một loại tiền vào đó, người nhận mới là tài khoản cá nhân, và lệnh này cộng các khoản đi từ lúc nhận đã dùng ít nhất 70% khoản vào, đồng thời `habit_money_rare`.

Mục đích `investment` chỉ thành `purpose_high_risk` khi người nhận mới và là tài khoản cá nhân. Cùng ngân hàng: `account_type` của bank-core; `business`, `securities`, `merchant` không phải cá nhân. Liên ngân hàng không có loại tài khoản: tên đã bỏ dấu mà chứa `CONG TY`, `CTCP`, `TNHH` hoặc `QUY`, hoặc nằm trong `verified_companies`, được coi là tổ chức. Tên cá nhân không có các cụm đó được coi là tài khoản cá nhân. Đây là giả định vì liên ngân hàng không trả loại tài khoản.

Mọi quyết định mức 2 mở một episode 24 giờ. Episode đó nâng mức của lần chuyển sau tới người nhận mới, không chỉ khi có dấu hiệu bị hướng dẫn. Người nhận đã lưu không bị nâng theo episode đó.
