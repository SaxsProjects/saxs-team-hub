import { useQueries, useQuery } from "@tanstack/react-query";
import { Check, Clock, Eye, Plus, type LucideIcon } from "lucide-react";
import { Link } from "react-router";
import { api } from "../api/client";
import { useViewFile } from "../components/DocumentPreview";
import type { AuditEntry, Dashboard, Project, TaskOrder } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { AssistantPanel, VatCard } from "../components/Assistant";
import { ErrorNote, Skeleton, StatCard } from "../components/ui";
import { describeAudit } from "../lib/activity";
import { clock, dayMonth, firstName, greeting, longDate, plural, rands, shortDate } from "../lib/format";
import "./overview.css";

interface ProjectDetail extends Project {
  contributors: { person_id: number }[];
  received_cents: number;
}

const ACTIVE = new Set(["planned", "in_progress"]);
/** People who have accepted an offer, i.e. who count toward "team members onboarded". */
const ON_TEAM = ["accepted", "agreement_signed", "onboarded"];

const STATUS_CHIP: Record<Project["status"], { label: string; cls: string }> = {
  in_progress: { label: "In progress", cls: "chip-brand" },
  planned: { label: "Quoted", cls: "chip-neutral" },
  completed: { label: "Completed", cls: "chip-success" },
  cancelled: { label: "Cancelled", cls: "chip-neutral" },
};

