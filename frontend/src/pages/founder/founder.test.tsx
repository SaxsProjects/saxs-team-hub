import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { MemoryRouter, Route, Routes } from "react-router";
import { AuditHistory } from "./AuditHistory";
import { Finance } from "./Finance";
import { Payouts } from "./Payouts";
import { TaskOrders } from "./TaskOrders";

type Call = { url: string; method: string; body: unknown };

function json(status: number, body: unknown): Response {
  return new Response(status === 204 ? null : JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

/** Renders one screen against a fake API; `routes` maps "METHOD /path" (or "/path" for GET) to a response body. */
function renderPage(page: ReactNode, routes: Record<string, unknown>, path = "/", pattern = "*") {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init: RequestInit = {}) => {
      const method = init.method ?? "GET";
      const p = new URL(url).pathname;
      calls.push({ url: p, method, body: typeof init.body === "string" ? JSON.parse(init.body) : undefined });
      const hit = routes[`${method} ${p}`] ?? (method === "GET" ? routes[p] : undefined);
      return hit === undefined ? json(404, { detail: "Not found" }) : json(200, hit);
    }),
  );
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path={pattern} element={page} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return calls;
}

afterEach(() => vi.unstubAllGlobals());

const PEOPLE = [{ id: 5, full_name: "Thabo Mokoena", email: "t@example.com", phone: null, status: "onboarded", rate_bp: 1500, fee_terms: "standard", created_at: "2026-10-30T08:00:00Z", has_sensitive_details: true, avatar_url: null }];

const SUBMITTED = {
  id: 24, number: "SP-TO-2026-024", person_id: 5, title: "Email template", deliverable: "One template.", fee_cents: 45000, due_on: "2026-11-30",
  fee_terms: "standard", status: "submitted", submitted_at: "2026-11-25T08:00:00Z", review_due_on: "2026-11-28", review_note: null, accepted_on: null,
  created_at: "2026-11-20T08:00:00Z", review_overdue: false, confirmed_at: null, closed_reason: null,
  submission_note: "Delivery link: https://github.com/SaxsProjects/demo/pull/31\n\nTested in Gmail.",
};

describe("Founder Task Orders", () => {
  it("shows the delivery link, needs a note to request changes, and accepts", async () => {
    const user = userEvent.setup();
    const calls = renderPage(<TaskOrders />, {
      "/api/task-orders": [SUBMITTED],
      "/api/people": PEOPLE,
      "POST /api/task-orders/24/request-changes": { ...SUBMITTED, status: "confirmed" },
      "POST /api/task-orders/24/accept": { ...SUBMITTED, status: "accepted" },
    });
    const link = await screen.findByRole("link", { name: "github.com/SaxsProjects/demo/pull/31" });
    expect(link).toHaveAttribute("href", "https://github.com/SaxsProjects/demo/pull/31");
    expect(screen.getByText("Tested in Gmail.")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Request changes" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Write a short note");
    expect(calls.some((c) => c.method === "POST")).toBe(false);

    await user.type(screen.getByLabelText("Feedback"), "Looks good, thanks.");
    await user.click(screen.getByRole("button", { name: "Accept delivery" }));
    await screen.findByText(/SP-TO-2026-024 accepted/);
    const accept = calls.find((c) => c.method === "POST")!;
    expect(accept.url).toBe("/api/task-orders/24/accept");
    expect(accept.body).toEqual({ note: "Looks good, thanks." });
  });
});

