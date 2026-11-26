import {
  FileClock,
  FileText,
  Folder,
  LayoutDashboard,
  ListChecks,
  Settings2,
  SquareCheck,
  Users,
  Wallet,
  type LucideIcon,
} from "lucide-react";

export interface NavItem {
  to: string;
  label: string;
  /** Title shown in the top bar. */
  title: string;
  icon: LucideIcon;
  badgeKey?: "reviews";
}

export const FOUNDER_NAV: NavItem[] = [
  { to: "/", label: "Overview", title: "Business overview", icon: LayoutDashboard },
  { to: "/team", label: "Team & offers", title: "Team & offers", icon: Users },
  { to: "/projects", label: "Projects", title: "Projects", icon: Folder },
  { to: "/task-orders", label: "Task Orders", title: "Task Orders", icon: SquareCheck, badgeKey: "reviews" },
  { to: "/finance", label: "Client finance", title: "Client finance", icon: FileText },
  { to: "/payouts", label: "Payouts", title: "Payouts", icon: Wallet },
  { to: "/audit", label: "Audit history", title: "Audit history", icon: FileClock },
];

export const MEMBER_NAV: NavItem[] = [
  { to: "/", label: "My overview", title: "My workspace", icon: LayoutDashboard },
  { to: "/my/projects", label: "My projects", title: "My projects", icon: Folder },
  { to: "/my/task-orders", label: "My Task Orders", title: "My Task Orders", icon: SquareCheck },
  { to: "/my/payouts", label: "My payouts", title: "My payouts", icon: Wallet },
  { to: "/my/documents", label: "My documents", title: "My documents", icon: FileText },
  { to: "/my/onboarding", label: "Onboarding", title: "Onboarding", icon: ListChecks },
];

export const SETTINGS_ITEM: NavItem = { to: "/settings", label: "Settings", title: "Settings", icon: Settings2 };
