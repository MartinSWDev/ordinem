import { islandClient } from "../../core/api";
import type { Island } from "../../core/types";
import type { RepoRef, Review } from "./types";

export { ApiError } from "../../core/api";

/** Review-island client: list repos, run a review, fetch one. Everything hangs
 *  off the island's `/reviews` base. */
export function useReview(island: Island) {
  const { request } = islandClient(island);

  return {
    listRepos: () => request<RepoRef[]>("GET", "/repos"),
    runReview: (repoId: string, baseBranch: string | null, headBranch: string | null) =>
      request<Review>("POST", "", {
        repo_id: repoId,
        base_branch: baseBranch || null,
        head_branch: headBranch || null,
      }),
    getReview: (id: string) => request<Review>("GET", `/${id}`),
  };
}
