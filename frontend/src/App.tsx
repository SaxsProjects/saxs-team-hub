import { lazy, Suspense } from "react";
import { Navigate, Route, Routes } from "react-router";
import { useAuth } from "./auth/AuthContext";
import { AppShell } from "./components/AppShell";
import { Skeleton } from "./components/ui";
import { FounderOverview } from "./pages/FounderOverview";
import { MyWorkspace } from "./pages/MyWorkspace";
import { MemberSettings } from "./pages/member/MemberSettings";
import { MyDocuments } from "./pages/member/MyDocuments";
import { MyPayouts } from "./pages/member/MyPayouts";
import { MyProjects } from "./pages/member/MyProjects";
import { MyTaskOrders } from "./pages/member/MyTaskOrders";
import { Onboarding } from "./pages/member/Onboarding";
import { SignIn } from "./pages/SignIn";

// Founder-only screens load on demand, so team members never download them.
const AuditHistory = lazy(() =>
  import("./pages/founder/AuditHistory").then((m) => ({
    default: m.AuditHistory,
  })),
);
const Finance = lazy(() =>
  import("./pages/founder/Finance").then((m) => ({ default: m.Finance })),
);
const FounderSettings = lazy(() =>
  import("./pages/founder/FounderSettings").then((m) => ({
    default: m.FounderSettings,
  })),
);
const MemberProfile = lazy(() =>
  import("./pages/founder/MemberProfile").then((m) => ({
    default: m.MemberProfile,
  })),
);
const Payouts = lazy(() =>
  import("./pages/founder/Payouts").then((m) => ({ default: m.Payouts })),
);
const ProjectDetail = lazy(() =>
  import("./pages/founder/ProjectDetail").then((m) => ({
    default: m.ProjectDetail,
  })),
);
const Projects = lazy(() =>
  import("./pages/founder/Projects").then((m) => ({ default: m.Projects })),
);
const TaskOrders = lazy(() =>
  import("./pages/founder/TaskOrders").then((m) => ({ default: m.TaskOrders })),
);
const TeamOffers = lazy(() =>
  import("./pages/founder/TeamOffers").then((m) => ({ default: m.TeamOffers })),
);
const Templates = lazy(() => import("./pages/founder/Templates").then((m) => ({ default: m.Templates })));
const Enquiries = lazy(() => import("./pages/founder/Enquiries").then((m) => ({ default: m.Enquiries })));
const Proposals = lazy(() => import("./pages/founder/Proposals").then((m) => ({ default: m.Proposals })));
const Certificates = lazy(() => import("./pages/founder/Certificates").then((m) => ({ default: m.Certificates })));
const Reports = lazy(() => import("./pages/founder/Reports").then((m) => ({ default: m.Reports })));

export function App() {
  const { me, loading } = useAuth();
  if (loading)
    return (
      <div
        style={{ padding: 48, maxWidth: 480, margin: "0 auto" }}
        aria-busy="true"
        aria-label="Loading"
      >
        <Skeleton h={24} />
      </div>
    );
  if (!me)
    return (
      <Routes>
        <Route path="*" element={<SignIn />} />
      </Routes>
    );

  const isAdmin = me.role === "admin";
  if (!isAdmin)
    return (
      <AppShell>
        <Routes>
          <Route path="/" element={<MyWorkspace />} />
          <Route path="/my/projects" element={<MyProjects />} />
          <Route path="/my/task-orders" element={<MyTaskOrders />} />
          <Route path="/my/payouts" element={<MyPayouts />} />
          <Route path="/my/documents" element={<MyDocuments />} />
          <Route path="/my/onboarding" element={<Onboarding />} />
          <Route path="/settings" element={<MemberSettings />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </AppShell>
    );

  return (
    <AppShell>
      <Suspense fallback={<Skeleton h={160} />}>
        <Routes>
          <Route path="/" element={<FounderOverview />} />
          <Route path="/team" element={<TeamOffers />} />
          <Route path="/team/:id" element={<MemberProfile />} />
          <Route path="/projects" element={<Projects />} />
          <Route path="/projects/:id" element={<ProjectDetail />} />
          <Route path="/task-orders" element={<TaskOrders />} />
          <Route
            path="/finance"
            element={<Navigate to="/finance/clients" replace />}
          />
          <Route path="/finance/:tab" element={<Finance />} />
          <Route path="/payouts" element={<Payouts />} />
          <Route path="/audit" element={<AuditHistory />} />
          <Route path="/templates" element={<Templates />} />
          <Route path="/enquiries" element={<Enquiries />} />
          <Route path="/proposals" element={<Proposals />} />
          <Route path="/certificates" element={<Certificates />} />
          <Route path="/reports" element={<Reports />} />
          <Route path="/settings" element={<FounderSettings />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Suspense>
    </AppShell>
  );
}
