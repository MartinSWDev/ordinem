export interface Island {
  id: string;
  title: string;
  endpoint_base: string;
  credential_ref: string;
}

export interface Manifest {
  device_name: string;
  islands: Island[];
}

export type FetchOutcome =
  | { status: "ok"; code: number; body: string }
  | { status: "error"; message: string };
