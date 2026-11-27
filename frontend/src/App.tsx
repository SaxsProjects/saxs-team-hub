import { Navigate, Route, Routes } from "react-router";
import { useAuth } from "./auth/AuthContext";
import { AppShell } from "./components/AppShell";
import { FOUNDER_NAV, SETTINGS_ITEM } from "./components/nav";
import { ComingSoon, Skeleton } from "./components/ui";
import { FounderOverview } from "./pages/FounderOverview";
import { MyWorkspace } from "./pages/MyWorkspace";
import { MemberSettings } from "./pages/member/MemberSettings";
import { MyDocuments } from "./pages/member/MyDocuments";
import { MyPayouts } from "./pages/member/MyPayouts";
import { MyProjects } from "./pages/member/MyProjects";
import { MyTaskOrders } from "./pages/member/MyTaskOrders";
import { Onboarding } from "./pages/member/Onboarding";
import { SignIn } from "./pages/SignIn";

export function App() {
  const { me, loading } = useAuth();
  if (loading)
    return (
      <div style={{ padding: 48, maxWidth: 480, margin: "0 auto" }} aria-busy="true" aria-label="Loading">
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

  // Founder screens arriving in phase 3; each route exists now so the menu works.
  const later = FOUNDER_NAV.slice(1).concat(SETTINGS_ITEM);
  return (
    <AppShell>
      <Routes>
        <Route path="/" element={<FounderOverview />} />
        {later.map((item) => (
          <Route key={item.to} path={`${item.to}/*`} element={<ComingSoon title={item.title} />} />
        ))}
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </AppShell>
  );
}
