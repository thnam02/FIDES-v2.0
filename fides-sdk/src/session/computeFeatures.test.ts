import { computeFeatures } from "./computeFeatures"
import { SessionRecorder } from "./SessionRecorder"
import type { SessionEvent } from "./types"

const limit = { burst_gap_ms: 1500 }

function event(type: SessionEvent["type"], t: number, extra: Partial<SessionEvent> = {}): SessionEvent {
  return { type, t, ...extra }
}

describe("computeFeatures", () => {
  it("một sự kiện thì mọi số là 0", () => {
    const features = computeFeatures([event("screen_enter", 5, { screen: "amount" })], limit)
    expect(features).toEqual({
      median_gap_ms: 0,
      p90_gap_ms: 0,
      burst_count: 0,
      pause_to_action_ratio: 0,
      review_dwell_ms: 0,
      edit_count: 0,
      backtrack_count: 0,
      screen_revisit_count: 0,
      background_count: 0,
      background_total_ms: 0,
      session_duration_ms: 0,
      payee_burst_count: 0,
      payee_mean_burst_len: 0,
      payee_inter_burst_gap_median_ms: 0,
    })
  })

  it("không có khoảng cách thì burst một cụm và tỉ lệ nghỉ là 0", () => {
    const features = computeFeatures(
      [event("key_tick", 5), event("key_tick", 5), event("confirm_tap", 5)],
      limit,
    )
    expect(features.median_gap_ms).toBe(0)
    expect(features.p90_gap_ms).toBe(0)
    expect(features.burst_count).toBe(1)
    expect(features.pause_to_action_ratio).toBe(0)
    expect(features.session_duration_ms).toBe(0)
  })

  it("tính median, p90, burst và tỉ lệ nghỉ", () => {
    const features = computeFeatures(
      [
        event("screen_enter", 0, { screen: "amount" }),
        event("key_tick", 100),
        event("key_tick", 200),
        event("field_edit", 300),
        event("screen_enter", 5000, { screen: "confirm" }),
        event("app_background", 6000),
        event("app_foreground", 9000),
        event("confirm_tap", 10000),
      ],
      limit,
    )
    expect(features.median_gap_ms).toBe(1000)
    expect(features.p90_gap_ms).toBeCloseTo(3680)
    expect(features.burst_count).toBe(3)
    expect(features.pause_to_action_ratio).toBeCloseTo(7700 / 2300)
    expect(features.edit_count).toBe(1)
    expect(features.background_count).toBe(1)
    expect(features.background_total_ms).toBe(3000)
    expect(features.session_duration_ms).toBe(10000)
    expect(features.review_dwell_ms).toBe(2000)
    expect(features.backtrack_count).toBe(0)
    expect(features.screen_revisit_count).toBe(0)
  })

  it("khoảng đúng bằng ngưỡng không phải burst", () => {
    const features = computeFeatures([event("key_tick", 0), event("key_tick", 1500)], limit)
    expect(features.burst_count).toBe(0)
    expect(features.pause_to_action_ratio).toBe(0)
  })

  it("toàn khoảng nghỉ thì tỉ lệ là 0 vì không có khoảng thao tác", () => {
    const features = computeFeatures([event("key_tick", 0), event("key_tick", 4000)], limit)
    expect(features.burst_count).toBe(0)
    expect(features.pause_to_action_ratio).toBe(0)
  })

  it("nền trong lúc xem lại bị trừ khỏi review_dwell", () => {
    const features = computeFeatures(
      [
        event("screen_enter", 0, { screen: "confirm" }),
        event("app_background", 1000),
        event("app_foreground", 4000),
        event("confirm_tap", 5000),
      ],
      limit,
    )
    expect(features.review_dwell_ms).toBe(2000)
    expect(features.background_total_ms).toBe(3000)
  })

  it("nền chưa về thì tính tới sự kiện cuối và cắt ở confirm", () => {
    const features = computeFeatures(
      [
        event("screen_enter", 0, { screen: "confirm" }),
        event("app_background", 100),
        event("confirm_tap", 400),
      ],
      limit,
    )
    expect(features.background_total_ms).toBe(300)
    expect(features.review_dwell_ms).toBe(100)
  })

  it("quay lại màn cũ là backtrack, vào lại cùng màn chỉ là revisit", () => {
    const back = computeFeatures(
      [
        event("screen_enter", 0, { screen: "amount" }),
        event("screen_enter", 10, { screen: "confirm" }),
        event("screen_enter", 20, { screen: "amount" }),
      ],
      limit,
    )
    expect(back.backtrack_count).toBe(1)
    expect(back.screen_revisit_count).toBe(0)

    const again = computeFeatures(
      [event("screen_enter", 0, { screen: "amount" }), event("screen_enter", 10, { screen: "amount" })],
      limit,
    )
    expect(again.backtrack_count).toBe(0)
    expect(again.screen_revisit_count).toBe(1)
  })

  it("cụm số tài khoản tách ở 1000 ms, một phím là cụm dài 1", () => {
    const features = computeFeatures(
      [
        event("key_tick", 0, { payee: true }),
        event("key_tick", 200, { payee: true }),
        event("key_tick", 400, { payee: true }),
        event("key_tick", 2500, { payee: true }),
        event("key_tick", 2700, { payee: true }),
        event("key_tick", 5000, { payee: true }),
        event("key_tick", 5200),
      ],
      limit,
    )
    expect(features.payee_burst_count).toBe(3)
    expect(features.payee_mean_burst_len).toBe(2)
    expect(features.payee_inter_burst_gap_median_ms).toBe(2200)
    expect(features.burst_count).toBeGreaterThan(0)
    const alone = computeFeatures([event("key_tick", 0, { payee: true })], limit)
    expect(alone.payee_burst_count).toBe(1)
    expect(alone.payee_mean_burst_len).toBe(1)
    expect(alone.payee_inter_burst_gap_median_ms).toBe(0)
    const wide = computeFeatures(
      [event("key_tick", 0, { payee: true }), event("key_tick", 1000, { payee: true })],
      limit,
    )
    expect(wide.payee_burst_count).toBe(2)
  })

  it("ngưỡng burst đổi được", () => {
    const features = computeFeatures([event("key_tick", 0), event("key_tick", 100)], { burst_gap_ms: 50 })
    expect(features.burst_count).toBe(0)
  })
})

