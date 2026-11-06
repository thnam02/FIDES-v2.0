# Demo cuối: năm cảnh

Một lần `scripts/demo_reset.sh` trước cảnh 1. Không reset giữa các cảnh. Thứ tự cố định: Hoàng, Lê, Huỳnh (hai cảnh liền), Trương.

Cảnh 3 mở episode 24 giờ cho Huỳnh. Cảnh 4 đi trên cùng episode đó. Cảnh 4 là mức 2 tăng cường vì chính lệnh đó khớp hai nhóm, A và C. Nó không dựa vào việc cảnh 3 chạy trước.

Cuộc gọi là cuộc gọi thật, từ một máy khác. App nghe trạng thái cuộc gọi. “Demo: kết thúc cuộc gọi” chỉ tắt cuộc gọi giả lập.

Đổi khách: tab Cá nhân, “Đổi tài khoản demo”. App tự chọn tài khoản thanh toán số dư cao nhất. Số gõ trên bàn phím là số hiển thị, liền, không khoảng trắng.

Nút khiên trên tiêu đề, hoặc dòng “Phiên FIDES”, mở menu demo.

Câu lớn mức 2 lấy theo nhóm: C (mục đích) trước B (thao tác khi nghe máy), rồi A (dòng tiền), rồi D (người nhận). Màn mức 2 và tờ mức 1 hiện câu lớn và tối đa hai dòng lý do. Dòng nào câu lớn đã nói thì không hiện lại. Hai dòng hiện là hai dòng cụ thể nhất còn lại, theo thứ tự mục đích, thao tác, cuộc gọi, dòng tiền, thói quen, người nhận. Mọi dòng khác, kể cả dòng câu lớn đã nói, nằm sau “Xem chi tiết”, đóng sẵn.

## Trước khi mở app

Máy Mac mới: làm theo `docs/SETUP.md` trước, rồi chạy `sh scripts/setup_check.sh`.

- Từ thư mục SEDIF, bật engine và bank. Script kiểm tra Postgres và Redis trước. Redis tắt thì tự bật `redis-server`. Postgres không trả lời thì dừng và in lệnh sửa (`brew services restart postgresql@16`). Không bật Postgres của docker compose, vì cơ sở đó không có `fides_w1`. Sau đó script dừng tiến trình đang giữ cổng 8091 và 8092, bật lại tách khỏi terminal, ghi log vào `logs/engine.log` và `logs/bank.log`, đợi health, chấm thử một lệnh rồi in `ready`. Đóng editor hay terminal không tắt hai server.

```sh
sh scripts/demo_up.sh
```

- Mở một terminal khác và giữ chạy suốt buổi demo, để Mac không ngủ. Ctrl+C sau demo.

```sh
caffeinate -d
```

- Máy gọi đã sẵn, có số của điện thoại demo. Gọi thật ở cảnh 2, cảnh 3 (lệnh 120 triệu sau tất toán), cảnh 4 và cảnh 5. Từ cảnh 3 sang cảnh 4 không cúp máy.
- Engine cổng 8091 và bank cổng 8092 đều trả 200:

```sh
curl -sf -o /dev/null -w "engine %{http_code}\n" http://127.0.0.1:8091/health
curl -sf -o /dev/null -w "bank %{http_code}\n" http://127.0.0.1:8092/health
```

- Điện thoại và Mac cùng Wi‑Fi. App gọi bank-core tại `EXPO_PUBLIC_BANK_URL` trong `bank-app/.env` (hiện `http://192.168.50.146:8092`). Điện thoại không gọi engine. Engine nghe `127.0.0.1:8091`, bank nghe cổng 8092 và tự gọi engine. Đổi IP thì sửa `.env` rồi mở lại Metro.
- QR cửa hàng in sẵn để giơ lên: Công ty TNHH Thành Công, `0901 119 434`. Nút QR trong app điền đúng cửa hàng đó. App không đọc camera.
- Không AirPlay, không ghi màn hình, không chiếu màn hình. iOS gộp cả ba vào `UIScreen.isCaptured`. Khi đó mọi lệnh thành mức 2 với `R_CAPTURE`, và năm cảnh dưới đây sai hết.
- Sau `demo_up.sh`, từ thư mục SEDIF, đúng một lần:

