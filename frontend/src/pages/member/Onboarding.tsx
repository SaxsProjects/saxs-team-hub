import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, CheckCircle2, FileText } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";
import { api } from "../../api/client";
import type { OnboardingItem } from "../../api/types";
import { ErrorNote, PageHead, Skeleton } from "../../components/ui";
import { shortDay } from "../../lib/format";
import "../overview.css";
import "../pages.css";

/** What each step means and how to finish it. Keys match backend/app/services.py DEFAULT_ONBOARDING. */
const GUIDE: Record<string, { title: string; doneNote: string; steps: [string, string][]; link?: { to: string; label: string } }> = {
  agreement_signed: {
    title: "Contractor agreement",
    doneNote: "Signed",
    steps: [
      ["Read the agreement", "Check the role, rate and payment terms in your offer."],
      ["Sign and return it", "The founder confirms once the signed copy is filed."],
    ],
    link: { to: "/my/documents", label: "Open my documents" },
  },
  github_invited: {
    title: "GitHub access",
    doneNote: "Organisation invitation accepted",
    steps: [
      ["Share your GitHub username", "Send it to the founder in the team channel."],
      ["Accept the invitation", "GitHub emails you an invite to the SaxsProjects organisation."],
    ],
  },
  two_factor: {
    title: "Two-factor authentication",
    doneNote: "Account security enabled",
    steps: [
      ["Turn on two-factor", "Use an authenticator app on your GitHub and work accounts."],
      ["Let the founder know", "The founder confirms this step."],
    ],
  },
  channel_joined: {
    title: "Team channel",
    doneNote: "Joined the team channel",
    steps: [
      ["Open your invitation", "Join the team channel from the link the founder sent you."],
      ["Say hello", "Introduce yourself so the team knows you’re in."],
      ["Mark as done", "Tick this step once you’ve joined."],
    ],
  },
  banking_captured: {
    title: "Banking details",
    doneNote: "Saved to your profile",
    steps: [
      ["Add your bank account", "Open Settings and save your banking details."],
      ["Stored encrypted", "Only the founder can see them, and only to pay you."],
    ],
    link: { to: "/settings", label: "Open settings" },
  },
  standards_read: {
    title: "Team standards",
    doneNote: "Read and acknowledged",
    steps: [
      ["Read the standards", "Our delivery, communication, coding and security rules."],
      ["Ask any questions", "Use the team channel if anything needs clarification."],
      ["Mark as read", "Confirm that you have read and understood the standards."],
    ],
  },
  first_task: {
    title: "First task",
    doneNote: "Assigned",
    steps: [
      ["Wait for your first Task Order", "The founder sends it once setup is complete."],
      ["Confirm it", "Open My Task Orders and confirm before you start."],
    ],
    link: { to: "/my/task-orders", label: "Open my Task Orders" },
  },
};

