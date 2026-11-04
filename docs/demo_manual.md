# Chạy demo v2.5 trên iPhone

Cuộc gọi là cuộc gọi thật. App nghe trạng thái cuộc gọi và mở lại nút “Tiếp tục” khi máy đã cúp. Mục “Demo: kết thúc cuộc gọi” chỉ tắt cuộc gọi giả lập, không cúp cuộc gọi thật.

Không AirPlay, không ghi màn hình, không chiếu màn hình, trừ khi một nhịp bên dưới nói rõ. iOS gộp cả ba vào `UIScreen.isCaptured`. App gửi trạng thái đó là `active_capture`, và mọi lệnh chuyển trở thành mức 2 với `R_CAPTURE`.

## Máy và cổng

Điện thoại không gọi engine. Nó gọi bank-core. Engine nghe `127.0.0.1:8091`. Bank-core nghe `127.0.0.1:8092` và tự gọi engine.

Trong `bank-app/.env`, `EXPO_PUBLIC_BANK_URL` đang là `http://10.0.2.2:8082`. Trên iPhone, app đổi `10.0.2.2` thành máy chạy Metro và giữ nguyên cổng, nên điện thoại sẽ gọi cổng 8082. Demo này không nghe cổng đó. Sửa thành `http://<IP mạng của Mac>:8092`, rồi mở lại Metro.

Trước khi mở app:

```sh
curl -sf -o /dev/null -w "engine %{http_code}\n" http://127.0.0.1:8091/health
curl -sf -o /dev/null -w "bank %{http_code}\n" http://127.0.0.1:8092/health
```

Cả hai phải là 200. `scripts/demo_reset.sh` chạy từ thư mục SEDIF. Nó gắn giờ máy lên ngày 21/9/2026 và xoá episode. Gọi nó đúng chỗ ghi trong thứ tự, không gọi giữa các nhịp của cùng một cảnh.

Nút khiên trên tiêu đề (nhãn “Phiên FIDES”) mở menu demo.

App tự chọn tài khoản cá nhân số dư cao nhất của khách. Số gõ trên bàn phím là số hiển thị, nhóm ba chữ số.

## Thứ tự

1. Hoàng, chuyển thường cho Võ Tiến Hà.
2. Lê, quét QR trong lúc đang gọi.
3. Huỳnh, cảnh F, mục đích cơ quan nhà nước, khi sổ còn đóng. Kết bằng “Demo: tổng đài xác nhận lừa đảo”.
4. `scripts/demo_reset.sh`.
5. Huỳnh, cảnh B.
6. Hoàng, cảnh D, màn hình bị ghi.
7. Hoàng, cảnh E, tài khoản đường dây.
8. Trương, cảnh C, phiên có hướng dẫn.
9. Tuỳ chọn: G rồi H, mỗi cảnh sau một lần `demo_reset.sh`.

### 1. Hoàng Văn Tâm, chuyển thường

Khách Hoàng Văn Tâm. Tài khoản nguồn A0051289, số hiển thị 1903 051 289, số dư khoảng 427 triệu.

Người nhận đã lưu: Võ Tiến Hà, A0022775, gõ `1903022775`. Số tiền 500.000. Không gọi. Không bật công tắc demo. Dưới 10 triệu nên không hỏi mục đích.

Màn hình: “Chuyển tiền thành công”. Không có nút tạm dừng. Không cần menu demo. Chưa cần reset.

### 2. Lê Kim Trân, QR trong cuộc gọi

Gọi điện thật và giữ máy trước khi mở app. Khách Lê Kim Trân. Nguồn A0031239, số hiển thị 1903 031 239.

Ở màn người nhận, bấm nút quét QR (nhãn “Quét mã QR cửa hàng”). App điền Công ty TNHH Thành Công, A0119434, số hiển thị 0901 119 434. Số tiền 60.000. Không bật công tắc demo.

Màn hình mức 1. Câu: “Bạn đang nghe điện thoại và chuyển cho người nhận mới. Nếu có ai đang hướng dẫn bạn chuyển tiền, hãy dừng lại.” Nút “Tiếp tục chuyển” và “Huỷ” đều bấm được. Bấm “Huỷ”. Cúp máy sau nhịp này.

### 3. Huỳnh Thị Mận, cảnh F, trước khi đóng sổ

Vẫn để sổ tiết kiệm đóng. Khách Huỳnh Thị Mận. Nguồn A0072556, số hiển thị 1903 072 556, số dư khoảng 29,1 triệu. Sổ A0077690, 150 triệu, chưa đụng tới.

Gọi điện thật và giữ máy. Người nhận mới: Lý Minh Châu, gõ `0902230230`. Số tiền 23.000.000. App hỏi mục đích vì trên 10 triệu. Chọn “Cơ quan nhà nước / công an yêu cầu chuyển”.

