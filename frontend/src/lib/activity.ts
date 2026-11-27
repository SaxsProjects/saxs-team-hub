import type { AuditEntry } from "../api/types";

/** Plain-English wording for audit-log entries (Recent activity, the bell, Audit history). */
const TITLES: Record<string, string> = {
  "auth.login": "Signed in",
  "auth.2fa_enabled": "Two-factor turned on",
  "auth.reset_requested": "Password reset requested",
  "auth.reset_password": "Password reset",
  "auth.set_password": "Password set",
  "auth.change_password": "Password changed",
  "auth.login_locked": "Sign-in blocked after failed attempts",
  "auth.totp_lock": "Two-factor locked after wrong codes",
  "auth.session_token_reused": "Old sign-in pass reused; session ended",
  "auth.unlock": "Unlocked a trusted device",
  "auth.device_trusted": "New trusted device",
  "auth.device_removed": "Trusted device removed",
  "auth.device_untrusted": "Device untrusted after wrong passwords",
  "auth.passkey_added": "Passkey set up (fingerprint, face or Windows Hello)",
  "settings.notifications": "Notification settings changed",
  "user.create_admin": "Admin account created",
  "user.avatar_set": "Profile picture updated",
  "user.avatar_removed": "Profile picture removed",
  "user.invite_resent": "Invitation sent again",
  "user.access": "Team access changed",
  "person.create": "Person added",
  "person.update": "Person details updated",
  "person.stage": "Onboarding stage changed",
  "person.rate_change": "Rate reviewed",
  "person.rate_withdraw": "Rate review withdrawn",
  "person.sensitive_update": "Banking details saved",
  "person.sensitive_reveal": "Banking details revealed",
  "person.erase": "Personal details erased",
  "onboarding.update": "Onboarding step updated",
  "document.upload": "Document uploaded",
  "retention.purge": "Old candidate record deleted",
  "offer.create": "Offer drafted",
  "offer.update": "Offer edited",
  "offer.attach_pdf": "Offer PDF attached",
  "offer.send": "Offer sent",
  "offer.view": "Offer opened",
  "offer.accept": "Offer accepted",
  "offer.decline": "Offer declined",
  "offer.revoke": "Offer withdrawn",
  "offer.expire": "Offer expired",
  "project.create": "Project created",
  "project.update": "Project updated",
  "project.set_contributor": "Contributor share set",
  "project.remove_contributor": "Contributor removed",
  "project.lock_shares": "Project shares locked",
  "project.record_payment": "Client payment recorded",
  "project.add_cost": "Project cost added",
  "task_order.create": "Task Order proposed",
  "task_order.update": "Task Order edited",
  "task_order.confirm": "Task Order confirmed",
  "task_order.decline": "Task Order declined",
  "task_order.submit": "Task Order submitted",
  "task_order.accept": "Task Order accepted",
  "task_order.request_changes": "Changes requested",
  "task_order.cancel": "Task Order cancelled",
  "client.create": "Client added",
  "client.update": "Client details updated",
  "quotation.create": "Quotation drafted",
  "quotation.update": "Quotation edited",
  "quotation.delete_draft": "Draft quotation deleted",
  "quotation.issue": "Quotation issued",
  "quotation.accept": "Quotation accepted",
  "quotation.decline": "Quotation declined",
  "quotation.expire": "Quotation expired",
  "invoice.create": "Invoice drafted",
  "invoice.update": "Invoice edited",
  "invoice.delete_draft": "Draft invoice deleted",
  "invoice.issue": "Invoice issued",
  "invoice.payment": "Invoice payment recorded",
  "invoice.credit_note": "Credit note issued",
  "payout.create": "Payout created",
  "payout.release_deferred": "Deferred fee released",
  "payout.request_payment": "Payment requested",
  "payout.paid": "Payout marked as paid",
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
  const number = (entry.after?.number ?? entry.after?.statement_number ?? entry.after?.reference ?? entry.after?.device) as string | undefined;
  const detail = number ? String(number) : entry.entity_id ? `${entry.entity.replace(/_/g, " ")} #${entry.entity_id}` : "";
  const tone: ActivityTone = /locked|totp_lock|reused|untrusted|device_trusted|decline|cancel|expire|revoke/.test(entry.action)
    ? "amber"
    : /accept|confirm|paid|enabled|lock_shares/.test(entry.action)
    ? "success"
    : /offer|person|user/.test(entry.action)
      ? "amber"
      : "brand";
  return { title, detail, tone };
}
