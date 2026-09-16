import { Link } from "react-router-dom";
import { api } from "../api/client";
import AsyncState from "../components/AsyncState";
import { useApi } from "../hooks/useApi";

interface DashboardPageProps {
  onUnauthorized: () => void;
}

/**
 * Dashboard tiles are deliberately limited to what the hub can actually compute
 * today (PR07): total/wix-ready/b2b-ready/print-ready/sevdesk-ready/missing-cover/
 * open-improvements. low_stock/out_of_stock/sync_conflicts need the inventory
 * ledger and sync-conflict tables from later PRs (PR13+) - this page will grow
 * tiles as those land, not show placeholders for data that does not exist yet.
 */
export default function DashboardPage({ onUnauthorized }: DashboardPageProps) {
  const { data, error, loading } = useApi(api.getReadinessSummary, [], onUnauthorized);

  return (
    <section>
      <h1>Dashboard</h1>
      <AsyncState loading={loading} error={error} />
      {data && (
        <div className="tile-grid">
          <Link to="/products" className="tile">
            <span className="tile-value">{data.total_products}</span>
            <span className="tile-label">Produkte gesamt</span>
          </Link>
          <Link to="/products" className="tile">
            <span className="tile-value">{data.wix_ready}</span>
            <span className="tile-label">Wix-ready</span>
          </Link>
          <Link to="/products" className="tile">
            <span className="tile-value">{data.b2b_ready}</span>
            <span className="tile-label">B2B-ready</span>
          </Link>
          <Link to="/products" className="tile">
            <span className="tile-value">{data.print_ready}</span>
            <span className="tile-label">Print-ready</span>
          </Link>
          <Link to="/products" className="tile">
            <span className="tile-value">{data.sevdesk_ready}</span>
            <span className="tile-label">sevdesk-ready</span>
          </Link>
          <Link to="/products" className="tile tile-warn">
            <span className="tile-value">{data.missing_cover}</span>
            <span className="tile-label">ohne Cover</span>
          </Link>
          <Link to="/products" className="tile tile-warn">
            <span className="tile-value">{data.open_improvements}</span>
            <span className="tile-label">offene Verbesserungen</span>
          </Link>
        </div>
      )}
    </section>
  );
}
