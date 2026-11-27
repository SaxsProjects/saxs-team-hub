import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { MemoryRouter } from "react-router";
import { MyPayouts } from "./MyPayouts";
import { MyTaskOrders } from "./MyTaskOrders";
import { Onboarding } from "./Onboarding";

type Call = { url: string; method: string; body: unknown };

function json(status: number, body: unknown): Response {
  return new Response(status === 204 ? null : JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

/** Renders one screen against a fake API; `routes` maps "METHOD /path" (or "/path" for GET) to a response body. */
function renderPage(page: ReactNode, routes: Record<string, unknown>, path = "/") {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init: RequestInit = {}) => {
      const method = init.method ?? "GET";
      const p = new URL(url).pathname;
      calls.push({ url: p, method, body: init.body ? JSON.parse(String(init.body)) : undefined });
      const hit = routes[`${method} ${p}`] ?? (method === "GET" ? routes[p] : undefined);
      return hit === undefined ? json(404, { detail: "Not found" }) : json(200, hit);
    }),
  );
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[path]}>{page}</MemoryRouter>
    </QueryClientProvider>,
  );
  return calls;
}

afterEach(() => vi.unstubAllGlobals());

const ORDER = {
  id: 21, number: "SP-TO-2026-021", person_id: 5, title: "Polish the mobile navigation", deliverable: "Tidy the menu.",
  fee_cents: 35000, due_on: "2026-11-28", fee_terms: "standard", status: "confirmed", submitted_at: null, review_due_on: null,
  review_note: null, accepted_on: null, created_at: "2026-11-20T08:00:00Z", review_overdue: false,
};

describe("My Task Orders", () => {
  it("rejects a link that isn't https, then submits the link and note together", async () => {
    const user = userEvent.setup();
    const calls = renderPage(<MyTaskOrders />, {
      "/api/me/task-orders": [ORDER],
      "POST /api/me/task-orders/21/submit": { ...ORDER, status: "submitted", review_due_on: "2026-12-01" },
    });
    const link = await screen.findByLabelText("Delivery link");
    await user.type(link, "github.com/x");
    await user.click(screen.getByRole("button", { name: "Submit for review" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("must start with https://");
    expect(calls.some((c) => c.method === "POST")).toBe(false);

    await user.clear(link);
    await user.type(link, "https://github.com/SaxsProjects/demo/pull/1");
    await user.type(screen.getByLabelText("Delivery note"), "Menu spacing fixed.");
    await user.click(screen.getByRole("button", { name: "Submit for review" }));
    await screen.findByText("SP-TO-2026-021 submitted for review.");
    const submit = calls.find((c) => c.method === "POST")!;
    expect(submit.url).toBe("/api/me/task-orders/21/submit");
    expect(submit.body).toEqual({ note: "Delivery link: https://github.com/SaxsProjects/demo/pull/1\n\nMenu spacing fixed." });
  });

  it("confirms a proposed task from the detail panel", async () => {
    const user = userEvent.setup();
    const proposed = { ...ORDER, id: 23, number: "SP-TO-2026-023", status: "proposed" };
    const calls = renderPage(<MyTaskOrders />, {
      "/api/me/task-orders": [proposed],
      "POST /api/me/task-orders/23/confirm": { ...proposed, status: "confirmed" },
    });
    await user.click(await screen.findByRole("button", { name: "Confirm task" }));
    await screen.findByText("SP-TO-2026-023 confirmed. You can start the work.");
    expect(calls.filter((c) => c.method === "POST").map((c) => c.url)).toEqual(["/api/me/task-orders/23/confirm"]);
  });
});

describe("My payouts", () => {
  const overview = {
    today: "2026-11-26", current_rate_bp: 1500, owed_cents: 420000, due_now_cents: 270000, due_now_count: 1, can_request_payment_count: 1,
    next_due_on: "2026-12-02", waiting_for_first_payment_cents: 0, paid_this_year_cents: 0, task_orders_to_confirm: 0,
    task_orders_in_progress: 0, task_orders_awaiting_review: 0, onboarding_open: 0,
  };
  const due = {
    id: 27, kind: "revenue_share", project_id: 26, person_id: 5, task_order_id: null, amount_cents: 270000, due_at: "2026-11-26",
    paid_at: null, payment_requested_at: null, eft_reference: null, statement_number: "SP-PS-2026-027",
    calculation: { received_to_date_cents: 3600000, costs_to_date_cents: 0, net_income_cents: 3600000, rate_bp: 1500, work_share_bp: 5000 },
  };

  it("shows how the amount was calculated and requests payment for a due payout", async () => {
    const user = userEvent.setup();
    const calls = renderPage(<MyPayouts />, {
      "/api/me/overview": overview,
      "/api/me/payouts": [due, { ...due, id: 30, due_at: "2026-12-02", statement_number: "SP-PS-2026-030", amount_cents: 150000 }],
      "/api/me/projects": [{ project_id: 26, project: "Client portal", client: "Ubuntu", status: "in_progress", work_share_bp: 5000, rate_bp: 1500, current_rate_bp: 1500, locked_at: null }],
      "POST /api/me/payouts/27/request-payment": { ...due, payment_requested_at: "2026-11-26T10:00:00Z" },
    });
    const panel = await screen.findByRole("region", { name: "Payout details" });
    expect(within(panel).getByText("Client portal")).toBeInTheDocument();
    expect(within(panel).getAllByText("R36 000.00", { selector: "dd" })).toHaveLength(2); // received and net (no costs)
    expect(within(panel).getByText("50%")).toBeInTheDocument();
    await user.click(within(panel).getByRole("button", { name: "Request payment" }));
    await screen.findByText(/Payment requested for SP-PS-2026-027/);
    expect(calls.find((c) => c.method === "POST")?.url).toBe("/api/me/payouts/27/request-payment");
  });

  it("opens the payout named in the link", async () => {
    renderPage(
      <MyPayouts />,
      { "/api/me/overview": overview, "/api/me/payouts": [due, { ...due, id: 30, due_at: "2026-12-02", statement_number: "SP-PS-2026-030" }], "/api/me/projects": [] },
      "/my/payouts?payout=30",
    );
    const panel = await screen.findByRole("region", { name: "Payout details" });
    await waitFor(() => expect(within(panel).getByText("SP-PS-2026-030")).toBeInTheDocument());
    expect(within(panel).queryByRole("button", { name: "Request payment" })).not.toBeInTheDocument(); // not due yet
  });
});

describe("Onboarding", () => {
  it("lets the member tick only the steps they may complete", async () => {
    const user = userEvent.setup();
    const items = [
      { id: 1, key: "agreement_signed", item: "Contractor agreement signed", position: 1, member_can_complete: false, done: false, done_at: null },
      { id: 6, key: "standards_read", item: "Coding standards and security rules read", position: 6, member_can_complete: true, done: false, done_at: null },
    ];
    const calls = renderPage(<Onboarding />, {
      "/api/me/onboarding": items,
      "PATCH /api/me/onboarding/6": { ...items[1], done: true, done_at: "2026-11-26T10:00:00Z" },
    });
    expect(await screen.findByText("0 of 2 complete")).toBeInTheDocument();
    expect(screen.getByText("The founder confirms this step once it’s done.")).toBeInTheDocument(); // agreement is founder-confirmed
    await user.click(screen.getByText("Team standards"));
    await user.click(screen.getByRole("button", { name: "Mark as read" }));
    await screen.findByText("“Team standards” marked as done.");
    expect(calls.find((c) => c.method === "PATCH")).toMatchObject({ url: "/api/me/onboarding/6", body: { done: true } });
  });
});
