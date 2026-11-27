import { useQuery } from "@tanstack/react-query";
import { Bell, ChevronRight, CircleHelp, LogOut, Menu, X } from "lucide-react";
import { useEffect, useId, useMemo, useRef, useState, type ReactNode } from "react";
import { NavLink, useLocation, useNavigate } from "react-router";
import { api } from "../api/client";
import type { AuditEntry, Dashboard, MemberOverview } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { describeAudit } from "../lib/activity";
import { clock, firstName, shortDate } from "../lib/format";
import { Avatar } from "./Avatar";
import { GlobalSearch } from "./GlobalSearch";
import { PasskeyOffer } from "./TrustedDevices";
import { FOUNDER_NAV, MEMBER_NAV, SETTINGS_ITEM, type NavItem } from "./nav";
import markLight from "../assets/logo-mark-light.png";
import wordLight from "../assets/logo-wordmark-light.png";
import { APP_VERSION } from "../lib/version";
import "./AppShell.css";

export function AppShell({ children }: { children: ReactNode }) {
  const { me } = useAuth();
  const isAdmin = me?.role === "admin";
  const nav = isAdmin ? FOUNDER_NAV : MEMBER_NAV;
  const location = useLocation();
  const [drawerOpen, setDrawerOpen] = useState(false);
  useEffect(() => setDrawerOpen(false), [location.pathname]);

  const dashboard = useQuery({
    queryKey: ["dashboard"],
    queryFn: () => api<Dashboard>("/api/dashboard"),
    enabled: isAdmin,
  });
  const reviews = dashboard.data?.task_orders_by_status?.submitted ?? 0;

  const current = [...nav, SETTINGS_ITEM].find((i) => (i.to === "/" ? location.pathname === "/" : location.pathname.startsWith(i.to)));

  return (
    <div className="shell">
      <a href="#main" className="skip-link">
        Skip to content
      </a>
      <aside className={`sidebar${drawerOpen ? " open" : ""}`} aria-label="Main navigation">
        <div className="sidebar-brand">
          <span className="sidebar-logo">
            <img src={markLight} alt="" className="sidebar-mark" />
            <img src={wordLight} alt="SaxsProjects" className="sidebar-word" />
          </span>
          <span className="sidebar-tag">TEAM HUB</span>
          <span className="sidebar-accent" aria-hidden="true" />
          <button className="sidebar-close" onClick={() => setDrawerOpen(false)} aria-label="Close menu">
            <X size={20} />
          </button>
        </div>
        <p className="sidebar-label">{isAdmin ? "MANAGE YOUR BUSINESS" : "YOUR SPACE"}</p>
        <nav className="sidebar-nav">
          {nav.map((item) => (
            <SideLink key={item.to} item={item} badge={item.badgeKey === "reviews" ? reviews : 0} />
          ))}
        </nav>
        <div className="sidebar-foot">
          <SideLink item={SETTINGS_ITEM} />
          <hr className="sidebar-divider" />
          <p className="sidebar-role">{isAdmin ? "FOUNDER · ADMIN" : "TEAM MEMBER"}</p>
          <p className="sidebar-version">Team Hub v{APP_VERSION}</p>
        </div>
      </aside>
      {drawerOpen && <div className="scrim" onClick={() => setDrawerOpen(false)} aria-hidden="true" />}

      <div className="workspace">
        <header className="topbar">
          <button className="menu-btn" onClick={() => setDrawerOpen(true)} aria-label="Open menu">
            <Menu size={22} />
          </button>
          <h1 className="topbar-title">{current?.title ?? "Team Hub"}</h1>
          <GlobalSearch isAdmin={isAdmin} nav={nav} />
          <a className="topbar-help" href="mailto:admin@saxsprojects.co.za?subject=Team%20Hub%20help">
            <CircleHelp size={20} strokeWidth={1.75} aria-hidden="true" />
            <span>Help</span>
          </a>
          <span className="topbar-divider" aria-hidden="true" />
          <Notifications isAdmin={isAdmin} />
          <UserMenu />
        </header>
        <main id="main" className="content" tabIndex={-1}>
          <PasskeyOffer />
          {children}
        </main>
      </div>
    </div>
  );
}

function SideLink({ item, badge = 0 }: { item: NavItem; badge?: number }) {
  const Icon = item.icon;
  return (
    <NavLink to={item.to} end={item.to === "/"} className={({ isActive }) => `side-link${isActive ? " active" : ""}`}>
      <Icon size={20} strokeWidth={1.75} aria-hidden="true" />
      <span>{item.label}</span>
      {badge > 0 && (
        <span className="side-badge" aria-label={`${badge} to review`}>
          {badge}
        </span>
      )}
    </NavLink>
  );
}

/** Open/close state for a small floating panel that closes on outside click or Escape. */
function usePopover() {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (!ref.current?.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);
  return { open, setOpen, ref };
}

