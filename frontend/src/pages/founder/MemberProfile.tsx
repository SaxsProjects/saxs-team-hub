import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, FileText, Lock } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Link, useParams } from "react-router";
import { ApiError, api, downloadFile, post } from "../../api/client";
import type { DocumentInfo, MaskedBanking, OnboardingItem, Payout, Person, PersonStage, Pipeline, RatePeriod } from "../../api/types";
import { Dialog, Done, ErrorNote, Field, FormError, Skeleton } from "../../components/ui";
import { fullDay, percent, rands, shortDay, todaySA } from "../../lib/format";
import { STAGE } from "./TeamOffers";
import "../overview.css";
import "../pages.css";

const DOC_TITLE: Record<string, string> = {
  agreement: "Contractor agreement",
  acceptance: "Offer acceptance record",
  offer_pdf: "Offer letter",
  other: "Document",
};

/** Which manual stage move the founder can make next (backend MANUAL_STAGE_MOVES). */
const NEXT_STAGE: Partial<Record<PersonStage, { to: PersonStage; label: string }>> = {
  accepted: { to: "agreement_signed", label: "Mark agreement signed" },
  agreement_signed: { to: "onboarded", label: "Mark as onboarded" },
};

async function maybe<T>(path: string): Promise<T | null> {
  try {
    return await api<T>(path);
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) return null;
    throw e;
  }
}

