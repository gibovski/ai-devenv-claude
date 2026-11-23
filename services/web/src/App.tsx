import { useEffect, useState } from "react";
import { NavLink, Navigate, Route, Routes } from "react-router-dom";
import { api, type Me } from "./api";
import Login from "./pages/Login";
import Settings from "./pages/Settings";
import Apply from "./pages/Apply";
import ChangePassword from "./pages/ChangePassword";

export const NAV: { to: string; label: string }[] = [
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
          <Route path="/settings" element={<Settings />} />
          <Route path="/apply" element={<Apply />} />
          <Route path="/password" element={<ChangePassword onDone={refresh} />} />
          <Route path="*" element={<p>Not found.</p>} />
        </Routes>
      </main>
    </div>
  );
}
