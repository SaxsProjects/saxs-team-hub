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
      if (url.endsWith("/api/auth/refresh")) return json(401, { detail: "Your sign-in has ended." }); // no cookie yet
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

    await user.type(await screen.findByLabelText("Email address"), "admin@saxsprojects.co.za");
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
    expect(meCall.init.credentials).toBe("omit"); // only the sign-in endpoints carry the cookie
    expect(calls.find((c) => c.url.endsWith("/api/auth/login"))!.init.credentials).toBe("include");
    expect(JSON.stringify({ ...sessionStorage, ...localStorage })).not.toContain("tok"); // the pass is never stored
  });

  it("shows the server's message on a wrong password and stays signed out", async () => {
    const user = userEvent.setup();
    renderApp(() => json(401, { detail: "Wrong email or password" }));
    await screen.findByLabelText("Email address");
    await user.type(screen.getByLabelText("Email address"), "x@saxsprojects.co.za");
    await user.type(screen.getByLabelText("Password"), "nope");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Wrong email or password");
    expect(hasSession()).toBe(false);
  });
});

/** Pretend to be a phone: its browser name and (optionally) its passkey prompt. */
function fakePhone(credentials?: { get: unknown }, userAgent?: string) {
  if (userAgent) vi.spyOn(navigator, "userAgent", "get").mockReturnValue(userAgent);
  if (credentials) Object.defineProperty(navigator, "credentials", { configurable: true, value: credentials });
}

afterEach(() => {
  vi.restoreAllMocks();
  delete (navigator as unknown as { credentials?: unknown }).credentials;
});

