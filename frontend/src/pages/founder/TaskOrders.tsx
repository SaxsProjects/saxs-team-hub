import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Clock, FileText } from "lucide-react";
import { useState, type FormEvent } from "react";
import { api, post } from "../../api/client";
import type { FounderTaskOrder, TaskOrderStatus } from "../../api/types";
import { Dialog, Done, EmptyRow, ErrorNote, Field, FormError, LoadingRow, PageHead, Pager, RowButton, StatCard, Tabs, paginate, useSelectedFromUrl } from "../../components/ui";
import { fullDay, parseRands, plural, rands, shortDay, todaySA } from "../../lib/format";
import { WORKING_STAGES, usePeople } from "../../lib/people";
import "../overview.css";
import "../pages.css";

const STATUS: Record<TaskOrderStatus, { label: string; cls: string }> = {
  proposed: { label: "Proposed", cls: "chip-warning" },
  confirmed: { label: "Confirmed", cls: "chip-neutral" },
  submitted: { label: "Submitted", cls: "chip-brand" },
  accepted: { label: "Accepted", cls: "chip-success" },
  declined: { label: "Declined", cls: "chip-neutral" },
  cancelled: { label: "Cancelled", cls: "chip-neutral" },
};

type Filter = "all" | "submitted" | "confirmed" | "proposed";

/** A delivery note starts with "Delivery link: https://…" when the member added one. */
function splitSubmission(note: string | null): { link: string | null; text: string } {
  const m = note?.match(/^Delivery link: (https?:\/\/\S+)\s*/);
  return m ? { link: m[1]!, text: note!.slice(m[0].length) } : { link: null, text: note ?? "" };
}

export function TaskOrders() {
  const qc = useQueryClient();
  const orders = useQuery({ queryKey: ["task-orders"], queryFn: () => api<FounderTaskOrder[]>("/api/task-orders") });
  const people = usePeople();
  const [filter, setFilter] = useState<Filter>("all");
  const [page, setPage] = useState(0);
  const [selectedId, setSelectedId] = useSelectedFromUrl();
  const [creating, setCreating] = useState(false);
  const [done, setDone] = useState<string | null>(null);

  if (orders.isError) return <ErrorNote error={orders.error} onRetry={() => orders.refetch()} />;
  const all = [...(orders.data ?? [])].sort((a, b) => b.id - a.id);
  const count = (s: TaskOrderStatus) => all.filter((t) => t.status === s).length;
  const filtered = filter === "all" ? all : all.filter((t) => t.status === filter);
  const view = paginate(filtered, page);
  const selected = all.find((t) => t.id === selectedId) ?? filtered.find((t) => t.status === "submitted") ?? filtered[0];
  const waiting = all.filter((t) => t.status === "submitted");
  const firstDue = waiting.map((t) => t.review_due_on).filter(Boolean).sort()[0];
  const refresh = () => {
    for (const k of ["task-orders", "dashboard", "payouts"]) qc.invalidateQueries({ queryKey: [k] });
  };

  return (
    <div className="page">
      <PageHead
        title="Task Orders"
        sub={orders.data ? `${plural(all.length, "Task Order")} · ${plural(waiting.length, "submission")} awaiting review` : undefined}
      >
        <button className="btn btn-primary" onClick={() => (setDone(null), setCreating(true))}>
          New Task Order
        </button>
      </PageHead>
      <Done text={done} />

      <div className="stats-4 caps-stats">
        <StatCard label="To confirm" value={orders.data ? count("proposed") : "–"} />
        <StatCard label="In progress" value={orders.data ? count("confirmed") : "–"} />
        <StatCard label="Awaiting review" value={orders.data ? count("submitted") : "–"} />
        <StatCard label="Accepted" value={orders.data ? count("accepted") : "–"} />
      </div>

      <Tabs<Filter>
        label="Filter Task Orders"
        value={filter}
        onChange={(f) => (setFilter(f), setPage(0), setSelectedId(null))}
        tabs={[
          { key: "all", label: "All", count: all.length },
          { key: "submitted", label: "To review", count: count("submitted") },
          { key: "confirmed", label: "In progress", count: count("confirmed") },
          { key: "proposed", label: "Proposed", count: count("proposed") },
        ]}
      />

      <div className="split">
        <div className="stack">
          <section className="card">
            <div className="card-head">
              <h3 className="card-title">Task Order register</h3>
              <span className="th-note">Newest first</span>
            </div>
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>Task Order</th>
                    <th className="hide-sm">Contractor</th>
                    <th>Fee</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {orders.isPending && <LoadingRow cols={4} />}
                  {orders.data && filtered.length === 0 && <EmptyRow cols={4} text="No Task Orders here yet." />}
                  {view.rows.map((t) => (
                    <RowButton key={t.id} selected={t.id === selected?.id} onSelect={() => setSelectedId(t.id)}>
                      <td>
                        <p className="row-sub num" style={{ marginTop: 0 }}>
                          {t.number}
                        </p>
                        <p className="row-title">{t.title}</p>
                      </td>
                      <td className="hide-sm">{people.nameOf(t.person_id)}</td>
                      <td className="num cell-main">{rands(t.fee_cents)}</td>
                      <td>
                        <span className={`chip ${STATUS[t.status].cls}`}>{STATUS[t.status].label}</span>
                      </td>
                    </RowButton>
                  ))}
                </tbody>
              </table>
            </div>
            {orders.data && filtered.length > 0 && (
              <Pager page={view.page} pages={view.pages} total={filtered.length} shown={view.rows.length} noun="Task Orders" onPage={setPage} />
            )}
          </section>

          {waiting.length > 0 && (
            <div className="banner warning">
              <Clock size={18} aria-hidden="true" />
              <div>
                <p className="banner-title">
                  {plural(waiting.length, "review")} due{firstDue ? ` by ${fullDay(firstDue).replace(/ \d{4}$/, "")}` : ""}
                </p>
                <p className="banner-sub">Accept or request changes within the 5-day review window.</p>
              </div>
            </div>
          )}
        </div>

        {selected && (
          <ReviewPanel
            key={selected.id}
            order={selected}
            person={people.nameOf(selected.person_id)}
            onDone={(msg) => (refresh(), setDone(msg))}
          />
        )}
      </div>

      {creating && (
        <NewTaskOrder
          people={(people.data ?? []).filter((p) => WORKING_STAGES.has(p.status))}
          onClose={() => setCreating(false)}
          onCreated={(t) => (refresh(), setCreating(false), setSelectedId(t.id), setFilter("all"), setDone(`${t.number} sent to ${people.nameOf(t.person_id)} to confirm.`))}
        />
      )}
    </div>
  );
}

