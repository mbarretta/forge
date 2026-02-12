import { Link } from "react-router-dom";
import "./JobHistoryPage.css";

function JobHistoryPage() {
  return (
    <div className="container">
      <h2>Job History</h2>
      <p className="coming-soon">
        Job history view coming soon. For now, jobs are stored in Redis with a
        1-hour TTL.
      </p>
      <Link to="/" className="back-link">
        ← Back to tools
      </Link>
    </div>
  );
}

export default JobHistoryPage;