function UserMenu() {
  const { me, signOut } = useAuth();
  const { open, setOpen, ref } = usePopover();
  const navigate = useNavigate();
  const menuId = useId();
  const isAdmin = me?.role === "admin";
  const name = me?.full_name ?? (isAdmin ? "Phathutshedzo Mamagau" : me?.email);
  return (
    <div className="popover-anchor" ref={ref}>
      <button className="user-btn" aria-haspopup="menu" aria-expanded={open} aria-controls={menuId} onClick={() => setOpen(!open)}>
        <Avatar url={me?.avatar_url} name={name} size={36} />
        <span className="user-text">
          <span className="user-name">{isAdmin ? firstName(name) : name}</span>
          <span className="user-role">{isAdmin ? "Founder" : "Team member"}</span>
        </span>
        <ChevronRight size={16} className="muted" aria-hidden="true" />
      </button>
      {open && (
        <div className="popover menu" role="menu" id={menuId}>
          <p className="menu-email">{me?.email}</p>
          <button
            role="menuitem"
            className="menu-item"
            onClick={() => {
              setOpen(false);
              navigate("/settings");
            }}
          >
            Profile &amp; security
          </button>
          <button role="menuitem" className="menu-item danger" onClick={signOut}>
            <LogOut size={16} aria-hidden="true" /> Sign out
          </button>
        </div>
      )}
    </div>
  );
}

interface Notice {
  id: string;
  title: string;
  detail: string;
  to: string;
}

const SEEN_KEY = "teamhub.activitySeen";

function readSeen(isAdmin: boolean): number {
  if (!isAdmin) return 0;
  try {
    return Number(localStorage.getItem(SEEN_KEY)) || 0;
  } catch {
    return 0;
  }
}

function writeSeen(id: number): void {
  try {
    localStorage.setItem(SEEN_KEY, String(id));
  } catch {
    /* private mode: the dot just shows again next time */
  }
}

/** Where an activity item leads: the record itself where a page can open it, otherwise its history. */
function auditLink(a: AuditEntry): string {
  const id = a.entity_id;
  switch (a.entity) {
    case "person":
      return id ? `/team/${id}` : "/team";
    case "offer":
      return "/team";
    case "project":
      return id ? `/projects/${id}` : "/projects";
    case "task_order":
      return id ? `/task-orders?open=${id}` : "/task-orders";
    case "invoice":
      return id ? `/finance/invoices?open=${id}` : "/finance/invoices";
    case "quotation":
      return id ? `/finance/quotations?open=${id}` : "/finance/quotations";
    case "client":
      return id ? `/finance/clients?open=${id}` : "/finance/clients";
    case "payout":
      return id ? `/payouts?open=${id}` : "/payouts";
    default:
      return `/audit?event=${a.id}`;
  }
}

function Notifications({ isAdmin }: { isAdmin: boolean }) {
  const { open, setOpen, ref } = usePopover();
  const navigate = useNavigate();
  const audit = useQuery({
    queryKey: ["audit", 6],
    queryFn: () => api<AuditEntry[]>("/api/audit?scope=workspace&limit=6"),
    enabled: isAdmin,
  });
  const overview = useQuery({
    queryKey: ["me-overview"],
    queryFn: () => api<MemberOverview>("/api/me/overview"),
    enabled: !isAdmin,
  });

  const notices: Notice[] = useMemo(() => {
    if (isAdmin) {
      return (audit.data ?? []).map((a) => {
        const d = describeAudit(a);
        const when = `${shortDate(a.at)} ${clock(a.at)}`;
        return {
          id: `a${a.id}`,
          title: d.title,
          detail: d.detail ? `${d.detail} · ${when}` : when,
          to: auditLink(a),
        };
      });
    }
    const o = overview.data;
    if (!o) return [];
    const out: Notice[] = [];
    if (o.task_orders_to_confirm)
      out.push({
        id: "confirm",
        title: `${o.task_orders_to_confirm} Task Order${o.task_orders_to_confirm > 1 ? "s" : ""} to confirm`,
        detail: "Accept or decline the new work",
        to: "/my/task-orders",
      });
    if (o.can_request_payment_count)
      out.push({
        id: "pay",
        title: "A payout is ready to request",
        detail: "Ask for payment of what is due",
        to: "/my/payouts",
      });
    if (o.onboarding_open)
      out.push({
        id: "onb",
        title: "Finish your onboarding",
        detail: `${o.onboarding_open} step${o.onboarding_open > 1 ? "s" : ""} left`,
        to: "/my/onboarding",
      });
    return out;
  }, [isAdmin, audit.data, overview.data]);

  // The dot means "something new since you last looked", not "there is activity".
  const newest = isAdmin ? (audit.data?.[0]?.id ?? 0) : notices.length;
  const [seen, setSeen] = useState(() => readSeen(isAdmin));
  const unread = isAdmin ? newest > seen : notices.length > 0;
  const toggle = () => {
    if (!open && isAdmin && newest) {
      setSeen(newest);
      writeSeen(newest);
    }
    setOpen(!open);
  };

  return (
    <div className="popover-anchor" ref={ref}>
      <button className="icon-btn" aria-label={unread ? "Notifications: new activity" : "Notifications"} aria-expanded={open} onClick={toggle}>
        <Bell size={22} strokeWidth={1.75} aria-hidden="true" />
        {unread && <span className="bell-dot" aria-hidden="true" />}
      </button>
      {open && (
        <div className="popover notices" role="dialog" aria-label="Notifications">
          <p className="popover-title">{isAdmin ? "Latest activity" : "For you"}</p>
          {notices.length === 0 ? (
            <p className="empty">You are all caught up.</p>
          ) : (
            notices.map((n) => (
              <button
                key={n.id}
                className="notice"
                onClick={() => {
                  setOpen(false);
                  navigate(n.to);
                }}
              >
                <span className="notice-title">{n.title}</span>
                <span className="notice-detail">{n.detail}</span>
              </button>
            ))
          )}
        </div>
      )}
    </div>
  );
}
