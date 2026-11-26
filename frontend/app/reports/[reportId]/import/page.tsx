import { ImportPage } from "./report-import";

export default async function ReportImportRoute({ params }: { params: Promise<{ reportId: string }> }) {
  const { reportId } = await params;
  return <main><ImportPage reportId={reportId} /></main>;
}
