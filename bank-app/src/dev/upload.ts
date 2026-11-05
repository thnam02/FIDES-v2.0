import type { components } from "../api/openapi"
import { BANK_URL, bankFetch } from "../api/client"

/** raw_events chỉ đi endpoint thí nghiệm, không đi kèm /transfer. */
export function uploadExperiment(body: components["schemas"]["ExperimentSessionUpload"]) {
  return bankFetch(`${BANK_URL}/experiment/sessions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  }).catch(() => undefined)
}
