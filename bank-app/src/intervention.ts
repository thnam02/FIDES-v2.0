/** Màn mức 2 và tờ mức 1. Câu chữ giữ đúng bản đã chốt. */

export const LEVEL1_HEADLINE = "Hãy kiểm tra lại trước khi chuyển."
export const HANGUP_NOTE = "Hãy cúp máy trước. Công an, ngân hàng và cơ quan nhà nước không bao giờ yêu cầu chuyển tiền qua điện thoại."
export const STRENGTHENED_NOTE = "Giao dịch có nhiều dấu hiệu lừa đảo. Gọi tổng đài để xác nhận ngay, hoặc nhờ người giám hộ xác nhận."
export const FAKE_RELATIVE_NOTE = "Nếu người thân nhắn tin hỏi mượn tiền, hãy gọi lại cho họ bằng số bạn đã lưu trước khi chuyển."
export const HOTLINE_BUTTON = "Gọi tổng đài ngân hàng"
export const PAUSE_BUTTON = "Tạm dừng để xác minh"
export const CANCEL_BUTTON = "Huỷ"
export const CONTINUE_BUTTON = "Tiếp tục"
export const GUARDIAN_BUTTON = "Nhờ người giám hộ xác nhận"

export function level2Buttons(showGuardian: boolean): string[] {
  const buttons = [HOTLINE_BUTTON, PAUSE_BUTTON]
  if (showGuardian) buttons.push(GUARDIAN_BUTTON)
  buttons.push(CANCEL_BUTTON, CONTINUE_BUTTON)
  return buttons
}

export function showFakeRelative(payeeIsNew: boolean, purpose: string | null | undefined): boolean {
  return payeeIsNew && purpose === "family_friends"
}

export function formatLock(ms: number): string {
  const total = Math.max(0, Math.ceil(ms / 1000))
  const minutes = Math.floor(total / 60)
  const seconds = total % 60
  return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`
}

export type ContinueView = {
  enabled: boolean
  label: string
  notes: string[]
}

/** now là đồng hồ ngân hàng, không phải giờ máy. unlocked là tổng đài đã xác nhận. */
export function continueView(input: {
  continueRequiresHangup: boolean
  callActive: boolean
  strengthened: boolean
  lockUntil: string | null
  now: number | null
  unlocked: boolean
}): ContinueView {
  const notes: string[] = []
  const callBlocks = input.continueRequiresHangup && input.callActive
  if (callBlocks) notes.push(HANGUP_NOTE)
  if (input.strengthened) {
    notes.push(STRENGTHENED_NOTE)
    if (!input.unlocked) {
      const until = input.lockUntil ? Date.parse(input.lockUntil) : Number.NaN
      if (input.now == null || Number.isNaN(until) || until - input.now > 0) {
        const label = input.now == null || Number.isNaN(until) ? "Có thể tiếp tục sau --:--" : `Có thể tiếp tục sau ${formatLock(until - input.now)}`
        return { enabled: false, label, notes }
      }
    }
  }
  return { enabled: !callBlocks, label: CONTINUE_BUTTON, notes }
}
