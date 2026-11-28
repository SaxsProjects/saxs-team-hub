import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Lock } from "lucide-react";
import { Link } from "react-router";
import { api, post } from "../api/client";
import type { MemberOverview, MyProject, OnboardingItem, Payout, TaskOrder } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { AssistantPanel } from "../components/Assistant";
import { ErrorNote, Skeleton, StatCard } from "../components/ui";
import { firstName, greeting, longDate, percent, rands, shortDate } from "../lib/format";
import "./overview.css";

const TASK_CHIP: Partial<Record<TaskOrder["status"], { label: string; cls: string }>> = {
  proposed: { label: "Awaiting confirmation", cls: "chip-warning" },
  confirmed: { label: "In progress", cls: "chip-brand" },
  submitted: { label: "Submitted for review", cls: "chip-neutral" },
};

function fullDate(day: string): string {
  return new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "Africa/Johannesburg" }).format(
    new Date(`${day}T12:00:00Z`),
  );
}

export function MyWorkspace() {
  const { me } = useAuth();
  const qc = useQueryClient();
  const overview = useQuery({ queryKey: ["me-overview"], queryFn: () => api<MemberOverview>("/api/me/overview") });
  const tasks = useQuery({ queryKey: ["me-task-orders"], queryFn: () => api<TaskOrder[]>("/api/me/task-orders") });
  const onboarding = useQuery({ queryKey: ["me-onboarding"], queryFn: () => api<OnboardingItem[]>("/api/me/onboarding") });
  const payouts = useQuery({ queryKey: ["me-payouts"], queryFn: () => api<Payout[]>("/api/me/payouts") });
  const projects = useQuery({ queryKey: ["me-projects"], queryFn: () => api<MyProject[]>("/api/me/projects") });

  const refresh = () => {
    for (const k of ["me-overview", "me-task-orders", "me-payouts", "me-onboarding"]) qc.invalidateQueries({ queryKey: [k] });
  };
  const confirm = useMutation({ mutationFn: (id: number) => post<TaskOrder>(`/api/me/task-orders/${id}/confirm`), onSuccess: refresh });
  const requestPay = useMutation({
    mutationFn: (id: number) => post<Payout>(`/api/me/payouts/${id}/request-payment`),
    onSuccess: refresh,
  });
  const tick = useMutation({
    mutationFn: (id: number) => api<OnboardingItem>(`/api/me/onboarding/${id}`, { method: "PATCH", body: JSON.stringify({ done: true }) }),
    onSuccess: refresh,
  });

  if (overview.isError) return <ErrorNote error={overview.error} onRetry={() => overview.refetch()} />;
  const o = overview.data;
  const today = o?.today ?? new Date().toISOString().slice(0, 10);
  const name = firstName(me?.full_name) || "there";

  const items = [...(onboarding.data ?? [])].sort((a, b) => a.position - b.position);
  const done = items.filter((i) => i.done).length;
  const nextItem = items.find((i) => !i.done);
  const openTasks = (tasks.data ?? []).filter((t) => t.status in TASK_CHIP).slice(0, 3);
  const unpaid = (payouts.data ?? []).filter((p) => !p.paid_at).slice(0, 4);
  const projectName = new Map((projects.data ?? []).map((p) => [p.project_id, p.project]));
  const firstProject = projects.data?.[0];
  const actionError = confirm.error ?? requestPay.error ?? tick.error;

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h2 className="page-greeting">
            {greeting()}, {name}.
          </h2>
          <p className="page-date">{longDate(today)}</p>
        </div>
        <Link to="/settings" className="btn btn-secondary">
          View my profile
        </Link>
      </div>
      {!!actionError && <ErrorNote error={actionError} />}

      <AssistantPanel limit={4} />

      <div className="grid-2-1">
        <section className="card focus-card">
          <div>
            <span className="chip chip-strong">{nextItem ? "Onboarding" : "Today’s focus"}</span>
            {o === undefined ? (
              <Skeleton w={260} h={28} />
            ) : nextItem ? (
              <>
                <p className="focus-title">Finish your onboarding</p>
                <p className="focus-sub">{nextItem.item} to complete setup.</p>
              </>
            ) : o.task_orders_to_confirm ? (
              <>
                <p className="focus-title">Confirm your new Task Order{o.task_orders_to_confirm > 1 ? "s" : ""}</p>
                <p className="focus-sub">Accept the work before you start.</p>
              </>
            ) : (
              <>
                <p className="focus-title">You’re all set</p>
                <p className="focus-sub">New work and payouts will show up here.</p>
              </>
            )}
          </div>
        </section>
        <section className="card momentum-card due-card">
          <p className="stat-label caps">Payouts due</p>
          <p className="momentum-value num">{o ? rands(o.due_now_cents) : <Skeleton w={140} h={36} />}</p>
          <p className="momentum-sub">{o?.can_request_payment_count ? "Due now · ready to request" : "Due now"}</p>
        </section>
      </div>

      <div className="stats-4">
        <StatCard label="Total owed" value={o ? rands(o.owed_cents) : <Skeleton w={120} h={30} />} note="Due now + upcoming" />
        <StatCard
          label="Coming up next"
          value={o ? rands(Math.max(0, o.owed_cents - o.due_now_cents - o.waiting_for_first_payment_cents)) : <Skeleton w={120} h={30} />}
          note={o?.next_due_on ? `Due ${longDate(o.next_due_on).replace(/^\w+, /, "")}` : "Nothing scheduled"}
        />
        <StatCard label="Paid this year" value={o ? rands(o.paid_this_year_cents) : <Skeleton w={120} h={30} />} note="Year to date" />
        <StatCard label="Your current rate" value={o ? percent(o.current_rate_bp) : <Skeleton w={60} h={30} />} note="Revenue share" />
      </div>

      <div className="grid-2-1">
        <section className="card">
          <div className="card-head">
            <div>
              <h3 className="card-title" style={{ fontSize: 18 }}>
                Task Orders
              </h3>
              <p className="card-sub">My Task Orders</p>
            </div>
            <Link to="/my/task-orders" className="link-btn">
              View all tasks
            </Link>
          </div>
          <hr className="divider" />
          {tasks.isPending && <Skeleton h={60} />}
          {tasks.data && openTasks.length === 0 && <p className="empty">No open Task Orders.</p>}
          <ul className="task-list">
            {openTasks.map((t) => {
              const chip = TASK_CHIP[t.status]!;
              return (
                <li key={t.id} className="task">
                  <div className="task-text">
                    <p className="task-title">{t.title}</p>
                    <p className="task-meta num">
                      {t.number} · {rands(t.fee_cents)} · Due {shortDate(t.due_on)}
                    </p>
                  </div>
                  <span className={`chip ${chip.cls}`}>{chip.label}</span>
                  {t.status === "proposed" && (
                    <button className="btn btn-primary" onClick={() => confirm.mutate(t.id)} disabled={confirm.isPending}>
                      Confirm task
                    </button>
                  )}
                  {t.status === "confirmed" && (
                    <Link to="/my/task-orders" className="btn btn-secondary">
                      Submit work
                    </Link>
                  )}
                </li>
              );
            })}
          </ul>
        </section>

        <section className="card">
          <div className="card-head">
            <h3 className="card-title">Onboarding</h3>
            <span className="chip chip-success">
              {done} of {items.length}
            </span>
          </div>
          <hr className="divider" />
          <ul className="checklist">
            {items.map((i) => (
              <li key={i.id} className={i.done ? "done" : i === nextItem ? "next" : ""}>
                <span className="check-dot" aria-hidden="true">
                  {i.done ? <Check size={12} strokeWidth={3} /> : i.position}
                </span>
                <span>{i.item}</span>
                <span className="sr-only">{i.done ? "(done)" : "(to do)"}</span>
              </li>
            ))}
          </ul>
          {nextItem && (
            <div className="card-foot">
              {nextItem.member_can_complete ? (
                <button className="btn btn-primary btn-block" onClick={() => tick.mutate(nextItem.id)} disabled={tick.isPending}>
                  Mark “{nextItem.item}” done
                </button>
              ) : (
                <p className="card-sub">The founder confirms the next step.</p>
              )}
            </div>
          )}
        </section>
      </div>

      <div className="grid-2-1">
        <section className="card">
          <div className="card-head">
            <h3 className="card-title">My payouts</h3>
            <Link to="/my/payouts" className="link-btn">
              All payouts &amp; statements
            </Link>
          </div>
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Payout</th>
                  <th>Amount</th>
                  <th>Due date</th>
                  <th>Next step</th>
                </tr>
              </thead>
              <tbody>
                {payouts.data && unpaid.length === 0 && (
                  <tr>
                    <td colSpan={4} className="empty">
                      No unpaid payouts.
                    </td>
                  </tr>
                )}
                {unpaid.map((p) => {
                  const due = !!p.due_at && p.due_at <= today;
                  return (
                    <tr key={p.id}>
                      <td>
                        <div className="cell-main">
                          {p.kind === "task_fee" ? "Task fee" : (projectName.get(p.project_id ?? -1) ?? "Project share")}
                        </div>
                        <div className="cell-sub">{p.statement_number}</div>
                      </td>
                      <td className="num cell-main">{rands(p.amount_cents)}</td>
                      <td>
                        {p.due_at ? fullDate(p.due_at) : "After first client payment"}
                        {due && <div className="cell-sub">Due now</div>}
                      </td>
                      <td>
                        {due && !p.payment_requested_at ? (
                          <button className="btn btn-primary" onClick={() => requestPay.mutate(p.id)} disabled={requestPay.isPending}>
                            Request payment
                          </button>
                        ) : (
                          <span className={`chip ${due ? "chip-success" : "chip-neutral"}`}>{due ? "Requested" : "Upcoming"}</span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </section>

        <section className="card">
          {firstProject ? (
            <>
              <div className="card-head">
                <div>
                  <h3 className="card-title" style={{ fontSize: 16 }}>
                    {firstProject.project}
                  </h3>
                  <p className="card-sub">Your agreed project share</p>
                </div>
              </div>
              <hr className="divider" />
              <dl className="share-list">
                <div>
                  <dt>Revenue-share rate</dt>
                  <dd>{percent(firstProject.current_rate_bp)}</dd>
                </div>
                <div>
                  <dt>Your work share</dt>
                  <dd>{percent(firstProject.work_share_bp)}</dd>
                </div>
              </dl>
              {firstProject.locked_at && (
                <p className="locked-note">
                  <Lock size={14} aria-hidden="true" /> Shares locked for this project
                </p>
              )}
              <p className="formula">(Client money − costs) × rate × work share.</p>
            </>
          ) : (
            <p className="empty">
              <strong>No projects yet</strong>Projects you’re added to will appear here.
            </p>
          )}
        </section>
      </div>
    </div>
  );
}