describe("SessionRecorder", () => {
  it("xoá mốc thô sau khi tính, trừ bản sao thí nghiệm", () => {
    let clock = 0
    const recorder = new SessionRecorder(() => clock)
    recorder.start("new_typed")
    recorder.allowExperiment({ participantId: "p-1", condition: "control", sessionIndex: 0, consented: true })
    clock = 10
    recorder.note({ type: "key_tick", payee: true, field: "A0002119" })
    recorder.note({ type: "paste", payee: false })
    const snapshot = recorder.end()
    expect(snapshot.task_type).toBe("new_typed")
    expect(snapshot.raw_events?.map((item) => item.type)).toEqual(["key_tick", "paste", "confirm_tap"])
    expect(snapshot.raw_events?.every((item) => !("field" in item) || item.field === undefined)).toBe(true)
    expect(JSON.stringify(snapshot.raw_events)).not.toContain("A0002119")
    expect(snapshot.raw_events?.[0].payee).toBe(true)
    expect(snapshot.behaviour_features.payee_burst_count).toBe(1)
    expect(recorder.isOpen()).toBe(false)
    recorder.start("qr")
    const next = recorder.end()
    expect(next.raw_events).toBeUndefined()
    expect(next.task_type).toBe("qr")
    expect(next.behaviour_features.session_duration_ms).toBe(0)
    expect(next.behaviour_features.payee_burst_count).toBeUndefined()
  })

  it("không giữ mốc khi chưa đồng ý", () => {
    const recorder = new SessionRecorder(() => 1)
    recorder.start("saved_payee")
    recorder.allowExperiment({ participantId: "p-1", condition: "control", sessionIndex: 1, consented: false })
    recorder.note({ type: "saved_payee_pick" })
    const snapshot = recorder.end()
    expect(snapshot.task_type).toBe("saved_payee")
    expect(snapshot.raw_events).toBeUndefined()
    expect(snapshot.experiment).toBeUndefined()
  })

  it("cách nhập người nhận quyết định task_type, dán số tiền thì không", () => {
    const recorder = new SessionRecorder(() => 1)
    recorder.start("new_typed")
    recorder.note({ type: "key_tick", payee: true })
    recorder.note({ type: "paste", payee: true })
    recorder.note({ type: "paste" })
    recorder.note({ type: "saved_payee_pick" })
    const saved = recorder.end()
    expect(saved.task_type).toBe("saved_payee")
    expect(saved.behaviour_features.payee_burst_count).toBeUndefined()
  })
})
