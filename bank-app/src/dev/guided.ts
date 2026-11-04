import type { components } from "../api/openapi"

/** Ca được đọc số: nhịp và xem lại ở mức thường, không rời app, vài cụm 2–4 số cách 2–5 giây. */
export const GUIDED_FEATURES: components["schemas"]["BehaviourFeatures"] = {
  median_gap_ms: 831.0210845522126,
  p90_gap_ms: 2279.7838136013606,
  burst_count: 2,
  pause_to_action_ratio: 0.18471028781378585,
  review_dwell_ms: 1474,
  edit_count: 1,
  backtrack_count: 0,
  screen_revisit_count: 1,
  background_count: 0,
  background_total_ms: 0,
  session_duration_ms: 41830,
  payee_burst_count: 4,
  payee_mean_burst_len: 3,
  payee_inter_burst_gap_median_ms: 3500,
}
