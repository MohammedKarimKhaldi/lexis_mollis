import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";

export function loadJson<T>(relativePath: string, fallback: T): T {
  const path = join(process.cwd(), relativePath);
  if (!existsSync(path)) return fallback;
  return JSON.parse(readFileSync(path, "utf-8")) as T;
}

export interface DocumentSummary {
  document_id: string;
  title: string;
  year?: number | null;
  doc_type?: string | null;
  languages?: string[];
  quality_score?: number | null;
  review_required?: boolean;
  review_priority?: string | null;
  text_preview?: string;
  tags?: string[];
  source_url?: string | null;
}

export interface SiteManifest {
  generated_at?: string;
  source?: string;
  document_count?: number;
  page_count?: number;
  graph_node_count?: number;
  graph_edge_count?: number;
  pipeline_version?: string;
}
