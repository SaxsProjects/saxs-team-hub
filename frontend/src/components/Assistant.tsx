import { useQuery } from "@tanstack/react-query";
import { Sparkles } from "lucide-react";
import { Link } from "react-router";
import { api } from "../api/client";
import type { AssistantBriefing, VatPosition } from "../api/types";
import { percent, rands } from "../lib/format";
import { ErrorNote, Skeleton } from "./ui";

const TONE = { high: "chip-warning", normal: "chip-brand", info: "chip-neutral" } as const;
const LABEL = { high: "Now", normal: "Soon", info: "FYI" } as const;

/** Saxs Assistant: the hub's own helper. It reads the hub's records and lists what needs doing next. */
export function AssistantPanel({ limit = 6 }: { limit?: number }) {
  const q = useQuery({ queryKey: ["assistant"], queryFn: () => api<AssistantBriefing>("/api/assistant"), refetchInterval: 120_000 });
  if (q.isError) return <ErrorNote error={q.error} onRetry={() => q.refetch()} />;
  const b = q.data;
  const all = Array.isArray(b?.items) ? b.items : [];
  const items = all.slice(0, limit);
  const auto = b?.autopilot ?? {};
  const autoKeys = Object.keys(auto) as (keyof typeof auto)[];
  return (
    <section className="card assistant-card" aria-label="Saxs Assistant">
      <div className="card-head">
        <h3 className="card-title" style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <Sparkles size={18} aria-hidden="true" className="assistant-icon" /> Saxs Assistant
        </h3>
        {b && <span className="chip chip-neutral">{items.length ? `${all.length} to look at` : "All clear"}</span>}
      </div>
      {!b ? (
        <Skeleton h={64} />
      ) : (
        <>
          <p className="row-sub" style={{ marginBottom: 10 }}>{b.summary}</p>
          {items.length > 0 && (
            <ul className="assistant-list">
              {items.map((i) => (
                <li key={i.id} className="assistant-item">
                  <span className={`chip ${TONE[i.priority]}`}>{LABEL[i.priority]}</span>
                  <span className="assistant-text">
                    <span className="row-title">{i.title}</span>
                    <span className="row-sub">{i.detail}</span>
                  </span>
                  <Link className="btn btn-secondary btn-sm" to={i.link}>
                    {i.action}
                  </Link>
                </li>
              ))}
            </ul>
          )}
          {autoKeys.length > 0 && (
            <p className="row-sub assistant-auto">
              Running on its own:{" "}
              {autoKeys
                .map((k) => `${{ client_reminders: "payment reminders", client_statements: "monthly statements", monthly_report: "monthly finance report" }[k]} ${auto[k] ? "on" : "off"}`)
                .join(" · ")}
              . <Link to="/settings">Change</Link>
            </p>
          )}
        </>
      )}
    </section>
  );
}

const VAT_TONE: Record<VatPosition["status"], string> = {
  registered: "chip-success",
  below: "chip-neutral",
  voluntary_possible: "chip-brand",
  approaching: "chip-warning",
  must_register: "chip-warning",
};
const VAT_LABEL: Record<VatPosition["status"], string> = {
  registered: "VAT registered",
  below: "Below threshold",
  voluntary_possible: "Voluntary possible",
  approaching: "Approaching threshold",
  must_register: "Must register",
};

/** Taxable supplies in the last 12 months against the R2.3 million compulsory VAT threshold. */
export function VatCard({ vat }: { vat: VatPosition | undefined }) {
  if (!vat) return <Skeleton h={90} />;
  const share = Math.min(vat.share_of_compulsory_bp, 10_000);
  return (
    <section className="card vat-card" aria-label="VAT position">
      <div className="card-head">
        <h3 className="card-title">VAT</h3>
        <span className={`chip ${VAT_TONE[vat.status]}`}>{VAT_LABEL[vat.status]}</span>
      </div>
      <p className="momentum-line">
        <span className="momentum-value num">{rands(vat.taxable_12m_cents)}</span>
        <span className="momentum-sub">taxable supplies, last 12 months</span>
      </p>
      {!vat.registered && (
        <div className="vat-meter" role="img" aria-label={`${percent(share)} of the ${rands(vat.compulsory_threshold_cents)} threshold`}>
          <span style={{ width: `${share / 100}%` }} />
        </div>
      )}
      <p className="row-sub" style={{ marginTop: 8 }}>
        {vat.message}
      </p>
    </section>
  );
}
