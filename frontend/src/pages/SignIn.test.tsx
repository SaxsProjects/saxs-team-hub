import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { App } from "../App";
import { API_URL, clearSession, hasSession } from "../api/client";
import { AuthProvider } from "../auth/AuthContext";

type Handler = (url: string, init: RequestInit) => Response;

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

function renderApp(handler: Handler) {
  const calls: { url: string; init: RequestInit }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init: RequestInit = {}) => {
      calls.push({ url, init });
      return handler(url, init);
    }),
  );
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <AuthProvider>
          <App />
        </AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return calls;
}

const ADMIN = {
  id: 1, email: "admin@saxsprojects.co.za", role: "admin", person_id: null, totp_enabled: true,
  two_factor_required: true, full_name: null, avatar_url: null,
};

const DASHBOARD = {
  today: "2026-11-26",
  payouts: {
    unpaid_count: 3, unpaid_cents: 540_000, due_now_count: 3, due_now_cents: 540_000, due_next_7_days_cents: 0,
    waiting_for_first_payment_cents: 0, payment_requested_count: 2, paid_this_year_cents: 0,
  },
  invoices: { outstanding_count: 1, outstanding_cents: 2_400_000, overdue_count: 1, overdue_cents: 600_000, draft_count: 0 },
  quotations_awaiting_answer: 0,
  task_orders_by_status: { submitted: 2 },
  task_reviews_overdue: 0,
  people_by_status: { onboarded: 4, accepted: 2 },
  received_this_year_cents: 8_400_000,
};

afterEach(() => {
  clearSession();
  vi.unstubAllGlobals();
});

describe("sign in", () => {
  it("asks for the two-factor code, then signs in with it", async () => {
    const user = userEvent.setup();
    const calls = renderApp((url, init) => {
      if (url.endsWith("/api/auth/login")) {
        const body = JSON.parse(String(init.body));
        if (!body.totp_code) return json(401, { detail: "totp_required" });
        return body.totp_code === "123456"
          ? json(200, { access_token: "tok", token_type: "bearer", expires_in: 3600 })
          : json(401, { detail: "Wrong two-factor code" });
      }
      if (url.endsWith("/api/auth/me")) return json(200, ADMIN);
      if (url.endsWith("/api/dashboard")) return json(200, DASHBOARD);
      return json(200, []); // dashboard widgets: empty is fine for this test
    });

    await user.type(screen.getByLabelText("Email address"), "admin@saxsprojects.co.za");
    await user.type(screen.getByLabelText("Password"), "a-test-password");
    await user.click(screen.getByRole("button", { name: "Sign in" }));

    expect(await screen.findByText("One more step.")).toBeInTheDocument();
    const code = screen.getByLabelText("Authentication code");
    await user.type(code, "12ab3456"); // letters are dropped
    expect(code).toHaveValue("123456");
    await user.click(screen.getByRole("button", { name: "Verify & sign in" }));

    await waitFor(() => expect(hasSession()).toBe(true));
    expect(await screen.findByRole("navigation")).toBeInTheDocument();
    // The overview shows the real figures from the API in the design's format.
    expect(await screen.findByText("R84 000.00")).toBeInTheDocument();
    expect(screen.getByText("R6 000.00 overdue")).toBeInTheDocument();
    expect(screen.getByText("4 of 6")).toBeInTheDocument();
    expect(screen.getByLabelText("2 to review")).toBeInTheDocument();
    // Every request went to the API host only; the token was sent as a bearer header after sign-in.
    expect(calls.every((c) => c.url.startsWith(API_URL))).toBe(true);
    const meCall = calls.find((c) => c.url.endsWith("/api/auth/me"))!;
    expect(new Headers(meCall.init.headers).get("Authorization")).toBe("Bearer tok");
    expect(meCall.init.credentials).toBe("omit");
  });

  it("shows the server's message on a wrong password and stays signed out", async () => {
    const user = userEvent.setup();
    renderApp(() => json(401, { detail: "Wrong email or password" }));
    await user.type(screen.getByLabelText("Email address"), "x@saxsprojects.co.za");
    await user.type(screen.getByLabelText("Password"), "nope");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Wrong email or password");
    expect(hasSession()).toBe(false);
  });
});
