const API_BASE = "/api";

export interface ToolParam {
  name: string;
  description: string;
  type: string;
  required: boolean;
  default: any;
  choices: string[] | null;
}

export interface Tool {
  name: string;
  description: string;
  version: string;
  params: ToolParam[];
}

export interface Job {
  id: string;
  tool: string;
  status: "queued" | "running" | "completed" | "failed" | "cancelled";
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  progress: number;
  progress_message: string;
  summary: string | null;
  data: Record<string, any> | null;
  artifacts: Record<string, string> | null;
  error: string | null;
}

export interface ProgressEvent {
  job_id: string;
  progress: number;
  message: string;
  status: string;
}

export async function fetchTools(): Promise<Tool[]> {
  const response = await fetch(`${API_BASE}/tools`);
  if (!response.ok) {
    throw new Error("Failed to fetch tools");
  }
  return response.json();
}

export async function createJob(
  tool: string,
  args: Record<string, any>
): Promise<Job> {
  const response = await fetch(`${API_BASE}/jobs`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ tool, args }),
  });

  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || "Failed to create job");
  }

  return response.json();
}

export async function fetchJob(jobId: string): Promise<Job> {
  const response = await fetch(`${API_BASE}/jobs/${jobId}`);
  if (!response.ok) {
    throw new Error("Failed to fetch job");
  }
  return response.json();
}

export async function cancelJob(jobId: string): Promise<Job> {
  const response = await fetch(`${API_BASE}/jobs/${jobId}/cancel`, {
    method: "POST",
  });
  if (!response.ok) {
    throw new Error("Failed to cancel job");
  }
  return response.json();
}

export function connectToJobProgress(
  jobId: string,
  onProgress: (event: ProgressEvent) => void,
  onError?: (error: Event) => void
): WebSocket {
  const wsProtocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  const wsUrl = `${wsProtocol}//${window.location.host}/api/jobs/${jobId}/ws`;

  const ws = new WebSocket(wsUrl);

  ws.onmessage = (event) => {
    const data = JSON.parse(event.data);
    onProgress(data);
  };

  if (onError) {
    ws.onerror = onError;
  }

  return ws;
}