describe("trusted device", () => {
  const DEVICE = { email: "thandi@example.com", full_name: "Thandi Mokoena", device_name: "Team Hub Android app", passkey: false };
  const MEMBER = { ...ADMIN, id: 2, email: "thandi@example.com", role: "member", person_id: 1, totp_enabled: false, two_factor_required: false, full_name: "Thandi Mokoena" };

  it("remembers the account and unlocks with the password alone", async () => {
    const user = userEvent.setup();
    const calls = renderApp((url, init) => {
      if (url.endsWith("/api/auth/refresh")) return json(401, { detail: "Your sign-in has ended." });
      if (url.endsWith("/api/auth/device")) return json(200, DEVICE);
      if (url.endsWith("/api/auth/unlock")) {
        return JSON.parse(String(init.body)).password === "right-password"
          ? json(200, { access_token: "tok", token_type: "bearer", expires_in: 900 })
          : json(401, { detail: "Wrong password. 4 more tries on this device." });
      }
      if (url.endsWith("/api/auth/me")) return json(200, MEMBER);
      return json(200, []);
    });

    expect(await screen.findByText("Welcome back, Thandi.")).toBeInTheDocument();
    expect(screen.getByText("thandi@example.com")).toBeInTheDocument();
    expect(screen.queryByLabelText("Email address")).not.toBeInTheDocument(); // no email to type
    await user.type(screen.getByLabelText("Password"), "wrong");
    await user.click(screen.getByRole("button", { name: "Unlock" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("4 more tries");

    await user.type(screen.getByLabelText("Password"), "right-password");
    await user.click(screen.getByRole("button", { name: "Unlock" }));
    await waitFor(() => expect(hasSession()).toBe(true));
    expect(calls.filter((c) => c.url.endsWith("/api/auth/unlock")).every((c) => c.init.credentials === "include")).toBe(true);
    expect(calls.some((c) => c.url.endsWith("/api/auth/login"))).toBe(false); // no two-factor step
  });

  it("asks for the fingerprint or face straight away when a passkey is set up", async () => {
    const get = vi.fn(async () => ({
      id: "AQID",
      rawId: new Uint8Array([1, 2, 3]).buffer,
      type: "public-key",
      response: {
        clientDataJSON: new Uint8Array([4]).buffer,
        authenticatorData: new Uint8Array([5]).buffer,
        signature: new Uint8Array([6]).buffer,
        userHandle: null,
      },
      getClientExtensionResults: () => ({}),
    }));
    fakePhone({ get }, "Mozilla/5.0 (Linux; Android 14)");
    const calls = renderApp((url) => {
      if (url.endsWith("/api/auth/refresh")) return json(401, { detail: "Your sign-in has ended." });
      if (url.endsWith("/api/auth/device")) return json(200, { ...DEVICE, passkey: true });
      if (url.endsWith("/api/auth/unlock/passkey/options")) return json(200, { challenge_id: 7, options: { challenge: "AAEC", rpId: "hub.saxsprojects.co.za", allowCredentials: [{ id: "AQID", type: "public-key" }] } });
      if (url.endsWith("/api/auth/unlock/passkey")) return json(200, { access_token: "tok", token_type: "bearer", expires_in: 900 });
      if (url.endsWith("/api/auth/me")) return json(200, MEMBER);
      return json(200, []);
    });
    await waitFor(() => expect(hasSession()).toBe(true));
    expect(get).toHaveBeenCalledOnce();
    const sent = JSON.parse(String(calls.find((c) => c.url.endsWith("/api/auth/unlock/passkey"))!.init.body));
    expect(sent.challenge_id).toBe(7);
    expect(sent.credential.response.signature).toBe("Bg");
  });

  it("falls back to the password when the prompt is cancelled", async () => {
    const user = userEvent.setup();
    const get = vi.fn(async () => Promise.reject(new DOMException("cancelled", "NotAllowedError")));
    fakePhone({ get });
    renderApp((url) => {
      if (url.endsWith("/api/auth/refresh")) return json(401, { detail: "Your sign-in has ended." });
      if (url.endsWith("/api/auth/device")) return json(200, { ...DEVICE, passkey: true });
      if (url.endsWith("/api/auth/unlock/passkey/options")) return json(200, { challenge_id: 7, options: { challenge: "AAEC", rpId: "x" } });
      return json(200, []);
    });
    expect(await screen.findByLabelText("Password")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument(); // cancelling is not an error
    await user.click(screen.getByRole("button", { name: "Not you? Use another account" }));
    expect(await screen.findByLabelText("Email address")).toBeInTheDocument();
  });

  it("locks after 5 minutes in the background", async () => {
    let hidden = false;
    Object.defineProperty(document, "hidden", { configurable: true, get: () => hidden });
    const now = vi.spyOn(Date, "now");
    const calls = renderApp((url) => {
      if (url.endsWith("/api/auth/refresh")) return json(200, { access_token: "tok", token_type: "bearer", expires_in: 900 });
      if (url.endsWith("/api/auth/device")) return json(200, DEVICE);
      if (url.endsWith("/api/auth/me")) return json(200, MEMBER);
      if (url.endsWith("/api/auth/logout")) return new Response(null, { status: 204 });
      return json(200, []);
    });
    expect(await screen.findByRole("navigation")).toBeInTheDocument();
    await waitFor(() => expect(calls.some((c) => c.url.endsWith("/api/auth/device"))).toBe(true));

    const t0 = Date.now();
    now.mockReturnValue(t0);
    hidden = true;
    document.dispatchEvent(new Event("visibilitychange"));
    now.mockReturnValue(t0 + 4 * 60_000); // back within 5 minutes: still open
    hidden = false;
    document.dispatchEvent(new Event("visibilitychange"));
    expect(hasSession()).toBe(true);

    hidden = true;
    document.dispatchEvent(new Event("visibilitychange"));
    now.mockReturnValue(t0 + 10 * 60_000);
    hidden = false;
    document.dispatchEvent(new Event("visibilitychange"));
    await waitFor(() => expect(hasSession()).toBe(false));
    expect(await screen.findByText("Welcome back, Thandi.")).toBeInTheDocument();
    now.mockRestore();
    delete (document as unknown as { hidden?: boolean }).hidden;
  });

  it("offers to keep a phone signed in, and sends the choice", async () => {
    const user = userEvent.setup();
    fakePhone(undefined, "Mozilla/5.0 (Linux; Android 14) Chrome/140.0");
    const calls = renderApp((url) => {
      if (url.endsWith("/api/auth/refresh")) return json(401, { detail: "Your sign-in has ended." });
      if (url.endsWith("/api/auth/device")) return json(401, { detail: "This device is not trusted." });
      return json(401, { detail: "Wrong email or password" });
    });
    const keep = await screen.findByRole("checkbox", { name: "Keep me signed in on this device" });
    expect(keep).toBeChecked(); // a phone
    await user.type(screen.getByLabelText("Email address"), "x@saxsprojects.co.za");
    await user.type(screen.getByLabelText("Password"), "pw");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    await screen.findByRole("alert");
    expect(JSON.parse(String(calls.find((c) => c.url.endsWith("/api/auth/login"))!.init.body)).trust_device).toBe(true);
  });
});