function ReviewPanel({ order: t, person, onDone }: { order: FounderTaskOrder; person: string; onDone: (msg: string) => void }) {
  const [feedback, setFeedback] = useState("");
  const [error, setError] = useState<unknown>(null);
  const accept = useMutation({
    mutationFn: () => post(`/api/task-orders/${t.id}/accept`, { note: feedback.trim() || null }),
    onSuccess: () => onDone(`${t.number} accepted. The fee is on the payouts list.`),
    onError: setError,
  });
  const changes = useMutation({
    mutationFn: () => post(`/api/task-orders/${t.id}/request-changes`, { note: feedback.trim() }),
    onSuccess: () => onDone(`Changes requested on ${t.number}.`),
    onError: setError,
  });
  const cancel = useMutation({
    mutationFn: () => post(`/api/task-orders/${t.id}/cancel`, { note: feedback.trim() }),
    onSuccess: () => onDone(`${t.number} cancelled.`),
    onError: setError,
  });
  const sub = splitSubmission(t.submission_note);
  const needNote = (fn: () => void) => () => {
    if (feedback.trim().length < 3) return setError("Write a short note for the contractor first.");
    setError(null);
    fn();
  };
  const busy = accept.isPending || changes.isPending || cancel.isPending;
  const open = t.status === "proposed" || t.status === "confirmed";

  return (
    <section className="card" aria-label="Task Order details">
      <div className="card-head">
        <h3 className="card-title">{t.status === "submitted" ? "Review submission" : "Task Order"}</h3>
        <span className={`chip ${STATUS[t.status].cls}`}>{STATUS[t.status].label}</span>
      </div>
      <hr className="divider" />
      <div className="detail">
        <span className="detail-ref num">{t.number}</span>
        <h3 className="detail-title" style={{ marginTop: 6, fontSize: 22 }}>
          {t.title}
        </h3>
        <div className="detail-meta">
          <strong>{person}</strong>
          <span className="detail-note">
            {t.submitted_at ? `Submitted ${fullDay(t.submitted_at)}` : `Due ${fullDay(t.due_on)}`}
          </span>
        </div>
        <dl className="kv" style={{ marginTop: 16 }}>
          <div>
            <dt>Fee</dt>
            <dd style={{ fontSize: 15 }}>{rands(t.fee_cents)}</dd>
          </div>
          {t.review_due_on && t.status === "submitted" && (
            <div>
              <dt>Review by</dt>
              <dd className={t.review_overdue ? "warning-text" : "warning-text"}>{shortDay(t.review_due_on)}</dd>
            </div>
          )}
          {t.accepted_on && (
            <div>
              <dt>Accepted</dt>
              <dd>{shortDay(t.accepted_on)}</dd>
            </div>
          )}
        </dl>
        <hr className="divider" />
        <p className="detail-h">Deliverable</p>
        <p className="detail-p">{t.deliverable}</p>
        {(sub.link || sub.text) && (
          <div className="detail-section">
            <p className="detail-h">Submission</p>
            {sub.link && (
              <a className="file-tile" href={sub.link} target="_blank" rel="noopener noreferrer">
                <FileText size={18} className="doc-icon" aria-hidden="true" />
                <span className="row-title" style={{ wordBreak: "break-all" }}>
                  {sub.link.replace(/^https?:\/\//, "")}
                </span>
              </a>
            )}
            {sub.text && (
              <p className="detail-p" style={{ marginTop: 8 }}>
                {sub.text}
              </p>
            )}
          </div>
        )}
        {(t.review_note || t.closed_reason) && (
          <div className="detail-section">
            <p className="detail-h">{t.closed_reason ? "Reason" : "Last feedback"}</p>
            <p className="detail-p">{t.closed_reason ?? t.review_note}</p>
          </div>
        )}
        {(t.status === "submitted" || open) && (
          <div className="detail-section">
            <Field id="feedback" label={t.status === "submitted" ? "Feedback" : "Reason (needed to cancel)"}>
              <textarea
                id="feedback"
                className="input textarea"
                placeholder={t.status === "submitted" ? "Add a note for the contractor" : "Why is this Task Order cancelled?"}
                value={feedback}
                maxLength={5000}
                onChange={(e) => setFeedback(e.target.value)}
              />
            </Field>
          </div>
        )}
        <FormError error={error} />
        {t.status === "submitted" && (
          <div className="form-row" style={{ marginTop: 16, gap: 10 }}>
            <button className="btn btn-primary" disabled={busy} onClick={() => (setError(null), accept.mutate())}>
              Accept delivery
            </button>
            <button className="btn btn-secondary" disabled={busy} onClick={needNote(() => changes.mutate())}>
              Request changes
            </button>
          </div>
        )}
        {open && (
          <div className="detail-actions">
            <button className="btn btn-secondary" disabled={busy} onClick={needNote(() => cancel.mutate())}>
              Cancel Task Order
            </button>
          </div>
        )}
      </div>
    </section>
  );
}

function NewTaskOrder({ people, onClose, onCreated }: { people: { id: number; full_name: string }[]; onClose: () => void; onCreated: (t: FounderTaskOrder) => void }) {
  const [f, setF] = useState({ person_id: "", title: "", deliverable: "", fee: "", due_on: "" });
  const [error, setError] = useState<unknown>(null);
  const create = useMutation({
    mutationFn: (body: object) => post<FounderTaskOrder>("/api/task-orders", body),
    onSuccess: onCreated,
    onError: setError,
  });
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });

  function submit(e: FormEvent) {
    e.preventDefault();
    const fee = parseRands(f.fee);
    if (!f.person_id) return setError("Choose who the Task Order is for.");
    if (f.title.trim().length < 3 || f.deliverable.trim().length < 3) return setError("Add a title and describe the deliverable.");
    if (!fee) return setError("Enter the fee in rand, for example 450.");
    if (!f.due_on || f.due_on < todaySA()) return setError("Choose a due date from today onwards.");
    setError(null);
    create.mutate({ person_id: Number(f.person_id), title: f.title.trim(), deliverable: f.deliverable.trim(), fee_cents: fee, due_on: f.due_on });
  }

  return (
    <Dialog title="New Task Order" onClose={onClose}>
      <form onSubmit={submit} noValidate style={{ display: "grid", gap: 14 }}>
        <Field id="to-person" label="Contractor" hint={people.length === 0 ? "Only people who accepted an offer can get Task Orders." : undefined}>
          <select id="to-person" className="input" value={f.person_id} onChange={set("person_id")}>
            <option value="">Choose a person</option>
            {people.map((p) => (
              <option key={p.id} value={p.id}>
                {p.full_name}
              </option>
            ))}
          </select>
        </Field>
        <Field id="to-title" label="Title">
          <input id="to-title" className="input" value={f.title} maxLength={200} onChange={set("title")} />
        </Field>
        <Field id="to-deliverable" label="Deliverable">
          <textarea id="to-deliverable" className="input textarea" value={f.deliverable} maxLength={5000} onChange={set("deliverable")} />
        </Field>
        <div className="form-row" style={{ gap: 14 }}>
          <Field id="to-fee" label="Fee (R)" hint="Usually R150–R500">
            <input id="to-fee" className="input" inputMode="decimal" placeholder="450.00" value={f.fee} onChange={set("fee")} />
          </Field>
          <Field id="to-due" label="Due date">
            <input id="to-due" className="input" type="date" min={todaySA()} value={f.due_on} onChange={set("due_on")} />
          </Field>
        </div>
        <FormError error={error} />
        <div className="form-actions">
          <button type="button" className="btn btn-secondary" onClick={onClose}>
            Cancel
          </button>
          <button className="btn btn-primary" disabled={create.isPending}>
            {create.isPending ? "Sending…" : "Send to confirm"}
          </button>
        </div>
      </form>
    </Dialog>
  );
}
