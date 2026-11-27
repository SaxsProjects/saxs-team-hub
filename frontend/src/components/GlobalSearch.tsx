import { useQuery } from "@tanstack/react-query";
import { Search, X } from "lucide-react";
import { useEffect, useId, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router";
import { api } from "../api/client";
import type { Client, DocumentInfo, FounderTaskOrder, Invoice, Payout, Person, Project, Quotation, TaskOrder } from "../api/types";
import { SETTINGS_ITEM, type NavItem } from "./nav";

interface Result {
  key: string;
  label: string;
  hint: string;
  to: string;
  /** Extra text that matches but isn't shown (emails, numbers, client names). */
  also?: string;
}

/** Loads what can be searched only once the box is used, reusing the pages' own cached lists. */
function useIndex(isAdmin: boolean, enabled: boolean): { results: Result[]; loading: boolean } {
  const admin = { enabled: enabled && isAdmin };
  const member = { enabled: enabled && !isAdmin };
  const people = useQuery({
    queryKey: ["people"],
    queryFn: () => api<Person[]>("/api/people"),
    ...admin,
  });
  const projects = useQuery({
    queryKey: ["projects"],
    queryFn: () => api<Project[]>("/api/projects"),
    ...admin,
  });
  const orders = useQuery({
    queryKey: ["task-orders"],
    queryFn: () => api<FounderTaskOrder[]>("/api/task-orders"),
    ...admin,
  });
  const clients = useQuery({
    queryKey: ["clients"],
    queryFn: () => api<Client[]>("/api/clients"),
    ...admin,
  });
  const invoices = useQuery({
    queryKey: ["invoices"],
    queryFn: () => api<Invoice[]>("/api/invoices"),
    ...admin,
  });
  const quotes = useQuery({
    queryKey: ["quotations"],
    queryFn: () => api<Quotation[]>("/api/quotations"),
    ...admin,
  });
  const payouts = useQuery({
    queryKey: ["payouts"],
    queryFn: () => api<Payout[]>("/api/payouts"),
    ...admin,
  });
  const myOrders = useQuery({
    queryKey: ["me-task-orders"],
    queryFn: () => api<TaskOrder[]>("/api/me/task-orders"),
    ...member,
  });
  const myDocs = useQuery({
    queryKey: ["me-documents"],
    queryFn: () => api<DocumentInfo[]>("/api/me/documents"),
    ...member,
  });

  const results = useMemo(() => {
    const names = new Map((people.data ?? []).map((p) => [p.id, p.full_name]));
    const clientNames = new Map((clients.data ?? []).map((c) => [c.id, c.name]));
    if (!isAdmin) {
      return [
        ...(myOrders.data ?? []).map((o) => ({
          key: `mt${o.id}`,
          label: o.title,
          hint: `Task Order ${o.number}`,
          to: "/my/task-orders",
          also: o.number,
        })),
        ...(myDocs.data ?? []).map((d) => ({
          key: `md${d.id}`,
          label: d.filename,
          hint: "Document",
          to: "/my/documents",
        })),
      ];
    }
    return [
      ...(people.data ?? []).map((p) => ({
        key: `pe${p.id}`,
        label: p.full_name,
        hint: "Person",
        to: `/team/${p.id}`,
        also: p.email,
      })),
      ...(projects.data ?? []).map((p) => ({
        key: `pr${p.id}`,
        label: p.name,
        hint: `Project · ${p.client_name}`,
        to: `/projects/${p.id}`,
        also: p.client_name,
      })),
      ...(orders.data ?? []).map((o) => ({
        key: `to${o.id}`,
        label: o.title,
        hint: `Task Order ${o.number} · ${names.get(o.person_id) ?? ""}`,
        to: `/task-orders?open=${o.id}`,
        also: `${o.number} ${names.get(o.person_id) ?? ""}`,
      })),
      ...(clients.data ?? []).map((c) => ({
        key: `cl${c.id}`,
        label: c.name,
        hint: "Client",
        to: `/finance/clients?open=${c.id}`,
        also: c.contact_name ?? "",
      })),
      ...(invoices.data ?? []).map((i) => ({
        key: `in${i.id}`,
        label: i.number ?? `Draft invoice: ${i.title}`,
        hint: `Invoice · ${clientNames.get(i.client_id) ?? ""} · ${i.title}`,
        to: `/finance/invoices?open=${i.id}`,
        also: `${i.title} ${clientNames.get(i.client_id) ?? ""}`,
      })),
      ...(quotes.data ?? []).map((q) => ({
        key: `qu${q.id}`,
        label: q.number ?? `Draft quotation: ${q.title}`,
        hint: `Quotation · ${clientNames.get(q.client_id) ?? ""} · ${q.title}`,
        to: `/finance/quotations?open=${q.id}`,
        also: `${q.title} ${clientNames.get(q.client_id) ?? ""}`,
      })),
      ...(payouts.data ?? []).map((p) => ({
        key: `po${p.id}`,
        label: p.statement_number,
        hint: `Payout statement · ${names.get(p.person_id) ?? ""}`,
        to: `/payouts?open=${p.id}`,
        also: names.get(p.person_id) ?? "",
      })),
    ];
  }, [isAdmin, people.data, projects.data, orders.data, clients.data, invoices.data, quotes.data, payouts.data, myOrders.data, myDocs.data]);

  const all = isAdmin ? [people, projects, orders, clients, invoices, quotes, payouts] : [myOrders, myDocs];
  return { results, loading: enabled && all.some((q) => q.isPending) };
}

export function GlobalSearch({ isAdmin, nav }: { isAdmin: boolean; nav: NavItem[] }) {
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  // Phones: the box is hidden behind a magnifier button and opens over the top bar.
  const [expanded, setExpanded] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const navigate = useNavigate();
  const listId = useId();
  const index = useIndex(isAdmin, open || !!q);
  const term = q.trim().toLowerCase();

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => ref.current && !ref.current.contains(e.target as Node) && setOpen(false);
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [open]);

  const results = useMemo(() => {
    if (!term) return [];
    const words = term.split(/\s+/);
    const hit = (text: string) => words.every((w) => text.toLowerCase().includes(w));
    const pages = [...nav, SETTINGS_ITEM].filter((i) => hit(i.label)).map((i) => ({ key: i.to, label: i.label, hint: "Page", to: i.to }));
    const found = index.results.filter((r) => hit(`${r.label} ${r.hint} ${r.also ?? ""}`));
    return [...pages, ...found].slice(0, 10);
  }, [term, nav, index.results]);

  useEffect(() => setActive(0), [term]);

  const go = (to: string) => {
    navigate(to);
    setQ("");
    setOpen(false);
    setExpanded(false);
  };
  const collapse = () => {
    setQ("");
    setOpen(false);
    setExpanded(false);
  };

  const optionId = (i: number) => `${listId}-o${i}`;
  return (
    <>
      <button
        type="button"
        className="icon-btn search-toggle"
        aria-label="Search"
        onClick={() => {
          setExpanded(true);
          requestAnimationFrame(() => inputRef.current?.focus());
        }}
      >
        <Search size={20} aria-hidden="true" />
      </button>
      <div className={`search popover-anchor ${expanded ? "is-expanded" : ""}`} ref={ref} role="search">
        <Search size={18} className="muted" aria-hidden="true" />
        <input
          ref={inputRef}
          className="search-input"
          placeholder={isAdmin ? "Search people, projects, Task Orders, invoices" : "Search my Task Orders and documents"}
          aria-label="Search"
          role="combobox"
          aria-expanded={open && !!term}
          aria-controls={listId}
          aria-autocomplete="list"
          aria-activedescendant={open && results[active] ? optionId(active) : undefined}
          value={q}
          onChange={(e) => {
            setQ(e.target.value);
            setOpen(true);
          }}
          onFocus={() => setOpen(true)}
          onKeyDown={(e) => {
            if (e.key === "ArrowDown") {
              e.preventDefault();
              setOpen(true);
              setActive((a) => Math.min(a + 1, results.length - 1));
            } else if (e.key === "ArrowUp") {
              e.preventDefault();
              setActive((a) => Math.max(a - 1, 0));
            } else if (e.key === "Enter" && results[active]) {
              go(results[active].to);
            } else if (e.key === "Escape") {
              if (q) setQ("");
              else {
                (e.target as HTMLInputElement).blur();
                setExpanded(false);
              }
              setOpen(false);
            }
          }}
        />
        {open && term && (
          <div className="popover search-results" id={listId} role="listbox" aria-label="Search results">
            {results.length === 0 ? (
              <p className="empty">{index.loading ? "Searching…" : `No matches for "${q.trim()}".`}</p>
            ) : (
              results.map((r, i) => (
                <button
                  key={r.key}
                  id={optionId(i)}
                  type="button"
                  role="option"
                  aria-selected={i === active}
                  tabIndex={-1}
                  className={`notice ${i === active ? "is-active" : ""}`}
                  onMouseEnter={() => setActive(i)}
                  onClick={() => go(r.to)}
                >
                  <span className="notice-title">{r.label}</span>
                  <span className="notice-detail">{r.hint}</span>
                </button>
              ))
            )}
          </div>
        )}
        {expanded && (
          <button type="button" className="icon-btn search-close" aria-label="Close search" onClick={collapse}>
            <X size={18} aria-hidden="true" />
          </button>
        )}
      </div>
    </>
  );
}
