# Demo cuối: năm cảnh

Một lần `scripts/demo_reset.sh` trước cảnh 1. Không reset giữa các cảnh. Cảnh 3 mở episode 24 giờ. Cảnh 4 đi tiếp trên episode đó và vẫn là mức 2 tăng cường, vì lệnh đó tự khớp nhóm A và nhóm C.

Cuộc gọi là cuộc gọi thật, từ một máy khác. App nghe trạng thái cuộc gọi. “Demo: kết thúc cuộc gọi” chỉ tắt cuộc gọi giả lập.

Không AirPlay, không ghi màn hình, không chiếu màn hình. iOS gộp cả ba vào `UIScreen.isCaptured`. Mọi lệnh lúc đó thành mức 2 với `R_CAPTURE`.

Đổi khách: tab Cá nhân, “Đổi tài khoản demo”. App tự chọn tài khoản thanh toán số dư cao nhất. Số gõ trên bàn phím là số hiển thị, không có khoảng trắng.

## Trước khi mở app

- Máy gọi đã sẵn. Cảnh 2, cảnh 3 (lệnh 120 triệu) và cảnh 4 dùng cuộc gọi thật. Cảnh 4 giữ máy cho đến khi đã thấy nút Tiếp tục vẫn bị khoá. Cảnh 5 gọi lại.
- Engine và bank đều trả 200:

```sh
curl -sf -o /dev/null -w "engine %{http_code}\n" http://127.0.0.1:8091/health
curl -sf -o /dev/null -w "bank %{http_code}\n" http://127.0.0.1:8092/health
```

- Điện thoại và Mac cùng Wi‑Fi. App gọi bank-core tại `EXPO_PUBLIC_BANK_URL` trong `bank-app/.env` (hiện `http://192.168.50.146:8092`). Điện thoại không gọi engine. Engine nghe `127.0.0.1:8091`. Bank nghe cổng 8092 và tự gọi engine. Đổi IP thì sửa `.env` rồi mở lại Metro.
- QR cửa hàng in sẵn để giơ lên: Công ty TNHH Thành Công, số `0901119434`. Nút QR trong app điền đúng cửa hàng đó. App không đọc camera.
- Không AirPlay, không ghi, không chiếu.
- Từ thư mục SEDIF, một lần:

```sh
sh scripts/demo_reset.sh
```

Đợi dòng `ready`. Không gọi lại script này cho đến khi năm cảnh xong.

Nút khiên trên tiêu đề, hoặc dòng “Phiên FIDES”, mở menu demo.

## 1. Hoàng Văn Tâm, mức 0

Khách Hoàng Văn Tâm. Nguồn hiện `1903 051 289`. Không gọi. Không bật công tắc demo.

Ở “Người nhận đã lưu”, bấm Võ Tiến Hà. Dòng đó hiện `1903 022 775`. Đừng gõ số vào ô tài khoản mới: gõ số là lệnh người nhận mới. Số tiền `500000`. Dưới 10 triệu và người nhận đã lưu nên không hỏi mục đích.

Màn hình: “Chuyển tiền thành công”. Không có “Tạm dừng để xác minh”.

Nói: “Người nhận đã lưu, không có cuộc gọi. Ngân hàng để lệnh đi.”

## 2. Lê Kim Trân, tờ mức 1

Đổi sang Lê Kim Trân. Nguồn hiện `1903 031 239`. Gọi thật và giữ máy trước khi xác nhận.

Chuyển tiền, bấm nút quét QR (nhãn “Quét mã QR cửa hàng”). App điền Công ty TNHH Thành Công, `0901 119 434`. Số tiền `60000`. Người nhận mới nên app hỏi mục đích. Chọn “Mua hàng, dịch vụ”. Không chọn cơ quan nhà nước.

Tờ mức 1 hiện trên màn xác nhận. Câu lớn: “Bạn đang nghe điện thoại và chuyển cho người nhận mới. Nếu có ai đang hướng dẫn bạn chuyển tiền, hãy dừng lại.” “Tiếp tục chuyển” và “Huỷ” đều bấm được. Bấm “Huỷ”. Cúp máy.

Nói: “Có cuộc gọi và người nhận mới. Đây chỉ là lời nhắc. Khách vẫn tự quyết.”

## 3. Huỳnh Thị Mận, mức 2 nhóm A

Đổi sang Huỳnh Thị Mận. Nguồn hiện `1903 072 556`, số dư khoảng 29 triệu. Sổ tiết kiệm khoảng 150 triệu, chưa đụng. Không gọi ở nhịp đầu.

Người nhận mới: Phạm Thu Ngân, gõ `0902101002`. Số tiền `120000000`. Mục đích “Mua hàng, dịch vụ”. App từ chối trước khi chấm: “không đủ số dư”.

Về trang chủ, bấm “Tiền gửi”, bấm “Tất toán trước hạn”. Màn hình: 150 triệu về tài khoản thanh toán.

Gọi thật và giữ máy. Gửi lại `120000000` cho Phạm Thu Ngân, cùng mục đích “Mua hàng, dịch vụ”.