export function FounderOverview() {
  const { me } = useAuth();
  const dash = useQuery({ queryKey: ["dashboard"], queryFn: () => api<Dashboard>("/api/dashboard") });
  const reviews = useQuery({
    queryKey: ["task-orders", "submitted"],
    queryFn: () => api<TaskOrder[]>("/api/task-orders?status_filter=submitted"),
  });
  const projects = useQuery({ queryKey: ["projects"], queryFn: () => api<Project[]>("/api/projects") });
  const activity = useQuery({ queryKey: ["audit", 4], queryFn: () => api<AuditEntry[]>("/api/audit?scope=workspace&limit=4") });

  const inMotion = (projects.data ?? []).filter((p) => ACTIVE.has(p.status)).slice(0, 5);
  const details = useQueries({
    queries: inMotion.map((p) => ({
      queryKey: ["project", p.id],
      queryFn: () => api<ProjectDetail>(`/api/projects/${p.id}`),
    })),
  });

  const d = dash.data;
  const today = d?.today ?? new Date();
  const name = firstName(me?.full_name) || "Phathutshedzo";

  if (dash.isError) return <ErrorNote error={dash.error} onRetry={() => dash.refetch()} />;

  const toReview = reviews.data ?? [];
  const reviewBy = toReview
    .map((t) => t.review_due_on)
    .filter((x): x is string => !!x)
    .sort()[0];
  const team = d ? ON_TEAM.reduce((n, s) => n + (d.people_by_status[s] ?? 0), 0) : 0;
  const onboarded = d?.people_by_status.onboarded ?? 0;
  const settling = team - onboarded;
  const active = (projects.data ?? []).filter((p) => ACTIVE.has(p.status));
  const inProgress = active.filter((p) => p.status === "in_progress").length;

  const attention: AttentionItem[] = [];
  if (toReview.length)
    attention.push({
      key: "reviews",
      icon: Check,
      tone: "brand",
      title: `Review ${plural(toReview.length, "Task Order")}`,
      detail: "Submitted work is ready for your feedback.",
      action: "Review",
      to: "/task-orders",
      when: reviewBy ? `By ${shortDate(reviewBy)}` : "",
    });
  if (d?.invoices.overdue_count)
    attention.push({
      key: "overdue",
      icon: Clock,
      tone: "warning",
      title: `Follow up ${d.invoices.overdue_count === 1 ? "an overdue invoice" : `${d.invoices.overdue_count} overdue invoices`}`,
      detail: `${rands(d.invoices.overdue_cents)} outstanding`,
      action: "View invoices",
      to: "/finance",
      when: "Overdue",
    });
  if (d && settling > 0)
    attention.push({
      key: "settle",
      icon: Plus,
      tone: "success",
      title: `Help ${plural(settling, "person", "people")} get settled`,
      detail: "Onboarding steps still to confirm.",
      action: "Onboarding",
      to: "/team",
      when: plural(settling, "person", "people"),
    });
  if (d?.quotations_awaiting_answer)
    attention.push({
      key: "quotes",
      icon: Clock,
      tone: "brand",
      title: `${plural(d.quotations_awaiting_answer, "quotation")} awaiting the client`,
      detail: "Issued and not yet accepted or declined.",
      action: "Quotations",
      to: "/finance",
      when: "",
    });

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h2 className="page-greeting">
            {greeting()}, {name}.
          </h2>
          <p className="page-date">{longDate(today)}</p>
        </div>
        <Link to="/finance" className="btn btn-primary">
          <Plus size={16} aria-hidden="true" /> Record client payment
        </Link>
      </div>

      <div className="grid-2-1">
        <section className="card focus-card">
          <div>
            <span className="chip chip-strong">Today’s focus</span>
            {reviews.isPending ? (
              <Skeleton w={280} h={28} />
            ) : toReview.length ? (
              <>
                <p className="focus-title">{plural(toReview.length, "Task Order")} ready for review</p>
                <p className="focus-sub">{reviewBy ? `Review by ${dayMonth(reviewBy)}` : "Waiting for your review"}</p>
              </>
            ) : (
              <>
                <p className="focus-title">Nothing waiting for review</p>
                <p className="focus-sub">Submitted Task Orders will show up here.</p>
              </>
            )}
          </div>
          {toReview.length > 0 && (
            <Link to="/task-orders" className="btn btn-primary btn-lg">
              Review work
            </Link>
          )}
        </section>
        <section className="card momentum-card">
          <p className="momentum-label">Team onboarding</p>
          <p className="momentum-line">
            <span className="momentum-value num">{d ? `${onboarded} of ${team}` : "–"}</span>
            <span className="momentum-sub">team members fully onboarded</span>
          </p>
          <div className="momentum-bars" role="img" aria-label={`${onboarded} of ${team} onboarded`}>
            {Array.from({ length: Math.max(team, 1) }, (_, i) => (
              <span key={i} className={i < onboarded ? "on" : ""} />
            ))}
          </div>
        </section>
      </div>

      <div className="grid-2-1">
        <AssistantPanel />
        <VatCard vat={d?.vat} />
      </div>

      <div className="stats-4">
        <StatCard
          label="Client money received"
          value={d ? rands(d.received_this_year_cents) : <Skeleton w={140} h={30} />}
          note="Year to date · excluding VAT"
        />
        <StatCard
          label="Outstanding invoices"
          value={d ? rands(d.invoices.outstanding_cents) : <Skeleton w={140} h={30} />}
          note={d?.invoices.overdue_cents ? `${rands(d.invoices.overdue_cents)} overdue` : `${plural(d?.invoices.outstanding_count ?? 0, "invoice")} open`}
          noteTone={d?.invoices.overdue_cents ? "warning" : undefined}
        />
        <StatCard
          label="Payouts due now"
          value={d ? rands(d.payouts.due_now_cents) : <Skeleton w={140} h={30} />}
          note={`${plural(d?.payouts.due_now_count ?? 0, "payout")} · ${d?.payouts.payment_requested_count ?? 0} requested`}
        />
        <StatCard
          label="Active projects"
          value={projects.data ? active.length : <Skeleton w={30} h={30} />}
          note={`${inProgress} in progress · ${active.length - inProgress} quoted`}
        />
      </div>

      <div className="grid-2-1">
        <section className="card">
          <div className="card-head">
            <h3 className="card-title">Needs your attention</h3>
            <span className="chip chip-neutral">{attention.length} open</span>
          </div>
          <hr className="divider" />
          {attention.length === 0 ? (
            <p className="empty">
              <strong>All clear</strong>Nothing needs you right now.
            </p>
          ) : (
            <ul className="attention-list">
              {attention.map((a) => (
                <Attention key={a.key} item={a} />
              ))}
            </ul>
          )}
        </section>
        <PayoutsReady dash={d} />
      </div>

      <div className="grid-2-1">
        <section className="card">
          <div className="card-head">
            <h3 className="card-title">Projects in motion</h3>
            <Link to="/projects" className="link-btn">
              All projects
            </Link>
          </div>
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Project</th>
                  <th>Status</th>
                  <th>Received</th>
                  <th>Team</th>
                </tr>
              </thead>
              <tbody>
                {projects.isPending && (
                  <tr>
                    <td colSpan={4}>
                      <Skeleton h={30} />
                    </td>
                  </tr>
                )}
                {projects.data && inMotion.length === 0 && (
                  <tr>
                    <td colSpan={4} className="empty">
                      No active projects yet.
                    </td>
                  </tr>
                )}
                {inMotion.map((p, i) => {
                  const detail = details[i]?.data;
                  const chip = STATUS_CHIP[p.status];
                  return (
                    <tr key={p.id}>
                      <td>
                        <Link to={`/projects/${p.id}`} className="cell-main row-link">
                          {p.name}
                        </Link>
                        <div className="cell-sub">
                          SP-{String(p.id).padStart(3, "0")} · {p.client_name}
                        </div>
                      </td>
                      <td>
                        <span className={`chip ${chip.cls}`}>{chip.label}</span>
                      </td>
                      <td className="num" style={{ fontWeight: 500 }}>
                        {detail ? rands(detail.received_cents) : "–"}
                      </td>
                      <td className="muted">{detail ? plural(detail.contributors.length, "person", "people") : "–"}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </section>
        <section className="card">
          <div className="card-head">
            <h3 className="card-title">Recent activity</h3>
            <Link to="/audit" className="link-btn" style={{ fontSize: 11 }}>
              View history
            </Link>
          </div>
          <ol className="timeline">
            {activity.isPending && <Skeleton h={40} />}
            {activity.data?.length === 0 && <p className="empty">No activity yet.</p>}
            {activity.data?.map((a) => {
              const info = describeAudit(a);
              return (
                <li key={a.id} className={`tl-item tone-${info.tone}`}>
                  <p className="tl-title">{info.title}</p>
                  <p className="tl-sub">
                    {info.detail ? `${info.detail} · ` : ""}
                    {shortDate(a.at)} {clock(a.at)}
                  </p>
                </li>
              );
            })}
          </ol>
        </section>
      </div>
    </div>
  );
}

interface AttentionItem {
  key: string;
  icon: LucideIcon;
  tone: "brand" | "warning" | "success";
  title: string;
  detail: string;
  action: string;
  to: string;
  when: string;
}

function Attention({ item }: { item: AttentionItem }) {
  const Icon = item.icon;
  return (
    <li className="attention">
      <span className={`attention-icon tone-${item.tone}`} aria-hidden="true">
        <Icon size={20} strokeWidth={1.75} />
      </span>
      <div className="attention-text">
        <p className="attention-title">{item.title}</p>
        <p className="attention-detail">{item.detail}</p>
      </div>
      <div className="attention-action">
        <Link to={item.to} className="link-btn">
          {item.action}
        </Link>
        {item.when && <p className="attention-when">{item.when}</p>}
      </div>
    </li>
  );
}

function PayoutsReady({ dash }: { dash: Dashboard | undefined }) {
  const view = useViewFile();
  const count = dash?.payouts.due_now_count ?? 0;
  const download = () => view("/api/payment-list.csv", `payment-list-${dash?.today ?? "today"}.csv`, "Payment list");
  return (
    <section className="card payouts-card">
      <h3 className="card-title">Payouts ready</h3>
      <p className="card-sub" style={{ marginTop: 10 }}>
        {plural(count, "due payout")}
      </p>
      <p className="payouts-value num">{dash ? rands(dash.payouts.due_now_cents) : <Skeleton w={150} h={36} />}</p>
      <span className="chip chip-success">{plural(dash?.payouts.payment_requested_count ?? 0, "payment request")}</span>
      <button className="btn btn-primary btn-block payouts-btn" onClick={download} disabled={count === 0}>
        <span>View payment list</span>
        <Eye size={20} aria-hidden="true" />
      </button>
    </section>
  );
}
