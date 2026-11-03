# Snapshot Redis cho demo

Sổ đặc trưng demo nằm ở Redis db 15 và được ghi ra `dump.rdb`. `scripts/demo_reset.sh` tắt Redis không ghi đè file, rồi bật lại để nạp đúng file đó.

## Nạp lại

```sh
cd SEDIF
export FIDES_HMAC_KEY=fides-demo-hmac
export REDIS_URL=redis://localhost:6379/15
python scripts/rebuild_feature_snapshot.py
```

Mặc định nạp mọi sự kiện observed trước `2026-09-21T10:00:00+07:00`, rồi `SAVE`. Không cắt 7 ngày. Cùng file parquet và cùng mốc thì ra cùng một sổ: `build_until` xoá db 15, phát lại theo `ts`, và ghi `f:snapshot_until`.

Đừng dùng `scripts/snapshot_features.py --rebuild` cho sổ này. Lệnh đó trim khoản cũ hơn 7 ngày trước mốc, nên mất cửa sổ 90 ngày và 12 tháng của thói quen chuyển tiền.

`--until` khác `2026-09-20T00:00:00+07:00` thì `fides/tests/test_snapshot_parity.py` không còn khớp mốc cũ, vì test đó tiếp tục sự kiện từ đúng biên snapshot. Sổ demo hiện dùng mốc 21/9 10:00 để buổi sáng demo vẫn còn lịch sử thói quen. `test_decide_http_matches_seed45` không đọc mốc này: nó chấm model đã đóng gói, nên không cần phát lại 13 phút khi chỉ đổi mốc demo.
