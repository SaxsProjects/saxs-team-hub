import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useSearchParams } from "react-router";
import { api } from "../../api/client";
import type { AuditEntry } from "../../api/types";
import { EmptyRow, ErrorNote, LoadingRow, PageHead, Pager, RowButton, paginate } from "../../components/ui";
import { describeAudit } from "../../lib/activity";
import { TIME_ZONE, todaySA } from "../../lib/format";
import "../overview.css";
import "../pages.css";

const pad = (n: number | null) => (n === null ? "—" : String(n).padStart(3, "0"));

function when(at: string): string {
  const d = new Date(at);
  const day = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", timeZone: TIME_ZONE }).format(d);
  const time = new Intl.DateTimeFormat("en-GB", { hour: "2-digit", minute: "2-digit", hour12: false, timeZone: TIME_ZONE }).format(d);
  return `${day} · ${time}`;
}

function fullWhen(at: string): string {
  const d = new Date(at);
  return `${new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: TIME_ZONE }).format(d)}, ${new Intl.DateTimeFormat("en-GB", {
    hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false, timeZone: TIME_ZONE,
  }).format(d)} SAST`;
}

const dayOf = (at: string) => new Intl.DateTimeFormat("en-CA", { timeZone: TIME_ZONE }).format(new Date(at));

function value(v: unknown): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

function csvCell(v: string): string {
  // Neutralise spreadsheet formulas and quote every cell.
  const safe = /^[=+\-@\t\r]/.test(v) ? `'${v}` : v;
  return `"${safe.replace(/"/g, '""')}"`;
}

export function AuditHistory() {
  const log = useQuery({ queryKey: ["audit", "all"], queryFn: () => api<AuditEntry[]>("/api/audit?limit=1000") });
  const [search, setSearch] = useState("");
  const [action, setAction] = useState("");
  const [params] = useSearchParams();
  const [entity, setEntity] = useState(params.get("entity") ?? "");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [page, setPage] = useState(0);
  const [selectedId, setSelectedId] = useState<number | null>(null);

  if (log.isError) return <ErrorNote error={log.error} onRetry={() => log.refetch()} />;
  const all = log.data ?? [];
  const actions = [...new Set(all.map((e) => e.action))].sort();
  const entities = [...new Set(all.map((e) => e.entity))].sort();
  const q = search.trim().toLowerCase();
  const filtered = all.filter((e) => {
    if (action && e.action !== action) return false;
    if (entity && e.entity !== entity) return false;
    const day = dayOf(e.at);
    if (from && day < from) return false;
    if (to && day > to) return false;
    if (!q) return true;
    return `${describeAudit(e).title} ${e.action} ${e.entity} ${e.entity}/${pad(e.entity_id)} ${e.entity_id ?? ""} ${e.actor}`.toLowerCase().includes(q);
  });
  const view = paginate(filtered, page, 10);
  const selected = all.find((e) => e.id === selectedId) ?? view.rows[0];
  const reset = () => (setPage(0), setSelectedId(null));

  function exportEvents() {
    const rows = [["id", "time", "event", "action", "entity", "entity_id", "actor", "before", "after"]];
    for (const e of filtered)
      rows.push([String(e.id), e.at, describeAudit(e).title, e.action, e.entity, value(e.entity_id), e.actor, value(e.before), value(e.after)]);
    const blob = new Blob([rows.map((r) => r.map(csvCell).join(",")).join("\r\n")], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `audit-history-${todaySA()}.csv`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 30_000);
  }

  return (
    <div className="page">
      <PageHead title="Audit history" sub="Search events across the workspace.">
        <span className="chip chip-neutral">Read only</span>
        <button className="btn btn-primary" onClick={exportEvents} disabled={filtered.length === 0}>
          Export events
        </button>
      </PageHead>

      <div className="filters">
        <input className="input" type="search" placeholder="Search events or entity ID" aria-label="Search events" value={search} onChange={(e) => (setSearch(e.target.value), reset())} />
        <select className="input" aria-label="Action" value={action} onChange={(e) => (setAction(e.target.value), reset())}>
          <option value="">All actions</option>
          {actions.map((a) => (
            <option key={a} value={a}>
              {a}
            </option>
          ))}
        </select>
        <select className="input" aria-label="Entity" value={entity} onChange={(e) => (setEntity(e.target.value), reset())}>
          <option value="">All entities</option>
          {entities.map((a) => (
            <option key={a} value={a}>
              {a.replace(/_/g, " ")}
            </option>
          ))}
        </select>
        <div className="date-range">
          <input className="input" type="date" aria-label="From date" value={from} max={to || undefined} onChange={(e) => (setFrom(e.target.value), reset())} />
          <span aria-hidden="true">–</span>
          <input className="input" type="date" aria-label="To date" value={to} min={from || undefined} onChange={(e) => (setTo(e.target.value), reset())} />
        </div>
      </div>

      <div className="split">
        <section className="card">
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Event</th>
                  <th className="hide-sm">Entity</th>
                  <th className="hide-sm">Actor</th>
                  <th>Time · SAST</th>
                </tr>
              </thead>
              <tbody>
                {log.isPending && <LoadingRow cols={4} />}
                {log.data && filtered.length === 0 && <EmptyRow cols={4} text="No events match these filters." />}
                {view.rows.map((e) => (
                  <RowButton key={e.id} selected={e.id === selected?.id} onSelect={() => setSelectedId(e.id)}>
                    <td className="row-title">{describeAudit(e).title}</td>
                    <td className="hide-sm muted num">
                      {e.entity} / {pad(e.entity_id)}
                    </td>
                    <td className="hide-sm muted">{e.actor}</td>
                    <td className="muted num">{when(e.at)}</td>
                  </RowButton>
                ))}
              </tbody>
            </table>
          </div>
          {log.data && filtered.length > 0 && <Pager page={view.page} pages={view.pages} total={filtered.length} shown={view.rows.length} noun="events" onPage={setPage} />}
        </section>

        {selected && (
          <section className="card detail" aria-label="Event detail">
            <h3 className="card-title" style={{ fontSize: 20 }}>
              Event detail
            </h3>
            <span className="chip chip-brand" style={{ justifySelf: "start", marginTop: 10 }}>
              {describeAudit(selected).title}
            </span>
            <dl className="facts">
              <div>
                <dt>Event ID</dt>
                <dd className="num">audit / {String(selected.id).padStart(6, "0")}</dd>
              </div>
              <div>
                <dt>Occurred at</dt>
                <dd className="num">{fullWhen(selected.at)}</dd>
              </div>
              <div>
                <dt>Action</dt>
                <dd>{selected.action}</dd>
              </div>
              <div>
                <dt>Entity</dt>
                <dd className="num">
                  {selected.entity} / {pad(selected.entity_id)}
                </dd>
              </div>
              <div>
                <dt>Actor</dt>
                <dd>{selected.actor}</dd>
              </div>
            </dl>
            {(selected.before || selected.after) && (
              <>
                <hr className="divider" />
                <p className="stat-label caps-label">Record data</p>
                <dl className="kv" style={{ marginTop: 12 }}>
                  {Object.entries({ ...(selected.before ? Object.fromEntries(Object.entries(selected.before).map(([k, v]) => [`before ${k}`, v])) : {}), ...(selected.after ?? {}) }).map(([k, v]) => (
                    <div key={k}>
                      <dt>{k}</dt>
                      <dd style={{ wordBreak: "break-all", fontWeight: 500 }}>{value(v)}</dd>
                    </div>
                  ))}
                </dl>
              </>
            )}
          </section>
        )}
      </div>
    </div>
  );
}
