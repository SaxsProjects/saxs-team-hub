import { usePreview, type PreviewEmail } from "../../components/DocumentPreview";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FileText } from "lucide-react";
import { useRef, useState, type FormEvent } from "react";
import { Link } from "react-router";
import { api, apiBlob, post } from "../../api/client";
import type { CompanyTemplate, Offer, Person, PersonStage, Pipeline, PipelineCard } from "../../api/types";
import { Dialog, Done, EmptyRow, ErrorNote, Field, FormError, LoadingRow, PageHead, Skeleton, StatCard } from "../../components/ui";
import { fileSize, percent, plural, shortDay, todaySA } from "../../lib/format";
import "../overview.css";
import "../pages.css";

export const STAGE: Record<PersonStage, { label: string; cls: string }> = {
  draft: { label: "New", cls: "chip-neutral" },
  sent: { label: "Offer sent", cls: "chip-brand" },
  viewed: { label: "Offer viewed", cls: "chip-brand" },
  accepted: { label: "Onboarding", cls: "chip-warning" },
  agreement_signed: { label: "Onboarding", cls: "chip-warning" },
  onboarded: { label: "Active", cls: "chip-success" },
  declined: { label: "Declined", cls: "chip-neutral" },
  expired: { label: "Offer expired", cls: "chip-neutral" },
};

const TEAM = new Set<PersonStage>(["accepted", "agreement_signed", "onboarded"]);

export function TeamOffers() {
  const qc = useQueryClient();
  const people = useQuery({ queryKey: ["people"], queryFn: () => api<Person[]>("/api/people") });
  const pipeline = useQuery({ queryKey: ["pipeline"], queryFn: () => api<Pipeline>("/api/pipeline") });
  const [adding, setAdding] = useState(false);
  const [done, setDone] = useState<string | null>(null);
  const refresh = () => {
    for (const k of ["people", "pipeline", "dashboard"]) qc.invalidateQueries({ queryKey: [k] });
  };

  if (people.isError) return <ErrorNote error={people.error} onRetry={() => people.refetch()} />;
  const list = people.data ?? [];
  const stages = pipeline.data?.stages;
  const latestOffer = new Map<number, Offer | null>(Object.values(stages ?? {}).flat().map((c) => [c.person_id, c.offer]));
  const team = list.filter((p) => TEAM.has(p.status as PersonStage));
  const onboarding = team.filter((p) => p.status !== "onboarded");
  const sent = stages?.sent ?? [];
  const viewed = stages?.viewed ?? [];
  const accepted = [...(stages?.accepted ?? []), ...(stages?.agreement_signed ?? [])];
  const candidates = list.filter((p) => ["draft", "declined", "expired"].includes(p.status));

  return (
    <div className="page">
      <PageHead
        title="Team & offers"
        sub={people.data ? `${plural(team.length, "team member")} · ${plural(sent.length + viewed.length, "open offer")}` : undefined}
      >
        <button className="btn btn-secondary" onClick={() => (setDone(null), setAdding(true))}>
          Add person
        </button>
      </PageHead>
      <Done text={done} />

      <div className="split">
        <div className="stack">
          <div className="stats-3">
            <StatCard label="Team members" value={people.data ? team.length : <Skeleton w={40} h={30} />} note={`${team.length - onboarding.length} onboarded`} />
            <StatCard label="Onboarding" value={people.data ? onboarding.length : <Skeleton w={40} h={30} />} note={onboarding.length ? "Finishing setup" : "Nobody in setup"} />
            <StatCard
              label="Open offers"
              value={pipeline.data ? sent.length + viewed.length : <Skeleton w={40} h={30} />}
              note={`${sent.length} sent · ${viewed.length} viewed`}
            />
          </div>

          <section>
            <div className="card-head" style={{ padding: "4px 0 12px" }}>
              <h3 className="card-title">Offer pipeline</h3>
              {!!pipeline.data?.overdue_count && <span className="chip chip-warning">{plural(pipeline.data.overdue_count, "offer")} past deadline</span>}
            </div>
            <div className="board">
              <Column title="Sent" cards={sent} render={(c) => (c.offer ? `Respond by ${shortDay(c.offer.deadline)}` : "")} tone="brand" />
              <Column title="Viewed" cards={viewed} render={(c) => (c.offer?.viewed_at ? `Opened ${shortDay(c.offer.viewed_at)}` : "Opened")} tone="brand" />
              <Column
                title="Accepted"
                cards={accepted}
                render={(c) => (c.offer?.responded_at ? `Accepted ${shortDay(c.offer.responded_at)}` : "Accepted")}
                tone="success"
              />
            </div>
          </section>

          <section className="card">
            <div className="card-head">
              <h3 className="card-title">Team directory</h3>
              <span className="th-note">{plural(list.length, "person", "people")}</span>
            </div>
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>Name</th>
                    <th className="hide-sm">Role</th>
                    <th>Rate / terms</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {people.isPending && <LoadingRow cols={4} />}
                  {people.data && list.length === 0 && <EmptyRow cols={4} text="Nobody added yet. Use “Add person” to start an offer." />}
                  {[...list]
                    .sort((a, b) => a.full_name.localeCompare(b.full_name))
                    .map((p) => (
                      <tr key={p.id}>
                        <td className="row-title">
                          <Link className="row-link" to={`/team/${p.id}`}>
                            {p.full_name}
                          </Link>
                        </td>
                        <td className="hide-sm muted">{latestOffer.get(p.id)?.role ?? "—"}</td>
                        <td className="num">
                          {percent(p.rate_bp)}
                          <span className="muted"> · {p.fee_terms === "deferred" ? "Deferred" : "Standard"}</span>
                        </td>
                        <td>
                          <span className={`chip ${STAGE[p.status as PersonStage]?.cls ?? "chip-neutral"}`}>{STAGE[p.status as PersonStage]?.label ?? p.status}</span>
                        </td>
                      </tr>
                    ))}
                </tbody>
              </table>
            </div>
          </section>
        </div>

        <NewOffer candidates={candidates} onDone={(msg) => (refresh(), setDone(msg))} onAddPerson={() => setAdding(true)} />
      </div>

      {adding && <AddPerson onClose={() => setAdding(false)} onSaved={(p) => (refresh(), setAdding(false), setDone(`${p.full_name} added. You can now draft their offer.`))} />}
    </div>
  );
}