```sh
sh scripts/demo_reset.sh
```

Script chạy khoảng 5 phút. Đợi dòng `ready`. Không gọi lại cho đến khi xong năm cảnh.

Sau demo, dừng engine và bank theo pid trong `logs/`. Postgres và Redis trên máy vẫn chạy.

```sh
sh scripts/demo_down.sh
```

## 1. Hoàng Văn Tâm, mức 0

Khách Hoàng Văn Tâm. Nguồn hiện `1903 051 289`. Không gọi. Không bật công tắc demo nào.

Chuyển tiền. Ở “Người nhận đã lưu”, bấm Võ Tiến Hà, dòng hiện `1903 022 775`. Không gõ số vào ô tài khoản mới, vì gõ số là lệnh người nhận mới. Số tiền `500000`. Người nhận đã lưu và dưới 10 triệu nên app không hỏi mục đích. Xác nhận.

Màn hình: “Chuyển tiền thành công”, 500.000 đ. Không có màn hình cảnh báo. Nút duy nhất: “Về trang chủ”.

Nói: “Người nhận đã lưu, không có cuộc gọi. Ngân hàng để lệnh đi, không làm phiền khách.”

## 2. Lê Kim Trân, tờ mức 1

Đổi sang Lê Kim Trân. Nguồn hiện `1903 031 239`. Gọi thật và giữ máy trước khi xác nhận.

Chuyển tiền. Giơ QR in sẵn, bấm nút quét QR cạnh ô tài khoản (nhãn “Quét mã QR cửa hàng”). App điền Công ty TNHH Thành Công, `0901 119 434`. Số tiền `60000`. Người nhận mới nên app hỏi mục đích: chọn “Mua hàng, dịch vụ”. Xác nhận.

Tờ mức 1 hiện ngay trên màn xác nhận. Câu lớn: “Bạn đang nghe điện thoại và chuyển cho người nhận mới. Nếu có ai đang hướng dẫn bạn chuyển tiền, hãy dừng lại.” Không có dòng lý do nào mở sẵn: dòng duy nhất, “Bạn đang trong cuộc gọi và chuyển tiền cho người nhận mới.”, nói lại câu lớn nên nằm sau “Xem chi tiết”. Hai nút đều bấm được: “Tiếp tục chuyển” và “Huỷ”. Bấm “Huỷ”. Cúp máy.

Nói: “Có cuộc gọi và người nhận mới. Đây chỉ là lời nhắc. Khách vẫn tự quyết.”

## 3. Huỳnh Thị Mận, mức 2 nhóm A

Đổi sang Huỳnh Thị Mận. Nguồn hiện `1903 072 556`, số dư khoảng 29,1 triệu. Có một sổ tiết kiệm 150 triệu, chưa đụng.

Nhịp đầu, chưa cần gọi. Chuyển tiền, gõ `0902101002` (Phạm Thu Ngân). Số tiền `120000000`. Mục đích “Mua hàng, dịch vụ”. Xác nhận. Ngân hàng từ chối trước khi chấm: “không đủ số dư”.

Về trang chủ. Trên thẻ số dư bấm “Tiền gửi” (hoặc ô “Tiết kiệm”). Bấm “Tất toán trước hạn”, rồi bấm “Tất toán trước hạn” lần nữa ở màn sổ. Màn hình: “Đã chuyển 150.000.000 đ về tài khoản thanh toán”, nút “Về trang chủ”. Số dư thành khoảng 179,1 triệu.

Gọi thật và giữ máy. Gửi lại: gõ `0902101002`, `120000000`, mục đích “Mua hàng, dịch vụ”. Xác nhận.

