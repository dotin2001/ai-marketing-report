import { ReportListing } from "./report-listing";

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export default async function ReportsPage({
  searchParams,
}: {
  searchParams?: Promise<{ created?: string }>;
}) {
  const params = await searchParams;
  const createdId = params?.created && UUID_PATTERN.test(params.created) ? params.created : undefined;
  return <main><ReportListing createdId={createdId} /></main>;
}

