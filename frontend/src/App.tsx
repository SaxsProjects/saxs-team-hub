import { Navigate, Route, Routes } from "react-router";
import { useAuth } from "./auth/AuthContext";
import { AppShell } from "./components/AppShell";
import { FOUNDER_NAV, MEMBER_NAV, SETTINGS_ITEM } from "./components/nav";
import { ComingSoon, Skeleton } from "./components/ui";
import { FounderOverview } from "./pages/FounderOverview";
import { MyWorkspace } from "./pages/MyWorkspace";
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
  // Screens arriving in phases 2 and 3; each route exists now so the menu works.
  const later = (isAdmin ? FOUNDER_NAV : MEMBER_NAV).slice(1).concat(SETTINGS_ITEM);
  return (
    <AppShell>
      <Routes>
        <Route path="/" element={isAdmin ? <FounderOverview /> : <MyWorkspace />} />
        {later.map((item) => (
          <Route key={item.to} path={`${item.to}/*`} element={<ComingSoon title={item.title} />} />
        ))}
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </AppShell>
  );
}
