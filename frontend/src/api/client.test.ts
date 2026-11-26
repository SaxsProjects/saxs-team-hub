import { api, clearSession, hasSession, idleFor, renew, setSession, signOutHere, signOutPending } from "./client";

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

afterEach(() => {
  clearSession();
  vi.unstubAllGlobals();
});

describe("staying signed in", () => {
  it("renews once when a pass runs out, then repeats the request", async () => {
    setSession("old", 900);
    const seen: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init: RequestInit = {}) => {
        const auth = new Headers(init.headers).get("Authorization");
        seen.push(`${new URL(url).pathname.replace("/api", "")} ${auth ?? init.credentials}`);
        if (url.endsWith("/api/auth/refresh")) return json(200, { access_token: "new", expires_in: 900 });
        return auth === "Bearer new" ? json(200, { ok: true }) : json(401, { detail: "Session expired or invalid" });
      }),
    );
    await expect(api("/api/dashboard")).resolves.toEqual({ ok: true });
    expect(seen).toEqual(["/dashboard Bearer old", "/auth/refresh include", "/dashboard Bearer new"]);
  });

  it("signs out when the server refuses to renew", async () => {
    setSession("old", 900);
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => json(401, { detail: "Your sign-in has ended." })),
    );
    await expect(api("/api/dashboard")).rejects.toThrow();
    expect(hasSession()).toBe(false);
  });

  it("sends a single renewal however many requests need it", async () => {
    const fetchMock = vi.fn(async () => json(200, { access_token: "t", expires_in: 900 }));
    vi.stubGlobal("fetch", fetchMock);
    await Promise.all([renew(), renew(), renew()]);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(hasSession()).toBe(true);
  });
});

describe("signing out and temporary failures", () => {
  it("keeps the sign-in when the server is only busy or restarting", async () => {
    setSession("t", 900);
    vi.stubGlobal("fetch", vi.fn(async () => json(503, { detail: "restarting" })));
    expect(await renew()).toBe(false);
    expect(hasSession()).toBe(true);
  });

  it("remembers a sign-out that didn't reach the server, until it does", async () => {
    setSession("t", 900);
    vi.stubGlobal("fetch", vi.fn(async () => { throw new TypeError("offline"); }));
    expect(await signOutHere()).toBe(false);
    expect(hasSession()).toBe(false);
    expect(signOutPending()).toBe(true);
    vi.stubGlobal("fetch", vi.fn(async () => new Response(null, { status: 204 })));
    expect(await signOutHere()).toBe(true);
    expect(signOutPending()).toBe(false);
  });

  it("a new sign-in clears a pending sign-out", () => {
    sessionStorage.setItem("teamhub.signedOut", "1");
    setSession("t", 900);
    expect(signOutPending()).toBe(false);
  });

  it("activity in another tab counts", () => {
    localStorage.setItem("teamhub.lastActivity", String(Date.now()));
    expect(idleFor()).toBeLessThan(1_000);
  });
});
