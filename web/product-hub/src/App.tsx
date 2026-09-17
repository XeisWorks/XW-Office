import { useState } from "react";
import { NavLink, Route, Routes } from "react-router-dom";
import { clearToken, getToken } from "./api/client";
import TokenGate from "./components/TokenGate";
import DashboardPage from "./pages/DashboardPage";
import ProductListPage from "./pages/ProductListPage";
import ProductDetailPage from "./pages/ProductDetailPage";
import ConflictListPage from "./pages/ConflictListPage";
import ConflictWizardPage from "./pages/ConflictWizardPage";

export default function App() {
  const [hasToken, setHasToken] = useState<boolean>(() => Boolean(getToken()));

  function handleUnauthorized() {
    setHasToken(false);
  }

  function handleLogout() {
    clearToken();
    setHasToken(false);
  }

  if (!hasToken) {
    return <TokenGate onSaved={() => setHasToken(true)} />;
  }

  return (
    <div className="app-shell">
      <header className="app-header">
        <span className="brand">XW Product Hub</span>
        <nav className="app-nav">
          <NavLink to="/" end>
            Dashboard
          </NavLink>
          <NavLink to="/products">Produkte</NavLink>
          <NavLink to="/conflicts">Konflikte</NavLink>
        </nav>
        <button className="link-button" onClick={handleLogout} type="button">
          Abmelden
        </button>
      </header>
      <main className="app-main">
        <Routes>
          <Route path="/" element={<DashboardPage onUnauthorized={handleUnauthorized} />} />
          <Route path="/products" element={<ProductListPage onUnauthorized={handleUnauthorized} />} />
          <Route
            path="/products/:id"
            element={<ProductDetailPage onUnauthorized={handleUnauthorized} />}
          />
          <Route path="/conflicts" element={<ConflictListPage onUnauthorized={handleUnauthorized} />} />
          <Route path="/conflicts/wizard" element={<ConflictWizardPage onUnauthorized={handleUnauthorized} />} />
          <Route path="/conflicts/:id" element={<ConflictWizardPage onUnauthorized={handleUnauthorized} />} />
          <Route path="*" element={<p className="hint">Seite nicht gefunden.</p>} />
        </Routes>
      </main>
      <footer className="app-footer">
        Product Hub · Änderungen sind versioniert, auditiert und vor Channel-Syncs prüfbar.
      </footer>
    </div>
  );
}
