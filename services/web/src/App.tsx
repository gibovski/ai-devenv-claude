import { useEffect, useState } from "react";
import { NavLink, Navigate, Route, Routes } from "react-router-dom";
import { api, type Me } from "./api";
import Login from "./pages/Login";
import Settings from "./pages/Settings";
import Apply from "./pages/Apply";
import ChangePassword from "./pages/ChangePassword";
import Dashboard from "./pages/Dashboard";
import Queue from "./pages/Queue";
import Graph from "./pages/Graph";
import TaskDetail from "./pages/TaskDetail";

export const NAV: { to: string; label: string }[] = [
  { to: "/dashboard", label: "Agents" },
  { to: "/queue", label: "Queue" },
  { to: "/graph", label: "Graph" },
  { to: "/settings", label: "Settings" },
  { to: "/apply", label: "Apply" },
];

export default function App() {
  const [me, setMe] = useState<Me | null | undefined>(undefined);
  const refresh = () =>
    api<Me>("/api/auth/me")
      .then(setMe)
      .catch(() => setMe(null));
  useEffect(() => {
    refresh();
  }, []);

  if (me === undefined) return <div className="center">Loading…</div>;
  if (me === null) return <Login onLogin={refresh} />;
  if (me.must_change_password) return <ChangePassword onDone={refresh} firstLogin />;

  const logout = async () => {
    await api("/api/auth/logout", { method: "POST" });
    setMe(null);
  };

  return (
    <div className="layout">
      <nav className="sidebar">
        <h1>AI Dev Env</h1>
        {NAV.map((n) => (
          <NavLink key={n.to} to={n.to}>
            {n.label}
          </NavLink>
        ))}
        <div className="spacer" />
        <NavLink to="/password">Password</NavLink>
        <button className="link" onClick={logout}>
          Log out
        </button>
      </nav>
      <main>
        <Routes>
          <Route path="/" element={<Navigate to={NAV[0].to} replace />} />
          <Route path="/dashboard" element={<Dashboard />} />
          <Route path="/queue" element={<Queue />} />
          <Route path="/graph" element={<Graph />} />
          <Route path="/tasks/:id" element={<TaskDetail />} />
          <Route path="/settings" element={<Settings />} />
          <Route path="/apply" element={<Apply />} />
          <Route path="/password" element={<ChangePassword onDone={refresh} />} />
          <Route path="*" element={<p>Not found.</p>} />
        </Routes>
      </main>
    </div>
  );
}
