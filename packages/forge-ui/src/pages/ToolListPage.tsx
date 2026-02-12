import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { fetchTools } from "../api/client";
import "./ToolListPage.css";

function ToolListPage() {
  const { data: tools, isLoading, error } = useQuery({
    queryKey: ["tools"],
    queryFn: fetchTools,
  });

  if (isLoading) {
    return (
      <div className="container">
        <p>Loading tools...</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="container">
        <p className="error">Error: {(error as Error).message}</p>
      </div>
    );
  }

  return (
    <div className="container">
      <h2>Available Tools</h2>
      <div className="tools-grid">
        {tools?.map((tool) => (
          <Link
            key={tool.name}
            to={`/tool/${tool.name}`}
            className="tool-card"
          >
            <h3>{tool.name}</h3>
            <p className="tool-description">{tool.description}</p>
            <div className="tool-meta">
              <span className="tool-version">v{tool.version}</span>
              <span className="tool-params">
                {tool.params.length} parameter{tool.params.length !== 1 ? "s" : ""}
              </span>
            </div>
          </Link>
        ))}
      </div>
      {(!tools || tools.length === 0) && (
        <p className="empty">No tools available</p>
      )}
    </div>
  );
}

export default ToolListPage;
