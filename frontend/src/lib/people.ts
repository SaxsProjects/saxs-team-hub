import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { Person } from "../api/types";

/** Everyone in the team directory, plus a quick id -> name lookup. */
export function usePeople() {
  const q = useQuery({ queryKey: ["people"], queryFn: () => api<Person[]>("/api/people") });
  const names = new Map((q.data ?? []).map((p) => [p.id, p.full_name]));
  return { ...q, names, nameOf: (id: number) => names.get(id) ?? `Person #${id}` };
}

/** People a Task Order or project share can be given to: they accepted an offer. */
export const WORKING_STAGES = new Set(["accepted", "agreement_signed", "onboarded"]);