export function Onboarding() {
  const qc = useQueryClient();
  const items = useQuery({ queryKey: ["me-onboarding"], queryFn: () => api<OnboardingItem[]>("/api/me/onboarding") });
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const tick = useMutation({
    mutationFn: (id: number) => api<OnboardingItem>(`/api/me/onboarding/${id}`, { method: "PATCH", body: JSON.stringify({ done: true }) }),
    onSuccess: (i) => {
      for (const k of ["me-onboarding", "me-overview"]) qc.invalidateQueries({ queryKey: [k] });
      setDone(`“${GUIDE[i.key]?.title ?? i.item}” marked as done.`);
      setSelectedId(null);
    },
  });

  if (items.isError) return <ErrorNote error={items.error} onRetry={() => items.refetch()} />;
  const list = [...(items.data ?? [])].sort((a, b) => a.position - b.position);
  const complete = list.filter((i) => i.done).length;
  const next = list.find((i) => !i.done);
  const selected = list.find((i) => i.id === selectedId) ?? next ?? list[list.length - 1];
  const left = list.length - complete;
  const g = selected ? GUIDE[selected.key] : undefined;
  const titleOf = (i: OnboardingItem) => GUIDE[i.key]?.title ?? i.item;

  return (
    <div className="page">
      <PageHead
        title="Onboarding"
        sub={items.data ? (left === 0 ? "You’re fully set up." : left === 1 ? "Complete your last step to finish setting up." : "Complete these steps to finish setting up.") : undefined}
      />
      {!!tick.error && <ErrorNote error={tick.error} />}
      {done && (
        <p className="form-ok" role="status">
          <CheckCircle2 size={16} aria-hidden="true" /> {done}
        </p>
      )}

      <section className={`card progress-card${items.data && left === 0 ? " complete" : ""}`}>
        <div>
          <p className="progress-title">{items.data ? `${complete} of ${list.length} complete` : <Skeleton w={180} h={28} />}</p>
          <p className="progress-sub">{next ? `${titleOf(next)} is your ${left === 1 ? "last" : "next"} step.` : "Every step is done."}</p>
        </div>
        <div
          className="progress-bar"
          role="progressbar"
          aria-label="Onboarding progress"
          aria-valuemin={0}
          aria-valuemax={list.length}
          aria-valuenow={complete}
        >
          <span style={{ width: `${list.length ? (complete / list.length) * 100 : 0}%` }} />
        </div>
      </section>

      <div className="split">
        <section className="card">
          <div className="card-head">
            <h3 className="card-title">Your checklist</h3>
            {items.data && <span className={`chip ${left ? "chip-warning" : "chip-success"}`}>{left ? `${left} left` : "All done"}</span>}
          </div>
          {items.isPending && <Skeleton h={200} />}
          <ul className="check-list">
            {list.map((i) => (
              <li
                key={i.id}
                className={`check-row selectable${i.done ? " done" : ""}${i === next ? " next" : ""}`}
                tabIndex={0}
                aria-selected={i.id === selected?.id}
                onClick={() => setSelectedId(i.id)}
                onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), setSelectedId(i.id))}
                style={{ cursor: "pointer" }}
              >
                <span className="check-box" aria-hidden="true">
                  {i.done && <Check size={12} strokeWidth={3} />}
                </span>
                <div className="check-text">
                  <p className="row-title">{titleOf(i)}</p>
                  <p className="row-sub">{i.done ? (i.done_at ? `${GUIDE[i.key]?.doneNote ?? "Done"} · ${shortDay(i.done_at)}` : (GUIDE[i.key]?.doneNote ?? "Done")) : i.item}</p>
                </div>
                <span className={`chip ${i.done ? "chip-success" : "chip-warning"}`}>{i.done ? (i.member_can_complete ? "Complete" : "Confirmed") : "To do"}</span>
              </li>
            ))}
          </ul>
        </section>

        {selected && (
          <section className="card detail" aria-label="Step details">
            <span className="detail-icon" aria-hidden="true">
              <FileText size={20} />
            </span>
            <h3 className="detail-title" style={{ marginTop: 18 }}>
              {titleOf(selected)}
            </h3>
            <p className="detail-ref">{selected.item}</p>
            <span
              className={`chip ${selected.done ? "chip-success" : "chip-warning"}`}
              style={{ marginTop: 12, justifySelf: "start" }}
            >
              {selected.done ? "Done" : selected === next ? "Your next step" : "To do"}
            </span>
            <hr className="divider" />
            {g && (
              <>
                <p className="detail-h">{selected.done ? "What this step covered" : "How to finish this step"}</p>
                <ol className="numbered">
                  {g.steps.map(([t, s], n) => (
                    <li key={t}>
                      <span className="n">{String(n + 1).padStart(2, "0")}</span>
                      <span className="setting-title">{t}</span>
                      <span />
                      <span className="detail-p">{s}</span>
                    </li>
                  ))}
                </ol>
              </>
            )}
            {!selected.done && (
              <div className="detail-actions">
                {g?.link && (
                  <Link className="btn btn-secondary" to={g.link.to}>
                    {g.link.label}
                  </Link>
                )}
                {selected.member_can_complete ? (
                  <button className="btn btn-primary" onClick={() => (setDone(null), tick.mutate(selected.id))} disabled={tick.isPending}>
                    {selected.key === "standards_read" ? "Mark as read" : "Mark as done"}
                  </button>
                ) : (
                  <p className="field-hint">The founder confirms this step once it’s done.</p>
                )}
              </div>
            )}
          </section>
        )}
      </div>
    </div>
  );
}