export function MemberProfile() {
  const id = Number(useParams().id);
  const qc = useQueryClient();
  const person = useQuery({ queryKey: ["person", id], queryFn: () => api<Person>(`/api/people/${id}`) });
  const items = useQuery({ queryKey: ["person", id, "onboarding"], queryFn: () => api<OnboardingItem[]>(`/api/people/${id}/onboarding`) });
  const bank = useQuery({ queryKey: ["person", id, "banking"], queryFn: () => maybe<MaskedBanking>(`/api/people/${id}/sensitive`) });
  const rates = useQuery({ queryKey: ["person", id, "rates"], queryFn: () => api<RatePeriod[]>(`/api/people/${id}/rates`) });
  const docs = useQuery({ queryKey: ["person", id, "documents"], queryFn: () => api<DocumentInfo[]>(`/api/people/${id}/documents`) });
  const payouts = useQuery({ queryKey: ["payouts"], queryFn: () => api<Payout[]>("/api/payouts") });
  const pipeline = useQuery({ queryKey: ["pipeline"], queryFn: () => api<Pipeline>("/api/pipeline") });
  const [revealed, setRevealed] = useState<MaskedBanking | null>(null);
  const [editing, setEditing] = useState(false);
  const [done, setDone] = useState<string | null>(null);
  const [failed, setFailed] = useState<unknown>(null);

  const refresh = () => {
    for (const k of [["person", id], ["people"], ["pipeline"], ["dashboard"]]) qc.invalidateQueries({ queryKey: k });
  };
  const tick = useMutation({
    mutationFn: (item: OnboardingItem) => api(`/api/onboarding/${item.id}`, { method: "PATCH", body: JSON.stringify({ done: !item.done }) }),
    onSuccess: () => refresh(),
    onError: setFailed,
  });
  const stage = useMutation({
    mutationFn: (to: PersonStage) => post(`/api/people/${id}/stage`, { stage: to }),
    onSuccess: () => (refresh(), setDone("Stage updated.")),
    onError: setFailed,
  });
  const reveal = useMutation({
    mutationFn: () => api<MaskedBanking>(`/api/people/${id}/sensitive?reveal=true`),
    onSuccess: setRevealed,
    onError: setFailed,
  });

  if (person.isError) return <ErrorNote error={person.error} onRetry={() => person.refetch()} />;
  const p = person.data;
  if (!p) return <Skeleton h={160} />;
  const list = [...(items.data ?? [])].sort((a, b) => a.position - b.position);
  const complete = list.filter((i) => i.done).length;
  const next = list.find((i) => !i.done);
  const offer = Object.values(pipeline.data?.stages ?? {})
    .flat()
    .find((c) => c.person_id === id)?.offer;
  const owed = (payouts.data ?? []).filter((x) => x.person_id === id && !x.paid_at).reduce((s, x) => s + x.amount_cents, 0);
  const st = STAGE[p.status as PersonStage];
  const move = NEXT_STAGE[p.status as PersonStage];
  const shown = revealed ?? bank.data;

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h2 className="page-title">{p.full_name}</h2>
          <p className="page-sub">
            <Link to="/team">Team & offers</Link> / Member profile
          </p>
        </div>
        <div className="toolbar">
          {move && (
            <button className="btn btn-secondary" disabled={stage.isPending} onClick={() => (setDone(null), setFailed(null), stage.mutate(move.to))}>
              {move.label}
            </button>
          )}
          <button className="btn btn-secondary" onClick={() => (setDone(null), setEditing(true))}>
            Edit profile
          </button>
        </div>
      </div>
      {!!failed && <ErrorNote error={failed} />}
      <Done text={done} />

      <section className="card summary-card">
        <div>
          <p className="card-title">{offer?.role ?? "Team member"}</p>
          <p className="card-sub">{p.email}</p>
          {st && (
            <span className={`chip ${st.cls}`} style={{ marginTop: 8 }}>
              {st.label}
            </span>
          )}
        </div>
        <dl className="facts">
          <div>
            <dt>Engagement</dt>
            <dd>{p.fee_terms === "deferred" ? "Deferred task fees" : "Revenue share"}</dd>
          </div>
        </dl>
        <dl className="facts">
          <div>
            <dt>Current rate</dt>
            <dd>{percent(p.rate_bp)}</dd>
          </div>
        </dl>
        <dl className="facts">
          <div>
            <dt>Total owed</dt>
            <dd className="num">{payouts.data ? rands(owed) : "–"}</dd>
          </div>
        </dl>
        <dl className="facts">
          <div>
            <dt>Joined</dt>
            <dd>{fullDay(p.created_at)}</dd>
          </div>
        </dl>
      </section>

      <div className="grid-2-1">
        <section className="card">
          <div className="card-head">
            <h3 className="card-title">Onboarding checklist</h3>
            {items.data && (
              <span className="chip chip-success">
                {complete} of {list.length}
              </span>
            )}
          </div>
          <div style={{ padding: "0 22px 12px" }}>
            <div className="progress-bar" style={{ maxWidth: "none", background: "var(--success-bar-off)" }} aria-hidden="true">
              <span style={{ width: `${list.length ? (complete / list.length) * 100 : 0}%`, background: "var(--success-bar)" }} />
            </div>
          </div>
          {items.isPending && <Skeleton h={160} />}
          <ul className="check-list">
            {list.map((i) => (
              <li key={i.id} className={`check-row${i.done ? " done" : ""}${i === next ? " next" : ""}`}>
                <span className="check-box" aria-hidden="true">
                  {i.done ? <Check size={12} strokeWidth={3} /> : i.position}
                </span>
                <div className="check-text">
                  <p className="row-title">{i.item}</p>
                  <p className={`row-sub${!i.done && i === next ? " warning-text" : ""}`}>
                    {i.done ? (i.done_at ? `Done ${shortDay(i.done_at)}` : "Done") : i.member_can_complete ? "Awaiting the member" : "Waiting for you"}
                  </p>
                </div>
                <span className="owner">{i.member_can_complete ? "Member" : "Founder"}</span>
                {(!i.member_can_complete || i.done) && (
                  <button className="link-btn" disabled={tick.isPending} onClick={() => (setFailed(null), tick.mutate(i))}>
                    {i.done ? "Undo" : "Confirm"}
                  </button>
                )}
              </li>
            ))}
          </ul>
          {next && <p className="foot-note">Next step: {next.member_can_complete ? `${p.full_name.split(" ")[0]} completes “${next.item}”.` : `you confirm “${next.item}”.`}</p>}
        </section>

        <div className="stack" style={{ display: "grid", gap: 20 }}>
          <section className="card">
            <div className="card-head">
              <h3 className="card-title">Banking details</h3>
              <Lock size={16} className="success-text" aria-label="Stored encrypted" />
            </div>
            <hr className="divider" />
            <div className="form-card" style={{ paddingTop: 16 }}>
              {bank.isPending && <Skeleton h={60} />}
              {bank.data === null && <p className="detail-p">Not captured yet. The member adds them in their Settings.</p>}
              {shown && (
                <>
                  <dl className="reveal-row">
                    <dt>Bank</dt>
                    <dd>{shown.bank_name}</dd>
                    <dt>Account holder</dt>
                    <dd>{shown.account_holder}</dd>
                    <dt>Account number</dt>
                    <dd className="num">{shown.account_number.replace(/^\*+/, "•••• •••• ")}</dd>
                    <dt>Branch code</dt>
                    <dd className="num">{shown.branch_code}</dd>
                    {shown.id_number && (
                      <>
                        <dt>ID number</dt>
                        <dd className="num">{shown.id_number.replace(/^\*+/, "•••• •••• ")}</dd>
                      </>
                    )}
                  </dl>
                  {revealed ? (
                    <button className="btn btn-secondary btn-block" onClick={() => setRevealed(null)}>
                      Hide details
                    </button>
                  ) : (
                    <button className="btn btn-secondary btn-block" disabled={reveal.isPending} onClick={() => (setFailed(null), reveal.mutate())}>
                      Reveal details
                    </button>
                  )}
                  <p className="field-hint">Revealing is recorded in the audit history.</p>
                </>
              )}
            </div>
          </section>

          <RateReview person={p} rates={rates.data ?? []} onSaved={(msg) => (refresh(), setDone(msg))} />
        </div>
      </div>

      <section className="card">
        <div className="card-head">
          <h3 className="card-title">Documents</h3>
        </div>
        <ul className="doc-list doc-grid">
          {docs.data?.length === 0 && <li className="empty" style={{ display: "block" }}>No documents yet.</li>}
          {(docs.data ?? []).map((d) => (
            <li key={d.id} style={{ alignItems: "center" }}>
              <FileText size={18} className="doc-icon" aria-hidden="true" />
              <div className="doc-text">
                <p className="row-title">{DOC_TITLE[d.kind] ?? d.kind}</p>
                <p className="row-sub num">
                  {d.filename} · {shortDay(d.created_at)}
                </p>
              </div>
              <button className="link-btn" onClick={() => downloadFile(`/api/documents/${d.id}`, d.filename).catch(setFailed)}>
                Download
              </button>
            </li>
          ))}
        </ul>
      </section>

      {editing && <EditPerson person={p} onClose={() => setEditing(false)} onSaved={() => (refresh(), setEditing(false), setDone("Profile updated."))} />}
    </div>
  );
}

