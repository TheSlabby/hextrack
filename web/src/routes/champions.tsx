/**
 * /champions: every champion's win / pick / ban rate in a patch window, filterable by role
 * and sortable. Filters and sort live in the URL (defaults omitted).
 */
import { useDocumentTitle, pageTitle } from "@/lib/hooks";

export function ChampionsPage() {
  useDocumentTitle(pageTitle("Champions"));
  return <div className="flex min-w-0 flex-col gap-4 sm:gap-5">Champions</div>;
}
