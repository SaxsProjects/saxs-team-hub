import { useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { Folder, Lock, Search } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router";
import { api, post } from "../../api/client";
import type { AuditEntry, Client, Project, ProjectDetail, Quotation } from "../../api/types";
import { Dialog, ErrorNote, Field, FormError, PageHead, Skeleton, StatCard, Tabs } from "../../components/ui";
import { describeAudit } from "../../lib/activity";
import { plural, rands, shortDay } from "../../lib/format";
import { usePeople } from "../../lib/people";
import { projectRef } from "../member/MyProjects";
import "../overview.css";
import "../pages.css";

export const PROJECT_STATUS: Record<Project["status"], { label: string; cls: string }> = {
  planned: { label: "Planned", cls: "chip-neutral" },
  in_progress: { label: "In progress", cls: "chip-brand" },
  completed: { label: "Completed", cls: "chip-success" },
  cancelled: { label: "Cancelled", cls: "chip-neutral" },
};

type Filter = "all" | "in_progress" | "planned" | "closed";

export function Projects() {
  const projects = useQuery({ queryKey: ["projects"], queryFn: () => api<Project[]>("/api/projects") });
  const quotations = useQuery({ queryKey: ["quotations"], queryFn: () => api<Quotation[]>("/api/quotations") });
  const audit = useQuery({ queryKey: ["audit", "project"], queryFn: () => api<AuditEntry[]>("/api/audit?entity=project&limit=1") });
  const details = useQueries({
    queries: (projects.data ?? []).map((p) => ({ queryKey: ["project", p.id], queryFn: () => api<ProjectDetail>(`/api/projects/${p.id}`) })),
  });
  const people = usePeople();
  const [filter, setFilter] = useState<Filter>("all");
  const [search, setSearch] = useState("");
  const [creating, setCreating] = useState(false);

  if (projects.isError) return <ErrorNote error={projects.error} onRetry={() => projects.refetch()} />;
  const list = projects.data ?? [];
  const detail = new Map(details.flatMap((d) => (d.data ? [[d.data.id, d.data] as const] : [])));
  const isOpen = (p: Project) => p.status === "planned" || p.status === "in_progress";
  const open = list.filter(isOpen);
  const loaded = details.every((d) => d.data);
  const receivedOpen = open.reduce((s, p) => s + (detail.get(p.id)?.received_cents ?? 0), 0);
  const costsOpen = open.reduce((s, p) => s + (detail.get(p.id)?.costs_cents ?? 0), 0);
  const quoteFor = (id: number) => (quotations.data ?? []).filter((q) => q.project_id === id).sort((a, b) => b.id - a.id)[0];
  const q = search.trim().toLowerCase();
  const shown = list
    .filter((p) => (filter === "all" ? true : filter === "closed" ? !isOpen(p) : p.status === filter))
    .filter((p) => !q || `${p.name} ${p.client_name} ${projectRef(p.id)}`.toLowerCase().includes(q));
  const count = (s: Project["status"]) => list.filter((p) => p.status === s).length;
  const latest = audit.data?.[0];

  return (
    <div className="page">
      <PageHead
        title="Projects"
        sub={projects.data ? `${plural(open.length, "open project")} · ${count("in_progress")} in progress · ${count("planned")} planned` : undefined}
      >
        <button className="btn btn-primary" onClick={() => setCreating(true)}>
          New project
        </button>
      </PageHead>

      <div className="stats-3 caps-stats">
        <StatCard label="Open projects" value={projects.data ? open.length : <Skeleton w={40} h={30} />} />
        <StatCard label="Received on open projects" value={loaded && projects.data ? rands(receivedOpen) : <Skeleton w={140} h={30} />} />
        <StatCard label="Direct costs" value={loaded && projects.data ? rands(costsOpen) : <Skeleton w={120} h={30} />} />
      </div>

      <div className="toolbar" style={{ justifyContent: "space-between" }}>
        <Tabs<Filter>
          label="Filter projects"
          value={filter}
          onChange={setFilter}
          tabs={[
            { key: "all", label: "All projects", count: list.length },
            { key: "in_progress", label: "In progress", count: count("in_progress") },
            { key: "planned", label: "Planned", count: count("planned") },
            { key: "closed", label: "Closed", count: list.length - open.length },
          ]}
        />
        <label className="search-box">
          <Search size={15} aria-hidden="true" />
          <input type="search" placeholder="Search projects" aria-label="Search projects" value={search} onChange={(e) => setSearch(e.target.value)} />
        </label>
      </div>

      {projects.isPending && <Skeleton h={200} />}
      {projects.data && shown.length === 0 && (
        <section className="card empty">
          <strong>{list.length ? "No projects match" : "No projects yet"}</strong>
          {list.length ? "Try another filter or search." : "Create a project to track client money, contributors and payouts."}
        </section>
      )}

      <div className="grid-2">
        {shown.map((p) => {
          const d = detail.get(p.id);
          const quote = quoteFor(p.id);
          const lastPay = d?.payments.map((x) => x.received_at).sort().at(-1);
          const locked = d?.contributors.some((c) => c.locked_at);
          return (
            <section key={p.id} className="card project-card">
              <div className="project-head">
                <span className="detail-icon" aria-hidden="true">
                  <Folder size={20} />
                </span>
                <div className="project-name">
                  <h3 className="card-title" style={{ fontSize: 19 }}>
                    {p.name}
                  </h3>
                  <p className="card-sub">
                    {projectRef(p.id)} · {p.client_name}
                  </p>
                </div>
                <span className={`chip ${PROJECT_STATUS[p.status].cls}`}>
                  {p.status === "planned" && quote?.status === "issued" ? "Quoted" : PROJECT_STATUS[p.status].label}
                </span>
              </div>
              <hr className="divider" style={{ margin: "0 22px" }} />
              <div className="money-pair">
                <div>
                  <p className="stat-label caps-label">Client money received</p>
                  <p className="momentum-value num">{d ? rands(d.received_cents) : <Skeleton w={120} h={30} />}</p>
                </div>
                <div>
                  <p className="stat-label caps-label">Direct costs</p>
                  <p className="momentum-value num" style={{ fontSize: 16 }}>
                    {d ? rands(d.costs_cents) : "–"}
                  </p>
                </div>
              </div>
              <div className="contrib-line">
                <div>
                  <p className="setting-title">{d ? plural(d.contributors.length, "contributor") : "Contributors"}</p>
                  <p className="row-sub">{d?.contributors.map((c) => people.nameOf(c.person_id)).join(" · ") || "None added yet"}</p>
                </div>
                {locked && <Lock size={15} className="success-text" aria-label="Shares locked" />}
              </div>
              <div className="pager">
                <span>
                  {lastPay
                    ? `Last client payment ${shortDay(lastPay)}`
                    : quote?.status === "issued" && quote.valid_until
                      ? `Quotation valid until ${shortDay(quote.valid_until)}`
                      : quote?.status === "draft"
                        ? "Quotation in draft"
                        : "No client payments yet"}
                </span>
                <Link className="link-btn" to={`/projects/${p.id}`}>
                  Open project
                </Link>
              </div>
            </section>
          );
        })}
      </div>

      {latest && (
        <div className="banner" style={{ justifyContent: "space-between", alignItems: "center" }}>
          <div>
            <p className="banner-title brand-text" style={{ fontSize: 11 }}>
              Recent update
            </p>
            <p className="banner-sub" style={{ color: "var(--ink)", fontSize: 12 }}>
              {describeAudit(latest).title}
              {latest.entity_id ? ` · ${list.find((p) => p.id === latest.entity_id)?.name ?? projectRef(latest.entity_id)}` : ""} · {shortDay(latest.at)}
            </p>
          </div>
          <Link className="link-btn" to="/audit?entity=project">
            View project history
          </Link>
        </div>
      )}

      {creating && <NewProject onClose={() => setCreating(false)} />}
    </div>
  );
}

function NewProject({ onClose }: { onClose: () => void }) {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const clients = useQuery({ queryKey: ["clients"], queryFn: () => api<Client[]>("/api/clients") });
  const [f, setF] = useState({ name: "", client_name: "", description: "" });
  const [error, setError] = useState<unknown>(null);
  const create = useMutation({
    mutationFn: () => post<Project>("/api/projects", { name: f.name.trim(), client_name: f.client_name.trim(), description: f.description.trim() || null }),
    onSuccess: (p) => {
      qc.invalidateQueries({ queryKey: ["projects"] });
      navigate(`/projects/${p.id}`);
    },
    onError: setError,
  });

  function submit(e: FormEvent) {
    e.preventDefault();
    if (f.name.trim().length < 2 || f.client_name.trim().length < 2) return setError("Add the project name and the client.");
    setError(null);
    create.mutate();
  }

  return (
    <Dialog title="New project" onClose={onClose}>
      <form onSubmit={submit} noValidate style={{ display: "grid", gap: 14 }}>
        <Field id="p-name" label="Project name">
          <input id="p-name" className="input" value={f.name} maxLength={200} onChange={(e) => setF({ ...f, name: e.target.value })} autoFocus />
        </Field>
        <Field id="p-client" label="Client" hint="Pick a saved client or type a new name.">
          <input id="p-client" className="input" list="client-names" value={f.client_name} maxLength={200} onChange={(e) => setF({ ...f, client_name: e.target.value })} />
          <datalist id="client-names">
            {(clients.data ?? []).map((c) => (
              <option key={c.id} value={c.name} />
            ))}
          </datalist>
        </Field>
        <Field id="p-desc" label="Description (optional)">
          <textarea id="p-desc" className="input textarea" value={f.description} maxLength={5000} onChange={(e) => setF({ ...f, description: e.target.value })} />
        </Field>
        <FormError error={error} />
        <div className="form-actions">
          <button type="button" className="btn btn-secondary" onClick={onClose}>
            Cancel
          </button>
          <button className="btn btn-primary" disabled={create.isPending}>
            {create.isPending ? "Creating…" : "Create project"}
          </button>
        </div>
      </form>
    </Dialog>
  );
}
