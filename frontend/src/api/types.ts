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
  device_trusted?: boolean;
}

/** The account a trusted device belongs to, for the "Welcome back" screen. */
export interface TrustedDeviceInfo {
  email: string;
  full_name: string | null;
  device_name: string;
  passkey: boolean;
}

export interface TrustedDevice {
  id: number;
  name: string;
  created_at: string;
  last_used_at: string;
  passkey: boolean;
  this_device: boolean;
}

export interface PasskeyOptions {
  challenge_id: number;
  options: Record<string, unknown>;
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
  vat: VatPosition;
}

export type VatStatus = "registered" | "below" | "voluntary_possible" | "approaching" | "must_register";

export interface VatPosition {
  registered: boolean;
  vat_number: string | null;
  rate_bp: number;
  taxable_12m_cents: number;
  compulsory_threshold_cents: number;
  voluntary_threshold_cents: number;
  share_of_compulsory_bp: number;
  status: VatStatus;
  message: string;
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

export interface RatePeriod {
  id: number;
  person_id: number;
  rate_bp: number;
  effective_from: string;
  review_note: string;
  created_by: string;
  created_at: string;
}

export interface DocumentInfo {
  id: number;
  person_id: number | null;
  kind: string;
  filename: string;
  content_type: string;
  size: number;
  sha256: string;
  version: number;
  created_at: string;
}

/** Banking details as the API returns them: account and ID numbers masked to the last digits. */
export interface MaskedBanking {
  bank_name: string;
  account_holder: string;
  account_number: string;
  branch_code: string;
  account_type: string;
  id_number?: string | null;
}

/** Revenue-share payouts carry the full calculation; task fees carry the Task Order and its fee. */
export interface PayoutCalculation {
  kind?: "task_fee";
  task_order?: string;
  fee_cents?: number;
  fee_terms?: string;
  received_to_date_cents?: number;
  costs_to_date_cents?: number;
  net_income_cents?: number;
  rate_bp?: number;
  work_share_bp?: number;
  earned_to_date_cents?: number;
  previously_allocated_cents?: number;
  payout_cents?: number;
}

// ---- Founder (admin) shapes -------------------------------------------------------------

export type PersonStage = "draft" | "sent" | "viewed" | "accepted" | "declined" | "expired" | "agreement_signed" | "onboarded";

export interface Offer {
  id: number;
  person_id: number;
  role: string;
  reference: string;
  deadline: string;
  message: string | null;
  status: "draft" | "sent" | "viewed" | "accepted" | "declined" | "expired" | "revoked";
  has_pdf: boolean;
  sent_at: string | null;
  viewed_at: string | null;
  responded_at: string | null;
  token_expires_at: string | null;
  overdue: boolean;
}

export interface PipelineCard {
  person_id: number;
  full_name: string;
  email: string;
  offer: Offer | null;
}

export interface Pipeline {
  stages: Record<PersonStage, PipelineCard[]>;
  overdue_count: number;
}

export interface Contributor {
  id: number;
  person_id: number;
  work_share_bp: number;
  rate_bp: number;
  locked_at: string | null;
}

export interface ProjectPayment {
  id: number;
  amount_cents: number;
  received_at: string;
  reference: string;
}

export interface ProjectCost {
  id: number;
  description: string;
  amount_cents: number;
  incurred_at: string;
}

export interface ProjectDetail extends Project {
  contributors: Contributor[];
  payments: ProjectPayment[];
  costs: ProjectCost[];
  received_cents: number;
  costs_cents: number;
  net_income_cents: number;
}

export interface FounderTaskOrder extends TaskOrder {
  confirmed_at: string | null;
  submission_note: string | null;
  closed_reason: string | null;
}

export type ClientKind = "company" | "sole_proprietor" | "individual" | "npo" | "government" | "other";

export interface Client {
  id: number;
  name: string;
  kind: ClientKind;
  registration_number: string | null;
  vat_number: string | null;
  reminders_enabled: boolean;
  contact_name: string | null;
  email: string | null;
  phone: string | null;
  address: string | null;
  created_at: string;
}

export interface Line {
  id: number;
  position: number;
  description: string;
  quantity: number;
  unit_price_cents: number;
  line_total_cents: number;
}

export interface Quotation {
  id: number;
  number: string | null;
  client_id: number;
  project_id: number | null;
  title: string;
  notes: string | null;
  status: "draft" | "issued" | "accepted" | "declined" | "expired";
  issue_date: string | null;
  valid_until: string | null;
  vat_rate_bp: number;
  subtotal_cents: number;
  vat_cents: number;
  total_cents: number;
  issued_at: string | null;
  lines: Line[];
}

export interface Invoice {
  id: number;
  number: string | null;
  client_id: number;
  project_id: number | null;
  quotation_id: number | null;
  title: string;
  notes: string | null;
  status: "draft" | "issued" | "part_paid" | "paid" | "void";
  issue_date: string | null;
  due_date: string | null;
  vat_rate_bp: number;
  subtotal_cents: number;
  vat_cents: number;
  total_cents: number;
  paid_cents: number;
  credited_cents: number;
  balance_cents: number;
  overdue: boolean;
  issued_at: string | null;
  lines: Line[];
}

export interface Receipt {
  id: number;
  number: string;
  invoice_id: number;
  amount_cents: number;
  received_on: string;
  method: string;
  reference: string;
  issue_date: string;
}

export interface CreditNote {
  id: number;
  number: string;
  invoice_id: number;
  reason: string;
  amount_cents: number;
  issue_date: string;
}

export interface FinanceReadiness {
  registration_number_set: boolean;
  bank_details_set: boolean;
  signature_set: boolean;
  signatory_name_set: boolean;
  vat_registered: boolean;
  can_issue_quotations: boolean;
  can_issue_invoices: boolean;
  missing: string[];
}

export interface FinanceSummary {
  invoices_open: number;
  outstanding_cents: number;
  overdue_cents: number;
  received_cents: number;
  quotations_open: number;
}

export interface LineInput {
  description: string;
  quantity: number;
  unit_price_cents: number;
}

export interface NotificationPrefs {
  offers: boolean;
  reviews: boolean;
  payouts: boolean;
  invoices: boolean;
  enquiries: boolean;
  client_reminders: boolean;
  client_statements: boolean;
}

export interface CompanyDetails {
  company_name: string;
  company_legal_name: string;
  company_registration_number: string;
  company_vat_number: string;
  company_address: string;
  company_email: string;
  company_phone: string;
  company_website: string;
  company_whatsapp: string;
  company_bank_name: string;
  company_bank_account_name: string;
  company_bank_account_number: string;
  company_bank_branch_code: string;
  company_bank_account_type: string;
  signatory_name: string;
  signatory_title: string;
}

export type TemplateCategory = "letterhead" | "offer" | "contract" | "policy" | "finance" | "other";

export interface TemplateVersion {
  version: number;
  filename: string;
  size: number;
  sha256: string;
  note: string | null;
  uploaded_by: string;
  created_at: string;
}

export interface CompanyTemplate {
  id: number;
  name: string;
  category: TemplateCategory;
  description: string | null;
  archived: boolean;
  updated_at: string;
  updated_by: string;
  current: TemplateVersion;
  versions: TemplateVersion[];
}

// ---- v2.0 ----------------------------------------------------------------------------------------

export interface NotificationItem {
  id: number;
  kind: string;
  title: string;
  body: string | null;
  link: string | null;
  created_at: string;
  read_at: string | null;
}

export interface NotificationList {
  unread: number;
  items: NotificationItem[];
}

export interface AssistantItem {
  id: string;
  priority: "high" | "normal" | "info";
  title: string;
  detail: string;
  link: string;
  action: string;
}

export interface AssistantBriefing {
  greeting: string;
  summary: string;
  today: string;
  items: AssistantItem[];
  autopilot: Partial<Record<"client_reminders" | "client_statements" | "monthly_report", boolean>>;
}

export type ProposalStatus = "draft" | "issued" | "accepted" | "declined" | "expired";
export type ProposalService = "website" | "web_app" | "mobile_app" | "ecommerce" | "automation" | "it_support" | "custom";

export interface ProposalItem {
  description: string;
  quantity: number;
  unit_price_cents: number;
}

export interface Proposal {
  id: number;
  number: string | null;
  client_id: number;
  title: string;
  status: ProposalStatus;
  service: ProposalService;
  introduction: string | null;
  need: string | null;
  solution: string | null;
  scope: string | null;
  timeline: string | null;
  why_us: string | null;
  items: ProposalItem[];
  vat_rate_bp: number;
  subtotal_cents: number;
  vat_cents: number;
  total_cents: number;
  issue_date: string | null;
  valid_until: string | null;
  quotation_id: number | null;
  pdf_sha256: string | null;
  created_at: string;
}

export type CertificateKind =
  | "completion"
  | "achievement"
  | "appreciation"
  | "participation"
  | "recognition"
  | "training"
  | "service"
  | "project"
  | "partnership"
  | "custom";

export interface CertificatePreset {
  kind: CertificateKind;
  title: string;
  subtitle: string;
  lead: string;
  body: string;
}

export interface Certificate {
  id: number;
  number: string;
  kind: CertificateKind;
  title: string;
  subtitle: string | null;
  lead: string;
  recipient_name: string;
  body: string;
  issue_date: string;
  place: string;
  verify_code: string;
  verify_url: string;
  revoked_at: string | null;
  revoke_reason: string | null;
  pdf_sha256: string;
  created_at: string;
}

export interface FinanceReport {
  month: string;
  prepared_on: string;
  totals: {
    invoiced_excl_cents: number;
    vat_cents: number;
    invoiced_incl_cents: number;
    credited_cents: number;
    received_cents: number;
    payouts_paid_cents: number;
    costs_cents: number;
    net_cash_cents: number;
  };
  position: {
    open_count: number;
    outstanding_cents: number;
    overdue_count: number;
    overdue_cents: number;
    payouts_unpaid_cents: number;
    quotations_open: number;
    proposals_open: number;
  };
  clients: { name: string; count: number; total_cents: number }[];
  vat: { message: string; compulsory_threshold_cents: number; share_of_compulsory_bp: number };
}

export interface StatementResult {
  number: string;
  document_id: number;
  emailed: boolean;
}

export type EnquiryStatus = "new" | "contacted" | "converted" | "closed";

export interface Enquiry {
  id: number;
  name: string;
  email: string | null;
  phone: string | null;
  organisation: string | null;
  service: string | null;
  message: string;
  source: string;
  status: EnquiryStatus;
  client_id: number | null;
  created_at: string;
}
