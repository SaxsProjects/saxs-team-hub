import type { ReactNode } from "react";
import { LockKeyhole } from "lucide-react";
import mark from "../assets/logo-mark.png";
import word from "../assets/logo-wordmark.png";
import { APP_VERSION } from "../lib/version";
import "./AuthLayout.css";

/** The centred-card layout of the Sign in / Two-factor / Set password screens. */
export function AuthLayout({ title, subtitle, children, footer }: { title: string; subtitle: string; children: ReactNode; footer?: ReactNode }) {
  return (
    <div className="auth-page">
      <header className="auth-header">
        <span className="auth-logo">
          <img src={mark} alt="" className="auth-mark" />
          <img src={word} alt="SaxsProjects" className="auth-word" />
        </span>
        <span className="auth-header-tag">TEAM HUB</span>
      </header>
      <main className="auth-main" id="main">
        <section className="auth-card" aria-labelledby="auth-title">
          <span className="auth-icon" aria-hidden="true">
            <LockKeyhole size={20} strokeWidth={2} />
          </span>
          <h1 id="auth-title" className="auth-title">{title}</h1>
          <p className="auth-subtitle">{subtitle}</p>
          {children}
        </section>
        {footer ?? <p className="auth-footnote">SaxsProjects (Pty) Ltd · Team Hub v{APP_VERSION}</p>}
      </main>
    </div>
  );
}
