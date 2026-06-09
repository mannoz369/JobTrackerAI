import { ApplicationDetailView } from "@/components/applications/application-detail";

export default async function ApplicationPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  return <ApplicationDetailView applicationId={id} />;
}