Màn hình mức 2, một nhóm, chưa tăng cường. Câu lớn: “Bạn vừa rút tiền tiết kiệm hoặc nhận tiền và đang chuyển cho người lạ trong lúc nghe điện thoại. Đây là cách kẻ giả danh công an thường lừa tiền.” Câu lớn đã nói cuộc gọi, tiền tiết kiệm và người lạ, nên hai dòng lý do là: “Bạn đang chuyển gần hết số dư.” và “Số tiền lớn gấp nhiều lần mức bạn thường chuyển.” “Xem chi tiết” mở ba dòng câu lớn đã nói: cuộc gọi đang diễn ra, sổ tiết kiệm vừa tất toán, chưa từng chuyển tới người nhận này. Dòng khoá: “Hãy cúp máy trước. Công an, ngân hàng và cơ quan nhà nước không bao giờ yêu cầu chuyển tiền qua điện thoại.”

Nút, từ trên xuống: “Gọi tổng đài ngân hàng”, “Tạm dừng để xác minh”, “Gửi yêu cầu cho người giám hộ”, “Huỷ”, “Tiếp tục”. “Tiếp tục” bị khoá vì máy còn gọi. Người giám hộ của bà Mận được `demo_reset.sh` lưu sẵn, đã đồng ý từ trước. Nút giám hộ chỉ gửi yêu cầu, không nhả tiền; chỉ người giám hộ xác nhận trên máy của họ mới nhả. Không bấm nút này trong cảnh 3.

Bấm “Tạm dừng để xác minh”. Màn hình: “Lệnh đang được giữ lại để bạn tự kiểm tra.” và số tổng đài `1900 54 54 13`. 120 triệu vẫn bị giữ. Bấm “Về trang chủ”. Không cúp máy.

Sau khi tạm dừng, lệnh nằm trong Tra cứu giao dịch, lọc “Đang giữ”. Bấm dòng đó để mở lại cùng màn mức 2 (câu lớn, lý do, dòng cúp máy, đếm ngược nếu có). Từ đó khách gọi tổng đài, gửi giám hộ, huỷ (hoàn tiền), hoặc tiếp tục khi đã cúp máy — và, nếu tăng cường, sau khoá 30 phút hoặc tổng đài mở khoá. Máy chủ vẫn chặn Tiếp tục qua `block_proceed`. Lệnh mức 3 không bấm được: “Ngân hàng đang xem xét”.

Nói: “Vừa tất toán sổ, rồi chuyển cho người lạ trong lúc nghe máy. Đó là một nhóm dấu hiệu. Phải cúp máy mới được tiếp tục. Khách chọn tạm dừng, tiền vẫn nằm ở ngân hàng.”

## 4. Huỳnh Thị Mận, mức 2 tăng cường

Cùng khách, cùng cuộc gọi, chưa cúp. Không reset.

Chuyển tiền, gõ `0902102002` (Mai Phương Thảo). Số tiền `40000000`. Mục đích “Cơ quan nhà nước / công an yêu cầu chuyển”. Xác nhận.

Màn hình mức 2, tăng cường. Lệnh khớp nhóm A (cuộc gọi, sổ tiết kiệm) và nhóm C (mục đích). Nhóm C đứng trước nên câu lớn là: “Cơ quan nhà nước không bao giờ yêu cầu chuyển tiền để xác minh.” Ngay dưới là dòng tăng cường: “Có nhiều dấu hiệu lừa đảo cùng lúc, nên giao dịch được giữ thêm 30 phút.”

Câu lớn đã nói mục đích, nên hai dòng lý do là: “Có cuộc gọi đang diễn ra trong phiên này.” và “Sổ tiết kiệm vừa được tất toán.” “Xem chi tiết” mở thêm bốn dòng: chuyển gần hết số dư, số tiền lớn gấp nhiều lần thường lệ, chưa từng chuyển tới người nhận này, và dòng mục đích.

