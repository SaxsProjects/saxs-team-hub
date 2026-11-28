import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { MemoryRouter, Route, Routes } from "react-router";

vi.mock("../../auth/AuthContext", () => ({
  useAuth: () => ({ me: { full_name: "Founder", email: "f@example.com", role: "admin", totp_enabled: true, avatar_url: null }, signOut: vi.fn() }),
}));
vi.mock("../../lib/pdfRender", () => ({
  renderPdf: async (_data: ArrayBuffer, host: HTMLElement) => {
    host.textContent = "Rendered PDF page";
    return { pages: 1, destroy: () => undefined };
  },
}));
import { AppShell } from "../../components/AppShell";
import { PreviewProvider } from "../../components/DocumentPreview";
import { Certificates } from "./Certificates";
import { Proposals } from "./Proposals";

type Call = { url: string; method: string; body: unknown };
const pdf = () => new Response("%PDF-1.4", { status: 200, headers: { "Content-Type": "application/pdf" } });
const json = (status: number, body: unknown) => new Response(status === 204 ? null : JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

function renderPage(page: ReactNode, routes: Record<string, unknown>) {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init: RequestInit = {}) => {
      const method = init.method ?? "GET";
      const p = new URL(url).pathname;
      calls.push({ url: p, method, body: typeof init.body === "string" ? JSON.parse(init.body) : undefined });
      const hit = routes[`${method} ${p}`] ?? (method === "GET" ? routes[p] : undefined);
      if (typeof hit === "function") return (hit as () => Response)();
      return hit === undefined ? json(404, { detail: "Not found" }) : json(200, hit);
    }),
  );
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <PreviewProvider>
          <Routes>
            <Route path="*" element={page} />
          </Routes>
        </PreviewProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return calls;
}

const CLIENT = { id: 1, name: "Glow Salon", kind: "company", registration_number: null, vat_number: null, reminders_enabled: true, contact_name: null, email: "o@glow.example", phone: null, address: null, created_at: "2026-11-01T00:00:00Z" };
const DRAFT = {
  id: 5, number: null, client_id: 1, title: "Business website for Glow Salon", status: "draft", service: "website",
  introduction: "Thank you", need: "A website", solution: "We build it", scope: "Design\nBuild", timeline: "3 weeks", why_us: "Registered company",
  items: [{ description: "Website design and build", quantity: 1, unit_price_cents: 0 }],
  vat_rate_bp: 0, subtotal_cents: 0, vat_cents: 0, total_cents: 0, issue_date: null, valid_until: null, quotation_id: null, pdf_sha256: null, created_at: "2026-11-28T08:00:00Z",
};

describe("Notification bell", () => {
  it("shows the unread count and marks one as read when opened", async () => {
    const calls = renderPage(<AppShell>content</AppShell>, {
      "/api/dashboard": {},
      "/api/notifications": {
        unread: 2,
        items: [
          { id: 7, kind: "reviews", title: "Task submitted for review: SP-TO-0003", body: "Landing page", link: "/task-orders", created_at: "2026-11-28T08:00:00Z", read_at: null },
          { id: 6, kind: "payouts", title: "Paid: SP-PS-0002", body: null, link: null, created_at: "2026-11-27T08:00:00Z", read_at: "2026-11-27T09:00:00Z" },
        ],
      },
      "POST /api/notifications/read": { unread: 1 },
    });
    const user = userEvent.setup();
    const bell = await screen.findByRole("button", { name: "Notifications: 2 unread" });
    expect(within(bell).getByText("2")).toBeInTheDocument();
    await user.click(bell);
    await user.click(await screen.findByText("Task submitted for review: SP-TO-0003"));
    expect(calls.find((c) => c.method === "POST" && c.url === "/api/notifications/read")?.body).toEqual({ ids: [7] });
  });
});

describe("Proposals", () => {
  it("asks the hub for a first draft and warns until it is priced", async () => {
    const calls = renderPage(<Proposals />, {
      "/api/proposals": [],
      "/api/clients": [CLIENT],
      "/api/proposals/presets": [
        { key: "website", label: "Business website" },
        { key: "mobile_app", label: "Mobile app (Android)" },
      ],
      "POST /api/proposals/generate": DRAFT,
    });
    const user = userEvent.setup();
    expect(await screen.findByText(/No proposals yet/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /New proposal/ }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Write first draft" }));
    expect(await within(dialog).findByText("Choose the client.")).toBeInTheDocument();
    await user.selectOptions(within(dialog).getByLabelText(/Client/), "1");
    await user.selectOptions(within(dialog).getByLabelText("Service"), "mobile_app");
    await user.click(within(dialog).getByRole("button", { name: "Write first draft" }));
    expect(calls.find((c) => c.url === "/api/proposals/generate")?.body).toEqual({ client_id: 1, service: "mobile_app", need: null });
  });

  it("previews an unpriced draft and offers to issue it", async () => {
    renderPage(<Proposals />, { "/api/proposals": [DRAFT], "/api/clients": [CLIENT], "/api/proposals/5/pdf": pdf });
    const user = userEvent.setup();
    expect(await screen.findByText(/Set the prices before issuing/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Preview & issue" }));
    expect(await screen.findByText("Rendered PDF page")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Issue proposal" })).toBeInTheDocument();
  });
});

describe("Certificates", () => {
  it("won't issue with blanks, then previews before issuing", async () => {
    const preset = { kind: "completion", title: "CERTIFICATE", subtitle: "OF COMPLETION", lead: "This is to certify that", body: "has successfully completed ______________________________." };
    const calls = renderPage(<Certificates />, {
      "/api/certificates": [],
      "/api/certificates/presets": [preset],
      "POST /api/certificates/preview": pdf,
    });
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: /New certificate/ }));
    const dialog = await screen.findByRole("dialog");
    await user.type(within(dialog).getByLabelText(/Awarded to/), "Jane Doe");
    await user.click(within(dialog).getByRole("button", { name: "Preview" }));
    expect(await within(dialog).findByText(/Fill in the blanks/)).toBeInTheDocument();
    const text = within(dialog).getByLabelText("What it certifies");
    await user.clear(text);
    await user.type(text, "has successfully completed the Web Basics course.");
    await user.click(within(dialog).getByRole("button", { name: "Preview" }));
    expect(await screen.findByText("Rendered PDF page")).toBeInTheDocument();
    expect(calls.find((c) => c.url === "/api/certificates/preview")?.body).toMatchObject({ kind: "completion", recipient_name: "Jane Doe" });
    expect(calls.some((c) => c.method === "POST" && c.url === "/api/certificates")).toBe(false);
  });
});
