import type { components } from "./api/openapi"
import { reasonLine } from "./format"
import type { Outcome } from "./store"

export type HeldTransfer = {
  transfer_id: string
  from_account: string
  to_account: string
  amount: number
  payee_name: string
  status: components["schemas"]["TransferStatus"]
  funds_status: "held" | "released" | "cancelled"
  hold_until: string | null
  hotline_verified?: boolean
  decision: components["schemas"]["BankDecision"]
}

export function transferLevel(value: string | number | null | undefined): number | null {
  if (value == null || value === "" || value === "unscored") return null
  const n = Number(value)
  return Number.isFinite(n) ? n : null
}

export function outcomeFromTransfer(payload: HeldTransfer): Outcome {
  const decision = payload.decision
  const card = decision.evidence_card
  const engineLevel = decision.unscored && decision.level == null ? null : decision.level
  const reasonsVi = (card?.reasons_vi ?? decision.reasons.map((reason) => reason.text) ?? []).map(reasonLine).filter(Boolean)
  const restatedVi = (card?.restated_vi ?? []).map(reasonLine).filter(Boolean)
  return {
    transferId: payload.transfer_id,
    decisionId: `dec-${payload.transfer_id}`,
    status: payload.status,
    level: decision.level,
    engineLevel: engineLevel ?? null,
    intervention: decision.intervention ?? (engineLevel === 3 ? "security_workflow" : engineLevel === 2 ? "three_button" : engineLevel === 1 ? "banner" : "none"),
    actions: decision.actions,
    reasons: (decision.reasons ?? []).map((reason) => ({ ...reason, text: reasonLine(reason.text) })),
    reasonsVi,
    restatedVi,
    signalsPresent: decision.signals_present ?? [],
    funds_status: payload.funds_status,
    gate: "none",
    hold_until: payload.hold_until,
    countdown_until: null,
    payee: payload.to_account,
    payeeName: payload.payee_name,
    amount: payload.amount,
    headline: decision.headline ?? "",
    groupsFired: decision.groups_fired ?? [],
    strengthened: Boolean(decision.strengthened),
    continueRequiresHangup: Boolean(decision.continue_requires_hangup),
    lockUntil: decision.lock_until ?? null,
    hotlineUnlocked: Boolean(payload.hotline_verified),
    demoNotice: null,
  }
}