function Column({ title, cards, render, tone }: { title: string; cards: PipelineCard[]; render: (c: PipelineCard) => string; tone: "brand" | "success" }) {
  return (
    <div className="board-col">
      <div className="board-head">
        <span>{title}</span>
        <span className="board-count">{cards.length}</span>
      </div>
      {cards.length === 0 && <p className="board-empty">None</p>}
      {cards.map((c) => (
        <Link key={c.person_id} to={`/team/${c.person_id}`} className="board-card">
          <span className="row-title">{c.full_name}</span>
          <span className="row-sub">{c.offer?.role ?? "No offer yet"}</span>
          <span className={`board-meta ${tone === "success" ? "success-text" : "brand-text"}`}>{render(c)}</span>
        </Link>
      ))}
    </div>
  );
}

function NewOffer({ candidates, onDone, onAddPerson }: { candidates: Person[]; onDone: (msg: string) => void; onAddPerson: () => void }) {
  const [f, setF] = useState({ person_id: "", role: "", deadline: "", message: "We’d love you to join the team.\nPlease review your offer below." });
  const [file, setFile] = useState<File | null>(null);
  const [error, setError] = useState<unknown>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const person = candidates.find((p) => String(p.id) === f.person_id);
  const preview = usePreview();
  const templates = useQuery({
    queryKey: ["templates", false],
    queryFn: () => api<CompanyTemplate[]>("/api/templates"),
    select: (all) => all.filter((t) => t.category === "offer" || t.category === "contract"),
  });
  const [fromTemplate, setFromTemplate] = useState("");

  async function pickTemplate(id: string) {
    setFromTemplate(id);
    const t = templates.data?.find((x) => String(x.id) === id);
    if (!t) return;
    setError(null);
    try {
      // The template's current version becomes this offer's proposal, exactly as stored.
      const blob = await apiBlob(`/api/templates/${t.id}/pdf`);
      setFile(new File([blob], `${t.name}.pdf`, { type: "application/pdf" }));
      if (fileRef.current) fileRef.current.value = "";
    } catch (e) {
      setFromTemplate("");
      setError(e);
    }
  }

  const save = useMutation({
    mutationFn: async (send: boolean) => {
      const offer = await post<Offer>("/api/offers", { person_id: Number(f.person_id), role: f.role.trim(), deadline: f.deadline, message: f.message.trim() || null });
      if (file) {
        const form = new FormData();
        form.append("file", file);
        await api(`/api/offers/${offer.id}/pdf`, { method: "POST", body: form });
      }
      if (send) await post(`/api/offers/${offer.id}/send`);
      return { offer, send };
    },
    onSuccess: ({ offer, send }) => {
      setF({ ...f, person_id: "", role: "", deadline: "" });
      setFile(null);
      setFromTemplate("");
      if (fileRef.current) fileRef.current.value = "";
      onDone(send ? `Offer ${offer.reference} emailed to ${person?.full_name}.` : `Offer ${offer.reference} saved as a draft.`);
    },
    onError: setError,
  });

  function submit(send: boolean) {
    return (e?: FormEvent) => {
      e?.preventDefault();
      if (!f.person_id) return setError("Choose the candidate.");
      if (f.role.trim().length < 2) return setError("Add the role you’re offering.");
      if (!f.deadline || f.deadline < todaySA()) return setError("Choose a response deadline from today onwards.");
      if (send && !file) return setError("Attach the proposal PDF before sending.");
      if (file && (file.type !== "application/pdf" || file.size > 10 * 1024 * 1024)) return setError("The proposal must be a PDF under 10 MB.");
      setError(null);
      if (!send || !file) return save.mutate(send);
      // Nothing is emailed until the founder has seen the proposal and the exact email.
      preview({
        title: `Offer for ${person?.full_name ?? "the candidate"}`,
        filename: file.name,
        load: async () => file,
        email: () => post<PreviewEmail>("/api/offers/email-preview", { person_id: Number(f.person_id), role: f.role.trim(), deadline: f.deadline }),
        note: "This is the email and the proposal they will get. Their personal link and the offer reference are created when you send.",
        confirm: { label: "Send offer", run: () => save.mutateAsync(true) },
      });
    };
  }

  return (
    <section className="card" aria-label="New offer">
      <div className="card-head">
        <h3 className="card-title">New offer</h3>
        <span className="th-note">Draft</span>
      </div>
      <hr className="divider" />
      <form className="form-card" style={{ paddingTop: 16 }} onSubmit={submit(true)} noValidate>
        <Field id="o-person" label="Candidate">
          <select id="o-person" className="input" value={f.person_id} onChange={(e) => setF({ ...f, person_id: e.target.value })}>
            <option value="">{candidates.length ? "Choose a person" : "No candidates waiting"}</option>
            {candidates.map((p) => (
              <option key={p.id} value={p.id}>
                {p.full_name}
              </option>
            ))}
          </select>
        </Field>
        {candidates.length === 0 && (
          <button type="button" className="link-btn" style={{ justifySelf: "start" }} onClick={onAddPerson}>
            Add a person first
          </button>
        )}
        <Field id="o-email" label="Email">
          <input id="o-email" className="input" readOnly value={person?.email ?? ""} placeholder="Filled in from the person" />
        </Field>
        <Field id="o-role" label="Role">
          <input id="o-role" className="input" maxLength={200} placeholder="UI / UX designer" value={f.role} onChange={(e) => setF({ ...f, role: e.target.value })} />
        </Field>
        <Field id="o-deadline" label="Response deadline">
          <input id="o-deadline" className="input" type="date" min={todaySA()} value={f.deadline} onChange={(e) => setF({ ...f, deadline: e.target.value })} />
        </Field>
        <Field id="o-file" label="Proposal">
          <label className="file-tile" style={{ cursor: "pointer" }}>
            <FileText size={18} className="doc-icon" aria-hidden="true" />
            <span>
              <span className="row-title" style={{ display: "block" }}>
                {file ? file.name : "Choose the proposal PDF"}
              </span>
              <span className="row-sub">{file ? `PDF · ${fileSize(file.size)}` : "PDF, up to 10 MB"}</span>
            </span>
            <input id="o-file" ref={fileRef} type="file" accept="application/pdf" className="sr-only" onChange={(e) => (setFromTemplate(""), setFile(e.target.files?.[0] ?? null))} />
          </label>
        </Field>
        {(templates.data?.length ?? 0) > 0 && (
          <Field id="o-template" label="Or use a company template" hint="Its current version becomes the proposal. You see it before anything is sent.">
            <select id="o-template" className="input" value={fromTemplate} onChange={(e) => void pickTemplate(e.target.value)}>
              <option value="">Choose a template</option>
              {templates.data?.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.name} (version {t.current.version})
                </option>
              ))}
            </select>
          </Field>
        )}
        <Field id="o-message" label="Message">
          <textarea id="o-message" className="input textarea" maxLength={5000} value={f.message} onChange={(e) => setF({ ...f, message: e.target.value })} />
        </Field>
        <FormError error={error} />
        <div className="form-row" style={{ gap: 10 }}>
          <button className="btn btn-primary" disabled={save.isPending}>
            {save.isPending ? "Working…" : "Preview and send"}
          </button>
          <button type="button" className="btn btn-secondary" disabled={save.isPending} onClick={() => submit(false)()}>
            Save draft
          </button>
        </div>
      </form>
    </section>
  );
}