Màn hình mức 2, được tăng cường (hai nhóm: mục đích và cuộc gọi kèm thói quen). Câu lớn: “Cơ quan nhà nước không bao giờ yêu cầu chuyển tiền để xác minh.” Dòng khoá: “Giao dịch có nhiều dấu hiệu lừa đảo. Gọi tổng đài để xác nhận ngay, hoặc nhờ người giám hộ xác nhận.” “Tiếp tục” bị khoá và đếm ngược. “Cúp máy” cũng chưa đủ để mở nút đó, vì đây là mức tăng cường. Có thêm “Nhờ người giám hộ xác nhận”, “Tạm dừng để xác minh”, “Huỷ”, “Gọi tổng đài ngân hàng”.

Mở menu demo và bấm “Demo: tổng đài xác nhận lừa đảo”. Màn hình: “Tổng đài đã xác nhận đây là lừa đảo. Giao dịch đã được huỷ.”

Cúp máy. Chạy `scripts/demo_reset.sh` trước cảnh sau. Cảnh F vừa mở episode; nếu không reset, cảnh B bị sàn mức 2 từ episode đó.

### 4. Huỳnh Thị Mận, cảnh B

Sau reset. Cùng khách, cùng tài khoản thanh toán, sổ vẫn đóng.

Không gọi. Người nhận mới: Phạm Thu Ngân, gõ `0902101002`. Số tiền 120.000.000. App từ chối trước khi chấm: “không đủ số dư”.

Về trang chủ, bấm “Tiền gửi”, mở sổ, bấm “Tất toán trước hạn”. Màn hình: tiền sổ 150 triệu về tài khoản thanh toán. Số dư thanh toán đủ 120 triệu.

Gọi điện thật và giữ máy. Gửi lại 120.000.000 cho Phạm Thu Ngân. Mục đích “Mua hàng, dịch vụ” (không phải cơ quan nhà nước).

Màn hình mức 2, một nhóm, chưa tăng cường. Câu lớn: “Bạn vừa rút tiền tiết kiệm hoặc nhận tiền và đang chuyển cho người lạ trong lúc nghe điện thoại. Đây là cách kẻ giả danh công an thường lừa tiền.” “Tiếp tục” bị khoá với câu “Hãy cúp máy trước. Công an, ngân hàng và cơ quan nhà nước không bao giờ yêu cầu chuyển tiền qua điện thoại.” “Tạm dừng để xác minh”, “Huỷ” và “Gọi tổng đài ngân hàng” bấm được. Huỳnh có giám hộ nên có “Nhờ người giám hộ xác nhận”.

Cúp máy thật. Quay lại app. “Tiếp tục” hết khoá. Không bấm “Tiếp tục”. Bấm “Huỷ”. Episode của lệnh 120 triệu vẫn còn.

Không reset. Gửi 40.000.000 cho Mai Phương Thảo, gõ `0902102002`, không gọi, mục đích “Khác”. Màn hình vẫn mức 2. Câu lớn: “Bạn vừa có một giao dịch bị tạm dừng vì dấu hiệu lừa đảo. Các giao dịch tiếp theo cũng được kiểm tra kỹ.” “Tiếp tục” bấm được vì không còn cuộc gọi và lệnh này không tăng cường. Bấm “Huỷ”.

### 5. Hoàng Văn Tâm, cảnh D

Reset không bắt buộc nếu Hoàng chưa bị episode. Nếu vừa chạy cảnh khác của Hoàng thì chạy `scripts/demo_reset.sh`.

Khách Hoàng, nguồn A0051289. Không gọi. Mở menu demo và bật “Demo: màn hình đang bị ghi”. Đừng dùng AirPlay để tạo nhịp này: AirPlay giữ `isCaptured` cho đến khi ngắt chiếu, và nhịp sau cũng bị mức 2.

Người nhận mới: Đặng Quốc Bảo, gõ `0902401001`. Số tiền 500.000. Không hỏi mục đích.

Màn hình mức 2. Câu: “Màn hình của bạn đang bị ghi hoặc chia sẻ. Kẻ lừa đảo thường yêu cầu chia sẻ màn hình để hướng dẫn.” Không tăng cường. “Tiếp tục” bấm được. Bấm “Huỷ”. Mở menu và tắt “Demo: màn hình đang bị ghi”.

### 6. Hoàng Văn Tâm, cảnh E

Cùng khách, ngay sau D, công tắc ghi đã tắt. Không gọi. Không reset: D là mức 2 nhưng người nhận đường dây không cần episode để lên mức 3. Nếu muốn sổ sạch, chạy `scripts/demo_reset.sh` rồi làm lại từ khách Hoàng.

Người nhận: Trịnh Văn Khôi, gõ `0902003001`. Số tiền 500.000.

