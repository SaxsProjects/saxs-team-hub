import type { AuditEntry } from "../api/types";

/** Plain-English wording for audit-log entries (Recent activity, the bell, Audit history). */
const TITLES: Record<string, string> = {
  "auth.login": "Signed in",
  "auth.2fa_enabled": "Two-factor turned on",
  "settings.notifications": "Notification settings changed",
  "auth.reset_password": "Password reset",
  "auth.set_password": "Password set",
  "auth.change_password": "Password changed",
  "auth.login_locked": "Sign-in blocked after failed attempts",
  "auth.totp_lock": "Two-factor locked after wrong codes",
  "user.create_admin": "Admin account created",
  "user.avatar_set": "Profile picture updated",
  "user.avatar_removed": "Profile picture removed",
  "user.invite_resent": "Invitation sent again",
  "user.access": "Team access changed",
  "person.create": "Person added",
  "person.update": "Person details updated",
  "person.stage": "Onboarding stage changed",
  "person.sensitive_update": "Banking details saved",
  "person.sensitive_view": "Banking details viewed",
  "offer.create": "Offer drafted",
  "offer.send": "Offer sent",
  "offer.viewed": "Offer opened",
  "offer.accept": "Offer accepted",
  "offer.accepted": "Offer accepted",
  "offer.decline": "Offer declined",
  "offer.revoke": "Offer withdrawn",
  "project.create": "Project created",
  "project.payment": "Client payment recorded",
  "project.lock": "Project shares locked",
  "task_order.create": "Task Order proposed",
  "task_order.confirm": "Task Order confirmed",
  "task_order.submit": "Task Order submitted",
  "task_order.accept": "Task Order accepted",
  "task_order.request_changes": "Changes requested",
  "invoice.issue": "Invoice issued",
  "invoice.payment": "Invoice payment recorded",
  "quotation.issue": "Quotation issued",
  "payout.paid": "Payout marked as paid",
  "payout.payment_requested": "Payment requested",
  "payout.export_payment_list": "Payment list downloaded",
};

function fallbackTitle(action: string): string {
  const [entity, verb] = action.split(".");
  const words = `${(entity ?? "").replace(/_/g, " ")} ${(verb ?? "").replace(/_/g, " ")}`.trim();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/** Colour of the dot in the activity timeline, as in the design: blue money/default, green done, amber people. */
export type ActivityTone = "brand" | "success" | "amber";

export function describeAudit(entry: AuditEntry): { title: string; detail: string; tone: ActivityTone } {
  const title = TITLES[entry.action] ?? fallbackTitle(entry.action);
  const number = (entry.after?.number ?? entry.after?.statement_number ?? entry.after?.reference) as string | undefined;
  const detail = number ? String(number) : entry.entity_id ? `${entry.entity.replace(/_/g, " ")} #${entry.entity_id}` : "";
  const tone: ActivityTone = /accept|confirm|paid|enabled|lock/.test(entry.action)
    ? "success"
    : /offer|person|user/.test(entry.action)
      ? "amber"
      : "brand";
  return { title, detail, tone };
}
