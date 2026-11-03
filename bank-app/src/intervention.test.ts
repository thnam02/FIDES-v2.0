import assert from "node:assert/strict"
import test from "node:test"

import { CONTINUE_BUTTON, continueView, FAKE_RELATIVE_NOTE, level2Buttons, showFakeRelative, STRENGTHENED_NOTE, HANGUP_NOTE } from "./intervention.ts"

const lock = "2026-09-21T10:30:00+07:00"
const before = Date.parse("2026-09-21T10:00:00+07:00")
const after = Date.parse("2026-09-21T10:30:00+07:00")

test("level 2 buttons put continue last and hide the guardian without consent", () => {
  assert.deepEqual(level2Buttons(false), ["Gọi tổng đài ngân hàng", "Tạm dừng để xác minh", "Huỷ", "Tiếp tục"])
  assert.deepEqual(level2Buttons(true).at(-1), "Tiếp tục")
  assert.ok(level2Buttons(true).includes("Nhờ người giám hộ xác nhận"))
  assert.equal(level2Buttons(false).includes("Nhờ người giám hộ xác nhận"), false)
})

test("an active call disables continue until the call ends", () => {
  const blocked = continueView({
    continueRequiresHangup: true,
    callActive: true,
    strengthened: false,
    lockUntil: null,
    now: before,
    unlocked: false,
  })
  assert.equal(blocked.enabled, false)
  assert.equal(blocked.label, CONTINUE_BUTTON)
  assert.deepEqual(blocked.notes, [HANGUP_NOTE])
  const open = continueView({ ...{
    continueRequiresHangup: true,
    callActive: false,
    strengthened: false,
    lockUntil: null,
    now: before,
    unlocked: false,
  } })
  assert.equal(open.enabled, true)
})

test("strengthened shows the countdown until the lock or a hotline unlock", () => {
  const locked = continueView({
    continueRequiresHangup: true,
    callActive: false,
    strengthened: true,
    lockUntil: lock,
    now: before,
    unlocked: false,
  })
  assert.equal(locked.enabled, false)
  assert.equal(locked.label, "Có thể tiếp tục sau 30:00")
  assert.ok(locked.notes.includes(STRENGTHENED_NOTE))
  const unlocked = continueView({
    continueRequiresHangup: true,
    callActive: false,
    strengthened: true,
    lockUntil: lock,
    now: before,
    unlocked: true,
  })
  assert.equal(unlocked.enabled, true)
  assert.equal(unlocked.label, CONTINUE_BUTTON)
  const expired = continueView({
    continueRequiresHangup: false,
    callActive: false,
    strengthened: true,
    lockUntil: lock,
    now: after,
    unlocked: false,
  })
  assert.equal(expired.enabled, true)
})

test("a new payee sent to family or friends shows the fake-relative line", () => {
  assert.equal(showFakeRelative(true, "family_friends"), true)
  assert.equal(showFakeRelative(false, "family_friends"), false)
  assert.equal(showFakeRelative(true, "purchase"), false)
  assert.ok(FAKE_RELATIVE_NOTE.includes("số bạn đã lưu"))
})