function RateReview({ person, rates, onSaved }: { person: Person; rates: RatePeriod[]; onSaved: (msg: string) => void }) {
  const [rate, setRate] = useState(person.rate_bp === 1500 ? "2000" : "1500");
  const [from, setFrom] = useState(todaySA());
  const [note, setNote] = useState("");
  const [error, setError] = useState<unknown>(null);
  const save = useMutation({
    mutationFn: () =>
      api(`/api/people/${person.id}`, { method: "PATCH", body: JSON.stringify({ rate_bp: Number(rate), rate_review_note: note.trim(), rate_effective_from: from }) }),
    onSuccess: () => (setNote(""), onSaved(`Rate review recorded: ${percent(Number(rate))} from ${fullDay(from)}.`)),
    onError: setError,
  });
  const last = [...rates].sort((a, b) => b.effective_from.localeCompare(a.effective_from))[0];

  function submit(e: FormEvent) {
    e.preventDefault();
    if (note.trim().length < 10) return setError("Write the review (at least a sentence) that supports the new rate.");
    if (!from) return setError("Choose the date the rate applies from.");
    setError(null);
    save.mutate();
  }

  return (
    <section className="card">
      <div className="card-head">
        <h3 className="card-title">Rate review</h3>
        <span className="th-note">Current {percent(person.rate_bp)}</span>
      </div>
      <hr className="divider" />
      <form className="form-card" style={{ paddingTop: 16 }} onSubmit={submit} noValidate>
        <div className="form-row" style={{ gap: 14 }}>
          <Field id="r-rate" label="Reviewed rate">
            <select id="r-rate" className="input" value={rate} onChange={(e) => setRate(e.target.value)}>
              <option value="1500">15% (initial)</option>
              <option value="2000">20% (after written review)</option>
            </select>
          </Field>
          <Field id="r-from" label="Effective from">
            <input id="r-from" className="input" type="date" value={from} onChange={(e) => setFrom(e.target.value)} />
          </Field>
        </div>
        <Field id="r-note" label="Written review">
          <textarea id="r-note" className="input textarea" maxLength={2000} placeholder="Consistent delivery and a successful written performance review." value={note} onChange={(e) => setNote(e.target.value)} />
        </Field>
        <FormError error={error} />
        <div className="form-actions" style={{ justifyContent: "space-between", alignItems: "center" }}>
          <span className="field-hint">{last ? `Last review ${shortDay(last.created_at)}` : "No review recorded yet"}</span>
          <button className="btn btn-primary" disabled={save.isPending}>
            Record review
          </button>
        </div>
      </form>
    </section>
  );
}

function EditPerson({ person, onClose, onSaved }: { person: Person; onClose: () => void; onSaved: () => void }) {
  const [f, setF] = useState({ full_name: person.full_name, email: person.email, phone: person.phone ?? "", fee_terms: person.fee_terms });
  const [error, setError] = useState<unknown>(null);
  const save = useMutation({
    mutationFn: () => api(`/api/people/${person.id}`, { method: "PATCH", body: JSON.stringify({ ...f, phone: f.phone.trim() || null }) }),
    onSuccess: onSaved,
    onError: setError,
  });
  return (
    <Dialog title="Edit profile" onClose={onClose}>
      <form onSubmit={(e) => (e.preventDefault(), save.mutate())} noValidate style={{ display: "grid", gap: 14 }}>
        <Field id="pe-name" label="Full name">
          <input id="pe-name" className="input" maxLength={200} value={f.full_name} onChange={(e) => setF({ ...f, full_name: e.target.value })} />
        </Field>
        <Field id="pe-email" label="Email address">
          <input id="pe-email" className="input" type="email" value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} />
        </Field>
        <Field id="pe-phone" label="Phone">
          <input id="pe-phone" className="input" type="tel" maxLength={40} value={f.phone} onChange={(e) => setF({ ...f, phone: e.target.value })} />
        </Field>
        <Field id="pe-terms" label="Task-fee terms">
          <select id="pe-terms" className="input" value={f.fee_terms} onChange={(e) => setF({ ...f, fee_terms: e.target.value })}>
            <option value="standard">Standard</option>
            <option value="deferred">Deferred until the first client payment</option>
          </select>
        </Field>
        <FormError error={error} />
        <div className="form-actions">
          <button type="button" className="btn btn-secondary" onClick={onClose}>
            Cancel
          </button>
          <button className="btn btn-primary" disabled={save.isPending}>
            Save profile
          </button>
        </div>
      </form>
    </Dialog>
  );
}