function AddPerson({ onClose, onSaved }: { onClose: () => void; onSaved: (p: Person) => void }) {
  const [f, setF] = useState({ full_name: "", email: "", phone: "" });
  const [error, setError] = useState<unknown>(null);
  const save = useMutation({
    mutationFn: () => post<Person>("/api/people", { full_name: f.full_name.trim(), email: f.email.trim(), phone: f.phone.trim() || null }),
    onSuccess: onSaved,
    onError: setError,
  });

  function submit(e: FormEvent) {
    e.preventDefault();
    if (f.full_name.trim().length < 2) return setError("Enter the person’s full name.");
    if (!/^\S+@\S+\.\S+$/.test(f.email.trim())) return setError("Enter a valid email address.");
    setError(null);
    save.mutate();
  }

  return (
    <Dialog title="Add person" onClose={onClose}>
      <form onSubmit={submit} noValidate style={{ display: "grid", gap: 14 }}>
        <Field id="n-name" label="Full name">
          <input id="n-name" className="input" maxLength={200} value={f.full_name} onChange={(e) => setF({ ...f, full_name: e.target.value })} autoFocus />
        </Field>
        <Field id="n-email" label="Email address">
          <input id="n-email" className="input" type="email" value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} />
        </Field>
        <Field id="n-phone" label="Phone (optional)">
          <input id="n-phone" className="input" type="tel" maxLength={40} value={f.phone} onChange={(e) => setF({ ...f, phone: e.target.value })} />
        </Field>
        <p className="field-hint">Nothing is sent yet. You choose when to send their offer.</p>
        <FormError error={error} />
        <div className="form-actions">
          <button type="button" className="btn btn-secondary" onClick={onClose}>
            Cancel
          </button>
          <button className="btn btn-primary" disabled={save.isPending}>
            Add person
          </button>
        </div>
      </form>
    </Dialog>
  );
}