Màn hình mức 3. Tiêu đề: “Giao dịch đang được ngân hàng xem xét.” Câu lớn: “Tài khoản nhận đã được xác nhận là tài khoản lừa đảo. Ngân hàng đang giữ giao dịch để bảo vệ bạn.” Lý do: “Ngân hàng đã xác nhận tài khoản nhận nằm trong hồ sơ đường dây.” Dòng nhỏ: “Mô phỏng chính sách tạm giữ 24 giờ của ngân hàng.” Chỉ có “Về trang chủ”.

### 7. Trương Gia Thịnh, cảnh C

Chạy `scripts/demo_reset.sh` nếu Hoàng vừa bị mức 2 hoặc 3 và bạn không chắc episode. Trương là khách khác nên episode của Hoàng không đụng anh. Reset vẫn an toàn và là cách đã dùng khi chấm API.

Khách Trương Gia Thịnh. Nguồn A0002119, số hiển thị 1903 002 119. Gọi điện thật và giữ máy. Mở menu và bật “Demo: phiên có hướng dẫn”. Công tắc này thay bản ghi thời gian trên máy bằng một mẫu đọc số (vài cụm 2–4 chữ số). Gõ thật một dãy liền không tạo mẫu đó.

Người nhận mới: Ngô Thanh Hà, gõ `0902402001`. Số tiền 500.000. Không hỏi mục đích.

Màn hình mức 2. Câu lớn: “Cách bạn thao tác giống như đang được người khác đọc cho từng bước.” Một lý do: “Bạn nhập số tài khoản theo từng cụm, như đang được đọc cho.” “Tiếp tục” bị khoá cho đến khi cúp máy. Bấm “Huỷ”, cúp máy, tắt công tắc hướng dẫn.

### 8. Tuỳ chọn: cảnh G và H

Điện thoại không tự nhận bốn khoản vay. Sau mỗi `scripts/demo_reset.sh`, ghi bốn khoản 25 triệu vào A0072556 từ bốn người khác nhau, mốc trong vòng một giờ trước đồng hồ demo. Rồi mới cầm máy.

Cảnh G. Khách Huỳnh, nguồn A0072556. Gọi điện thật. Người nhận mới: Bùi Hải Yến, gõ `0902004001`. Số tiền 100.000.000. Mục đích “Khác”.

Màn hình mức 2, một nhóm, chưa tăng cường. Câu lớn: “Bạn vừa rút tiền tiết kiệm hoặc nhận tiền và đang chuyển cho người lạ trong lúc nghe điện thoại. Đây là cách kẻ giả danh công an thường lừa tiền.” Luật tiền đi qua cũng khớp, cùng nhóm với luật cuộc gọi, nên không thành mức tăng cường. “Tiếp tục” bị khoá cho đến khi cúp máy. Bấm “Huỷ”.

`scripts/demo_reset.sh`, ghi lại bốn khoản 25 triệu.

Cảnh H. Cùng khách, cùng số tiền, cùng người nhận, không gọi. Màn hình mức 2. Câu lớn: “Bạn vừa nhận tiền từ nhiều nơi và đang chuyển gần hết cho người lạ. Kẻ lừa đảo thường bảo nạn nhân vay mượn rồi chuyển tiền đi.” Không có câu cúp máy. “Tiếp tục” bấm được nếu chỉ một nhóm. Bấm “Huỷ”.

## Khác với đề xuất v2.5

Luật phát hiện đã chốt trong các đợt 1–3 khớp code. Những chỗ còn khác:

- Điểm gian lận vẫn là mô hình LightGBM đóng gói từ trước v2.5. Đợt này thêm luật, không huấn luyện lại mô hình.
- Hai ngưỡng 5% của thao tác (`behaviour_p_rarity_at_most`, `behaviour_guided_p_at_most`) và file `engine/artifacts/behaviour_ref` là phân phối tổng hợp, đánh `demo: true`. Chưa có quần thể người dùng thật.
- Android không gửi hướng cuộc gọi và không đọc ghi màn hình. Tín hiệu đó là unknown. Luật không coi unknown là vắng.
- iOS coi AirPlay, ghi màn hình và chiếu màn hình là cùng một `active_capture`.
- Người nhận không có loại tài khoản và không có tên bị coi là cá nhân. Luật đi qua và mục đích đầu tư vẫn có thể khớp với một tài khoản liên ngân hàng chưa có tên.
- Công tắc “Demo: phiên có hướng dẫn” thay số liệu trên máy bằng vector cố định. Tắt công tắc thì máy chấm đúng nhịp gõ.
- TreeSHAP của thói quen chỉ chạy khi `habit_rare` đã đúng.
- `/decide` quá 300 ms thành unscored, không bao giờ mức 0.
- Bản mô phỏng chính sách không có nhịp gõ. Nó rút `behaviour_rare` và `behaviour_guided` theo tỷ lệ tổng hợp ở 10 phiên nền. Phần 70% của luật đi qua trong bản mô phỏng chỉ tính lệnh hiện tại, không cộng các khoản đi trước đó trong 72 giờ.