Hai dòng khoá: dòng cúp máy, và “Giao dịch có nhiều dấu hiệu lừa đảo. Gọi tổng đài để xác nhận ngay, hoặc nhờ người giám hộ xác nhận.” Nút giống cảnh 3, có cả “Gửi yêu cầu cho người giám hộ”. “Tiếp tục” đổi thành đếm ngược “Có thể tiếp tục sau …” (khoá 30 phút) và không bấm được.

Cúp máy thật. Quay lại app. Dòng cúp máy mất. Dòng tăng cường và đếm ngược còn. “Tiếp tục” vẫn khoá. Nếu lệnh tiếp tục được gửi, máy chủ trả “Chưa hết thời gian giữ để xác minh.”

Mở menu demo, bấm “Demo: tổng đài xác nhận lừa đảo”. Màn hình: “Tổng đài đã xác nhận đây là lừa đảo. Giao dịch đã được huỷ.” và “Về trang chủ”. 40 triệu về lại tài khoản (số dư từ khoảng 19,1 lên 59,1 triệu). Lệnh 120 triệu ở cảnh 3 vẫn đang giữ.

Nói: “Cùng cuộc gọi, thêm mục đích cơ quan nhà nước. Hai nhóm dấu hiệu. Cúp máy không mở được nút. Tổng đài xác nhận lừa đảo thì lệnh bị huỷ và tiền được trả lại.”

## 5. Trương Gia Thịnh, mức 2 được đọc số

Đổi sang Trương Gia Thịnh. Nguồn hiện `1903 002 119`. Gọi thật và giữ máy. Mở menu demo, bật “Demo: phiên có hướng dẫn” (chữ đổi màu khi bật). Công tắc này thay nhịp gõ bằng mẫu được đọc từng cụm. Tự gõ một dãy liền không tạo ra mẫu đó.

Chuyển tiền, gõ `0902402001` (Ngô Thanh Hà). Số tiền `500000`. Người nhận mới nên app hỏi mục đích: chọn “Khác”. Không chọn cơ quan nhà nước. Xác nhận.

Màn hình mức 2, một nhóm (B), chưa tăng cường. Câu lớn: “Cách bạn thao tác giống như đang được người khác đọc cho từng bước.” Câu lớn chỉ nói chung về cách thao tác, nên không dòng nào bị coi là nói lại. Hai dòng lý do: “Bạn nhập số tài khoản theo từng cụm, như đang được đọc cho.” và “Có cuộc gọi đang diễn ra trong phiên này.” “Xem chi tiết” mở thêm một dòng: chưa từng chuyển tới người nhận này. Có dòng cúp máy. Nút giống cảnh 3, “Tiếp tục” khoá cho đến khi cúp máy. Bấm “Huỷ”. Cúp máy. Tắt “Demo: phiên có hướng dẫn”.

Nói: “Số tài khoản được đọc từng cụm trong lúc nghe máy. Ngân hàng nhận ra cách nhập, không cần số tiền lớn.”

## Slide dự phòng

Không nằm trong năm cảnh trên. Dùng khi không chạy được app.

- `docs/screens/level-3-mule.png`: mức 3, tài khoản đường dây. Hoàng, `0902003001`, 500.000 đ. Tiêu đề: “Giao dịch đang được ngân hàng xem xét.” Câu: “Tài khoản nhận đã được xác nhận là tài khoản lừa đảo. Ngân hàng đang giữ giao dịch để bảo vệ bạn.” Chỉ có “Về trang chủ”.
- `docs/screens/level-2-capture.png`: mức 2 vì màn hình đang bị ghi. Hoàng, `0902401001`, 500.000 đ. Câu: “Màn hình của bạn đang bị ghi hoặc chia sẻ. Kẻ lừa đảo thường yêu cầu chia sẻ màn hình để hướng dẫn.”
