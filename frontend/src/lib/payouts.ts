import type { Payout, PayoutCalculation } from "../api/types";

export type PayoutState = "paid" | "requested" | "due" | "upcoming" | "waiting";

/** Where a payout stands today: paid, requested, due now, upcoming, or waiting for the first client payment. */
export function payoutState(p: Payout, today: string): PayoutState {
  if (p.paid_at) return "paid";
  if (p.payment_requested_at) return "requested";
  if (!p.due_at) return "waiting";
  return p.due_at <= today ? "due" : "upcoming";
}

export const PAYOUT_CHIP: Record<PayoutState, { label: string; cls: string }> = {
  paid: { label: "Paid", cls: "chip-success" },
  requested: { label: "Requested", cls: "chip-brand" },
  due: { label: "Due now", cls: "chip-success" },
  upcoming: { label: "Upcoming", cls: "chip-brand" },
  waiting: { label: "Awaiting client payment", cls: "chip-neutral" },
};

export function calc(p: Payout): PayoutCalculation {
  return p.calculation as PayoutCalculation;
}

/** "Client portal" for a project share, "Task fee · SP-TO-2026-021" for a task fee. */
export function payoutName(p: Payout, projectName: Map<number, string>): string {
  if (p.kind === "task_fee") return `Task fee · ${calc(p).task_order ?? "Task Order"}`;
  return projectName.get(p.project_id ?? -1) ?? "Project share";
}

export function statementPath(p: Payout): string {
  return `/api/payouts/${p.id}/statement.pdf`;
}
