import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { useAuth } from "../auth";

const TABS = [
  { to: "/directory", label: "Directory" },
  { to: "/digest", label: "Digest" },
  { to: "/profile", label: "Profile" },
];

export function AppShell() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  async function handleLogout() {
    await logout();
    navigate("/login", { replace: true });
  }

  return (
    <div className="app">
      <header className="app-header">
        <div className="brand">Edge Mosaic</div>
        <nav className="tabs">
          {TABS.map((t) => (
            <NavLink
              key={t.to}
              to={t.to}
              className={({ isActive }) => (isActive ? "tab tab-active" : "tab")}
            >
              {t.label}
            </NavLink>
          ))}
        </nav>
        <div className="header-right">
          <span className="muted">{user?.display_name ?? user?.email}</span>
          <button className="btn btn-ghost" onClick={handleLogout}>
            Log out
          </button>
        </div>
      </header>
      <main className="app-main">
        <Outlet />
      </main>
    </div>
  );
}
