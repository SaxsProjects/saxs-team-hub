import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bell, ChevronRight, CircleHelp, LogOut, Menu, X } from "lucide-react";
import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { NavLink, useLocation, useNavigate } from "react-router";
import { api, post } from "../api/client";
import type { Dashboard, NotificationList } from "../api/types";
import { useAuth } from "../auth/AuthContext";
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

/** The bell: the user's own notifications from the server, with the number still unread. */
function Notifications({ isAdmin }: { isAdmin: boolean }) {
  const { open, setOpen, ref } = usePopover();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const list = useQuery({
    queryKey: ["notifications"],
    queryFn: () => api<NotificationList>("/api/notifications?limit=20"),
    refetchInterval: 30_000,
    refetchOnWindowFocus: true,
  });
  const unread = list.data?.unread ?? 0;
  const items = list.data?.items ?? [];
  const refresh = () => qc.invalidateQueries({ queryKey: ["notifications"] });
  const readOne = useMutation({ mutationFn: (id: number) => post("/api/notifications/read", { ids: [id] }), onSettled: refresh });
  const readAll = useMutation({ mutationFn: () => post("/api/notifications/read-all"), onSettled: refresh });
  const label = unread ? `Notifications: ${unread} unread` : "Notifications";

  return (
    <div className="popover-anchor" ref={ref}>
      <button className="icon-btn" aria-label={label} aria-expanded={open} onClick={() => setOpen(!open)}>
        <Bell size={22} strokeWidth={1.75} aria-hidden="true" />
        {unread > 0 && (
          <span className="bell-count" aria-hidden="true">
            {unread > 99 ? "99+" : unread}
          </span>
        )}
      </button>
      {open && (
        <div className="popover notices" role="dialog" aria-label="Notifications">
          <div className="popover-head">
            <p className="popover-title">{isAdmin ? "Notifications" : "For you"}</p>
            {unread > 0 && (
              <button className="link-btn" onClick={() => readAll.mutate()} disabled={readAll.isPending}>
                Mark all as read
              </button>
            )}
          </div>
          {items.length === 0 ? (
            <p className="empty">{list.isLoading ? "Loading..." : "You are all caught up."}</p>
          ) : (
            <div className="notice-list">
              {items.map((n) => (
                <button
                  key={n.id}
                  className={`notice${n.read_at ? "" : " is-unread"}`}
                  onClick={() => {
                    if (!n.read_at) readOne.mutate(n.id);
                    setOpen(false);
                    if (n.link) navigate(n.link);
                  }}
                >
                  <span className="notice-title">{n.title}</span>
                  {n.body && <span className="notice-detail notice-body">{n.body}</span>}
                  <span className="notice-detail">
                    {shortDate(n.created_at)} {clock(n.created_at)}
                  </span>
                </button>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
