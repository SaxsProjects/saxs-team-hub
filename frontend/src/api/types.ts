/** Shapes returned by the Team Hub API (see backend/app/schemas.py). Money is whole cents; rates are basis points. */

export interface Me {
  id: number;
  email: string;
  role: "admin" | "member";
  person_id: number | null;
  totp_enabled: boolean;
  two_factor_required: boolean;
  full_name: string | null;
  avatar_url: string | null;
}

export interface TokenOut {
  access_token: string;
  token_type: string;
  expires_in: number;
}

export interface Dashboard {
  today: string;
  payouts: {
    unpaid_count: number;
    unpaid_cents: number;
    due_now_count: number;
    due_now_cents: number;
    due_next_7_days_cents: number;
    waiting_for_first_payment_cents: number;
    payment_requested_count: number;
    paid_this_year_cents: number;
  };
  invoices: { outstanding_count: number; outstanding_cents: number; overdue_count: number; overdue_cents: number; draft_count: number };
  quotations_awaiting_answer: number;
  task_orders_by_status: Record<string, number>;
  task_reviews_overdue: number;
  people_by_status: Record<string, number>;
  received_this_year_cents: number;
}

export interface MemberOverview {
  today: string;
  current_rate_bp: number;
  owed_cents: number;
  due_now_cents: number;
  due_now_count: number;
  can_request_payment_count: number;
  next_due_on: string | null;
  waiting_for_first_payment_cents: number;
  paid_this_year_cents: number;
  task_orders_to_confirm: number;
  task_orders_in_progress: number;
  task_orders_awaiting_review: number;
  onboarding_open: number;
}

export interface Project {
  id: number;
  name: string;
  client_name: string;
  description: string | null;
  status: "planned" | "in_progress" | "completed" | "cancelled";
  created_at: string;
}

export interface AuditEntry {
  id: number;
  actor: string;
  action: string;
  entity: string;
  entity_id: number | null;
  before: Record<string, unknown> | null;
  after: Record<string, unknown> | null;
  at: string;
}

export type TaskOrderStatus = "proposed" | "confirmed" | "submitted" | "accepted" | "declined" | "cancelled";

export interface TaskOrder {
  id: number;
  number: string;
  person_id: number;
  title: string;
  deliverable: string;
  fee_cents: number;
  due_on: string;
  fee_terms: string;
  status: TaskOrderStatus;
  submitted_at: string | null;
  review_due_on: string | null;
  review_note: string | null;
  accepted_on: string | null;
  created_at: string;
  review_overdue: boolean;
}

export interface Payout {
  id: number;
  kind: "revenue_share" | "task_fee";
  project_id: number | null;
  person_id: number;
  task_order_id: number | null;
  amount_cents: number;
  due_at: string | null;
  paid_at: string | null;
  payment_requested_at: string | null;
  eft_reference: string | null;
  statement_number: string;
  calculation: Record<string, unknown>;
}

export interface OnboardingItem {
  id: number;
  key: string;
  item: string;
  position: number;
  member_can_complete: boolean;
  done: boolean;
  done_at: string | null;
}

export interface MyProject {
  project_id: number;
  project: string;
  client: string;
  status: Project["status"];
  work_share_bp: number;
  rate_bp: number;
  current_rate_bp: number;
  locked_at: string | null;
}

export interface Person {
  id: number;
  full_name: string;
  email: string;
  phone: string | null;
  status: string;
  rate_bp: number;
  fee_terms: string;
  created_at: string;
  has_sensitive_details: boolean;
  avatar_url: string | null;
}