Màn hình mức 2, một nhóm, chưa tăng cường. Luật: `R_CALL_FUNDS_NEWPAYEE`, `R_HABIT_NEWPAYEE`, `R_CALL_HABIT_NEWPAYEE`. Nhóm A. Câu lớn: “Bạn vừa rút tiền tiết kiệm hoặc nhận tiền và đang chuyển cho người lạ trong lúc nghe điện thoại. Đây là cách kẻ giả danh công an thường lừa tiền.” Dòng khoá: “Hãy cúp máy trước. Công an, ngân hàng và cơ quan nhà nước không bao giờ yêu cầu chuyển tiền qua điện thoại.” “Tiếp tục” bị khoá. “Tạm dừng để xác minh”, “Huỷ”, “Gọi tổng đài ngân hàng” bấm được. Huỳnh có giám hộ nên có “Nhờ người giám hộ xác nhận”.

Bấm “Tạm dừng để xác minh”. Màn hình: “Lệnh đang được giữ lại để bạn tự kiểm tra.” và số tổng đài. Bấm “Về trang chủ”. Giữ cuộc gọi. Episode của lệnh này còn đến hết cảnh sau.

Nói: “Vừa tất toán sổ và chuyển cho người lạ trong lúc nghe máy. Một nhóm dấu hiệu. Cúp máy thì mới được tiếp tục. Khách chọn tạm dừng, tiền vẫn bị giữ.”

## 4. Huỳnh Thị Mận, mức 2 tăng cường

Cùng khách, cùng cuộc gọi, chưa cúp. Không reset.

Người nhận mới: Mai Phương Thảo, gõ `0902102002`. Số tiền `40000000`. Mục đích “Cơ quan nhà nước / công an yêu cầu chuyển”.

Màn hình mức 2, tăng cường. Luật: `R_CALL_FUNDS_NEWPAYEE`, `R_PURPOSE_HIGH_RISK`, `R_HABIT_NEWPAYEE`, `R_CALL_HABIT_NEWPAYEE`. Nhóm A và C. Câu lớn vẫn là câu cuộc gọi và sổ tiết kiệm, vì luật đó đứng trước: “Bạn vừa rút tiền tiết kiệm hoặc nhận tiền và đang chuyển cho người lạ trong lúc nghe điện thoại. Đây là cách kẻ giả danh công an thường lừa tiền.” Mục đích cơ quan nhà nước là nhóm thứ hai. Nó không đổi câu lớn. Nó làm lệnh thành tăng cường.

Hai dòng khoá. Dòng cúp máy, và dòng: “Giao dịch có nhiều dấu hiệu lừa đảo. Gọi tổng đài để xác nhận ngay, hoặc nhờ người giám hộ xác nhận.” “Tiếp tục” hiện đếm ngược, dạng “Có thể tiếp tục sau …”, và bị khoá. Có “Nhờ người giám hộ xác nhận”.

Cúp máy thật. Quay lại app. Dòng cúp máy mất. Đếm ngược còn. “Tiếp tục” vẫn không bấm được. Nếu lệnh được gửi đi, máy chủ trả “Chưa hết thời gian giữ để xác minh.”

Mở menu demo, bấm “Demo: tổng đài xác nhận lừa đảo”. Màn hình: “Tổng đài đã xác nhận đây là lừa đảo. Giao dịch đã được huỷ.” Tiền 40 triệu được hoàn về tài khoản. Lệnh 120 triệu ở cảnh 3 vẫn đang giữ.

Nói: “Cùng cuộc gọi, thêm mục đích cơ quan nhà nước. Hai nhóm. Cúp máy không mở nút. Chỉ tổng đài xác nhận lừa đảo thì lệnh bị huỷ và tiền được trả lại.”

## 5. Trương Gia Thịnh, mức 2 được đọc số

Đổi sang Trương Gia Thịnh. Nguồn hiện `1903 002 119`. Gọi thật và giữ máy. Mở menu demo, bật “Demo: phiên có hướng dẫn”. Công tắc này thay nhịp gõ bằng mẫu được đọc từng cụm. Gõ một dãy liền không tạo mẫu đó.

Người nhận mới: Ngô Thanh Hà, gõ `0902402001`. Số tiền `500000`. Chọn mục đích “Khác”. Không chọn cơ quan nhà nước.

Màn hình mức 2, một nhóm. Luật `R_BEHAVIOUR_GUIDED`, nhóm B. Câu lớn: “Cách bạn thao tác giống như đang được người khác đọc cho từng bước.” Một lý do: “Bạn nhập số tài khoản theo từng cụm, như đang được đọc cho.” “Tiếp tục” bị khoá cho đến khi cúp máy. Bấm “Huỷ”. Cúp máy. Tắt “Demo: phiên có hướng dẫn”.

Nói: “Số tài khoản được đọc từng cụm trong lúc nghe máy. Ngân hàng nhận ra cách nhập, không cần số tiền lớn.”

## Slide dự phòng

Không nằm trong năm cảnh trên.

- `docs/screens/level-2-capture.png`: mức 2 vì màn hình đang bị ghi. Hoàng, `0902401001`, 500.000 đ. Câu: “Màn hình của bạn đang bị ghi hoặc chia sẻ. Kẻ lừa đảo thường yêu cầu chia sẻ màn hình để hướng dẫn.”
- `docs/screens/level-3-mule.png`: mức 3, tài khoản đường dây. Hoàng, `0902003001`, 500.000 đ. Tiêu đề: “Giao dịch đang được ngân hàng xem xét.” Câu lớn: “Tài khoản nhận đã được xác nhận là tài khoản lừa đảo. Ngân hàng đang giữ giao dịch để bảo vệ bạn.” Chỉ có “Về trang chủ”.
