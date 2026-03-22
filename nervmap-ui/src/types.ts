/** Types matching NervMap JSON output */

export interface Service {
  id: string;
  name: string;
  type: string;
  status: string;
  ports: number[];
  pid: number | null;
  health: string;
  metadata: Record<string, unknown>;
}

export interface Connection {
  source: string;
  target: string;
  type: string;
  source_port: number | null;
  target_port: number | null;
  confidence: number;
}

export interface Issue {
  rule_id: string;
  severity: string;
  service: string;
  message: string;
  hint: string;
  impact: string[];
}

export interface ConfigNode {
  path: string;
  config_type: string;
  role?: string;
  detection?: string;
  confidence: number;
  exists: boolean;
  content_hash?: string;
  children?: ConfigNode[];
}

export interface AIChain {
  id: string;
  status: string;
  session?: {
    terminal_type?: string;
    terminal_port?: number;
    mux_type?: string;
    mux_session?: string;
  };
  agent?: {
    agent_type: string;
    pid: number;
    cwd: string;
    display_name: string;
  };
  configs?: ConfigNode[];
  backend?: {
    backend_type: string;
    provider: string;
    endpoint: string;
    auth_method?: string;
    model_name?: string;
    gpu_layers?: number;
    context_size?: number;
  };
  proxy?: {
    proxy_type: string;
    listen_port?: number;
    listen_bind?: string;
    target_port?: number;
    target_host?: string;
  };
  consumers?: string[];
}

export interface NervMapState {
  version: string;
  services: Service[];
  connections: Connection[];
  issues: Issue[];
  ai_chains?: AIChain[];
  summary: {
    total_services: number;
    total_connections: number;
    total_issues: number;
    critical: number;
    warnings: number;
    info: number;
  };
  scanned_at?: number;
}

export interface FileEntry {
  name: string;
  path: string;
  type: "file" | "directory";
  size: number;
  mtime: number;
  is_symlink: boolean;
  symlink_target?: string;
}
