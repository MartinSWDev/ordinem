// Shared shell types — the manifest, islands, and the Rust api_request outcome.

export interface Island {
  id: string;
  title: string;
  endpoint_base: string;
  credential_ref: string;
  /** Optional custom component key (e.g. "tickets"). Falls back to generic panel. */
  component?: string | null;
}

export interface Manifest {
  device_name: string;
  islands: Island[];
}

export type FetchOutcome =
  | { status: "ok"; code: number; body: string }
  | { status: "error"; message: string };
