import { useState, useEffect } from "react";
import { useParams, Link } from "react-router-dom";
import { useQuery, useMutation } from "@tanstack/react-query";
import {
  fetchTools,
  createJob,
  fetchJob,
  cancelJob,
  connectToJobProgress,
  type Job,
  type ProgressEvent,
} from "../api/client";
import "./ToolRunPage.css";

function ToolRunPage() {
  const { toolName } = useParams<{ toolName: string }>();
  const [formData, setFormData] = useState<Record<string, any>>({});
  const [currentJob, setCurrentJob] = useState<Job | null>(null);

  const { data: tools } = useQuery({
    queryKey: ["tools"],
    queryFn: fetchTools,
  });

  const tool = tools?.find((t) => t.name === toolName);

  const createJobMutation = useMutation({
    mutationFn: (args: Record<string, any>) =>
      createJob(toolName!, args),
    onSuccess: (job) => {
      setCurrentJob(job);
    },
  });

  const cancelJobMutation = useMutation({
    mutationFn: () => cancelJob(currentJob!.id),
    onSuccess: (job) => {
      setCurrentJob(job);
    },
  });

  // Connect to WebSocket for real-time progress
  useEffect(() => {
    if (!currentJob || currentJob.status === "completed" || currentJob.status === "failed" || currentJob.status === "cancelled") {
      return;
    }

    const ws = connectToJobProgress(
      currentJob.id,
      (event: ProgressEvent) => {
        setCurrentJob((prev) =>
          prev
            ? {
                ...prev,
                progress: event.progress,
                progress_message: event.message,
                status: event.status as any,
              }
            : null
        );
      },
      (error) => {
        console.error("WebSocket error:", error);
      }
    );

    return () => {
      ws.close();
    };
  }, [currentJob?.id]);

  // Poll for final results when job completes
  useEffect(() => {
    if (
      currentJob &&
      (currentJob.status === "completed" ||
        currentJob.status === "failed" ||
        currentJob.status === "cancelled")
    ) {
      fetchJob(currentJob.id).then(setCurrentJob);
    }
  }, [currentJob?.status]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const args: Record<string, any> = {};

    tool?.params.forEach((param) => {
      const value = formData[param.name];
      if (value !== undefined && value !== "") {
        if (param.type === "int") {
          args[param.name] = parseInt(value, 10);
        } else if (param.type === "float") {
          args[param.name] = parseFloat(value);
        } else if (param.type === "bool") {
          args[param.name] = value;
        } else {
          args[param.name] = value;
        }
      } else if (param.default !== null && param.default !== undefined) {
        args[param.name] = param.default;
      }
    });

    createJobMutation.mutate(args);
  };

  const handleInputChange = (name: string, value: any) => {
    setFormData((prev) => ({ ...prev, [name]: value }));
  };

  if (!tool) {
    return (
      <div className="container">
        <p>Tool not found</p>
        <Link to="/">← Back to tools</Link>
      </div>
    );
  }

  return (
    <div className="container">
      <div className="breadcrumb">
        <Link to="/">← Back to tools</Link>
      </div>

      <h2>{tool.name}</h2>
      <p className="tool-description">{tool.description}</p>

      <div className="tool-run-layout">
        <div className="form-section">
          <h3>Parameters</h3>
          <form onSubmit={handleSubmit} className="tool-form">
            {tool.params.map((param) => (
              <div key={param.name} className="form-field">
                <label htmlFor={param.name}>
                  {param.name}
                  {param.required && <span className="required">*</span>}
                </label>
                <p className="field-description">{param.description}</p>

                {param.type === "bool" ? (
                  <input
                    type="checkbox"
                    id={param.name}
                    checked={formData[param.name] === true}
                    onChange={(e) =>
                      handleInputChange(param.name, e.target.checked)
                    }
                  />
                ) : param.choices ? (
                  <select
                    id={param.name}
                    value={formData[param.name] || param.default || ""}
                    onChange={(e) =>
                      handleInputChange(param.name, e.target.value)
                    }
                    required={param.required}
                  >
                    <option value="">Select...</option>
                    {param.choices.map((choice) => (
                      <option key={choice} value={choice}>
                        {choice}
                      </option>
                    ))}
                  </select>
                ) : (
                  <input
                    type={param.type === "int" || param.type === "float" ? "number" : "text"}
                    id={param.name}
                    value={formData[param.name] || ""}
                    onChange={(e) =>
                      handleInputChange(param.name, e.target.value)
                    }
                    placeholder={param.default?.toString() || ""}
                    required={param.required}
                    step={param.type === "float" ? "any" : undefined}
                  />
                )}
              </div>
            ))}

            <button
              type="submit"
              disabled={createJobMutation.isPending || (currentJob?.status === "running")}
            >
              {createJobMutation.isPending ? "Submitting..." : "Run Tool"}
            </button>
          </form>
        </div>

        {currentJob && (
          <div className="results-section">
            <div className="job-header">
              <h3>Job Results</h3>
              <span className={`status-badge status-${currentJob.status}`}>
                {currentJob.status}
              </span>
            </div>

            <div className="job-info">
              <div className="job-id">
                <strong>Job ID:</strong> <code>{currentJob.id}</code>
              </div>

              {(currentJob.status === "running" || currentJob.status === "queued") && (
                <>
                  <div className="progress-bar">
                    <div
                      className="progress-fill"
                      style={{ width: `${currentJob.progress * 100}%` }}
                    />
                  </div>
                  <p className="progress-message">
                    {currentJob.progress_message || "Waiting..."}
                  </p>
                  <button
                    onClick={() => cancelJobMutation.mutate()}
                    disabled={cancelJobMutation.isPending}
                    className="cancel-button"
                  >
                    Cancel Job
                  </button>
                </>
              )}

              {currentJob.summary && (
                <div className="job-summary">
                  <strong>Summary:</strong> {currentJob.summary}
                </div>
              )}

              {currentJob.error && (
                <div className="job-error">
                  <strong>Error:</strong> {currentJob.error}
                </div>
              )}

              {currentJob.data && Object.keys(currentJob.data).length > 0 && (
                <div className="job-data">
                  <strong>Data:</strong>
                  <pre>{JSON.stringify(currentJob.data, null, 2)}</pre>
                </div>
              )}

              {currentJob.artifacts &&
                Object.keys(currentJob.artifacts).length > 0 && (
                  <div className="job-artifacts">
                    <strong>Artifacts:</strong>
                    <ul>
                      {Object.entries(currentJob.artifacts).map(
                        ([name, path]) => (
                          <li key={name}>
                            {name}: <code>{path}</code>
                          </li>
                        )
                      )}
                    </ul>
                  </div>
                )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

export default ToolRunPage;