describe("Founder Payouts", () => {
  it("needs an EFT reference before marking a due payout as paid", async () => {
    const user = userEvent.setup();
    const due = {
      id: 27, kind: "revenue_share", project_id: 26, person_id: 5, task_order_id: null, amount_cents: 270000, due_at: "2026-01-01", paid_at: null,
      payment_requested_at: null, eft_reference: null, statement_number: "SP-PS-2026-027", calculation: {},
    };
    const calls = renderPage(<Payouts />, {
      "/api/payouts": [due],
      "/api/people": PEOPLE,
      "/api/projects": [{ id: 26, name: "Client portal", client_name: "Ubuntu", description: null, status: "in_progress", created_at: "2026-10-20T08:00:00Z" }],
      "POST /api/payouts/27/paid": { ...due, paid_at: "2026-11-26T08:00:00Z", eft_reference: "EFT-1" },
    });
    const panel = await screen.findByRole("region", { name: "Payout details" });
    expect(within(panel).getByText("Thabo Mokoena")).toBeInTheDocument();
    await user.click(within(panel).getByRole("button", { name: "Mark as paid" }));
    expect(await within(panel).findByRole("alert")).toHaveTextContent("EFT reference");

    await user.type(within(panel).getByLabelText("EFT reference"), "EFT-1");
    await user.click(within(panel).getByRole("button", { name: "Mark as paid" }));
    await screen.findByText(/SP-PS-2026-027 marked as paid/);
    expect(calls.find((c) => c.method === "POST")).toMatchObject({ url: "/api/payouts/27/paid", body: { eft_reference: "EFT-1" } });
  });
});

describe("Client finance", () => {
  it("won't record more than the invoice balance, then records the payment in cents", async () => {
    const user = userEvent.setup();
    const invoice = {
      id: 11, number: "SP-INV-2026-011", client_id: 1, project_id: null, quotation_id: null, title: "Website", notes: null, status: "part_paid",
      issue_date: "2026-10-24", due_date: "2099-12-02", vat_rate_bp: 0, subtotal_cents: 2400000, vat_cents: 0, total_cents: 2400000, paid_cents: 1200000,
      credited_cents: 0, balance_cents: 1200000, overdue: false, issued_at: "2026-10-24T08:00:00Z",
      lines: [{ id: 1, position: 1, description: "Website", quantity: 1, unit_price_cents: 2400000, line_total_cents: 2400000 }],
    };
    const calls = renderPage(
      <Finance />,
      {
        "/api/invoices": [invoice],
        "/api/clients": [{ id: 1, name: "Greenline Studio", registration_number: null, contact_name: null, email: null, phone: null, address: null, created_at: "2026-09-01T08:00:00Z" }],
        "/api/quotations": [],
        "/api/projects": [],
        "/api/invoices/11/receipts": [],
        "/api/invoices/11/credit-notes": [],
        "POST /api/invoices/11/payments": { invoice, receipt: { id: 5, number: "SP-REC-2026-005" }, payouts: [] },
      },
      "/finance/invoices",
      "/finance/:tab",
    );
    const panel = await screen.findByRole("region", { name: "Invoice details" });
    await user.click(within(panel).getByRole("button", { name: "Record payment" }));
    const dialog = screen.getByRole("dialog");
    const amount = within(dialog).getByLabelText("Amount (R)");
    await user.clear(amount);
    await user.type(amount, "13 000");
    await user.type(within(dialog).getByLabelText("Reference"), "GRN-1");
    await user.click(within(dialog).getByRole("button", { name: "Record payment" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("balance is only R12 000.00");

    await user.clear(amount);
    await user.type(amount, "12 000");
    await user.click(within(dialog).getByRole("button", { name: "Record payment" }));
    await screen.findByText(/Receipt SP-REC-2026-005 issued/);
    expect(calls.find((c) => c.method === "POST")).toMatchObject({ url: "/api/invoices/11/payments", body: { amount_cents: 1200000, method: "eft", reference: "GRN-1" } });
  });
});

describe("Audit history", () => {
  it("filters events by search text and shows the selected event", async () => {
    const user = userEvent.setup();
    renderPage(<AuditHistory />, {
      "/api/audit": [
        { id: 2, actor: "admin", action: "payout.paid", entity: "payout", entity_id: 12, before: null, after: { statement_number: "SP-PS-2026-012" }, at: "2026-11-17T08:15:00Z" },
        { id: 1, actor: "admin", action: "offer.send", entity: "offer", entity_id: 14, before: null, after: null, at: "2026-11-16T08:15:00Z" },
      ],
    });
    expect(await screen.findAllByText("Payout marked as paid")).not.toHaveLength(0);
    await user.type(screen.getByLabelText("Search events"), "offer");
    const table = screen.getByRole("table");
    expect(within(table).queryByText("Payout marked as paid")).not.toBeInTheDocument();
    expect(within(table).getByText("Offer sent")).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Event detail" })).toHaveTextContent("offer.send");
  });
});
